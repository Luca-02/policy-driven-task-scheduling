"""
core.py: the Runner that ties everything together for one replica.

Responsibilities: connect to the cluster, build the records, start the watchers
and the recorder thread, run the submitter, drive the progress/termination loop,
and write the outputs. Correlation lives in Recorder, streaming in Watchers,
serialisation in output; this file is orchestration and the submit bodies.
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from .output import EventsWriter, write_nodes_csv, write_summary, write_tasks_csv
from .record import Record, WatchEvent
from .recorder import Recorder
from .scenario import Task, load_conventions, load_tasks
from .util import is_num, log, pick
from .watchers import Watchers

DEFAULT_PROGRESS_SECONDS = 1.0
DEFAULT_FLUSH_SECONDS = 30.0
DEFAULT_TIMEOUT_WINDOWS = 10  # timeout = submission span + this many windows


class Runner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.scenario_dir = Path(args.scenario)
        self.config_json = json.loads((self.scenario_dir / "config.json").read_text())
        self.conv = load_conventions(self.config_json)
        self.scenario = self.config_json["scenario"]
        self.replica = args.replica

        self.tasks = load_tasks(self._resolve_tasks_path())

        # Knobs: CLI overrides scenario.
        self.rate_seconds = pick(args.rate_seconds, self.scenario["rate_seconds"])
        self.sanitize_interval = pick(
            args.sanitize_interval_seconds,
            self.scenario["sanitize_interval_seconds"],
        )
        self.namespace = pick(args.namespace, self.conv.task_namespace)
        self.mode = pick(args.mode, self.scenario.get("mode", "system"))

        # Timeout: explicit 0 (or negative) => no global timeout.
        if args.timeout_seconds is not None:
            self.timeout_seconds = args.timeout_seconds
        else:
            submission_span = len(self.tasks) * self.rate_seconds
            self.timeout_seconds = (
                submission_span + DEFAULT_TIMEOUT_WINDOWS * self.sanitize_interval
            )
        self.no_timeout = self.timeout_seconds <= 0

        self.results_dir = self._resolve_results_dir()
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # State.
        self.records: dict[int, Record] = {}
        self.order: list[int] = [t.task_id for t in self.tasks]
        self.events_q: "queue.Queue[WatchEvent]" = queue.Queue()
        self.stop = threading.Event()
        self.t0 = 0.0
        self.t0_epoch = 0.0

        self.recorder: Recorder | None = None
        self.events_writer: EventsWriter | None = None

        self.k8s_core: client.CoreV1Api | None = None
        self.k8s_batch: client.BatchV1Api | None = None
        self.k8s_custom: client.CustomObjectsApi | None = None

    # -- path resolution ------------------------------------------------------

    def _resolve_tasks_path(self) -> Path:
        if self.args.tasks_file:
            return Path(self.args.tasks_file)
        replicas = self.config_json.get("derived", {}).get("replicas", 1)
        name = f"tasks_r{self.replica}.csv" if replicas > 1 else "tasks.csv"
        return self.scenario_dir / name

    def _resolve_results_dir(self) -> Path:
        if self.args.results:
            return Path(self.args.results)
        return Path("results") / self.scenario["name"] / f"run_{self.replica}"

    # -- lifecycle ------------------------------------------------------------

    def run(self) -> int:
        self._connect()
        for t in self.tasks:
            self.records[t.task_id] = Record(
                task_id=t.task_id,
                name=t.name,
                issuer=t.issuer,
                context=t.context,
                context_degree=t.context_degree,
                datasets=json.dumps(t.datasets),
                replica=self.replica,
                t_submit_planned=t.submit_offset_s,
            )
        self.recorder = Recorder(self.records, self.conv)
        self.events_writer = EventsWriter(self.results_dir / "events.csv")

        self.t0 = time.perf_counter()
        self.t0_epoch = time.time()
        log(
            "start",
            f"scenario '{self.scenario['name']}' replica {self.replica}, "
            f"{len(self.tasks)} tasks, mode={self.mode}, "
            f"timeout={'none' if self.no_timeout else f'{self.timeout_seconds:.0f}s'}",
        )

        watchers = Watchers(
            k8s_core=self.k8s_core,
            k8s_batch=self.k8s_batch,
            k8s_custom=self.k8s_custom,
            conv=self.conv,
            namespace=self.namespace,
            mode=self.mode,
            events_q=self.events_q,
            stop=self.stop,
            now=self._now,
        ).start()

        recorder_th = threading.Thread(target=self._recorder_loop, name="recorder")
        recorder_th.start()
        submitter_th = threading.Thread(target=self._submitter_loop, name="submitter")
        submitter_th.start()

        try:
            self._progress_loop()
        except KeyboardInterrupt:
            log("interrupt", "stopping early on user request")

        self.stop.set()
        submitter_th.join(timeout=5)
        recorder_th.join(timeout=10)
        for w in watchers:
            w.join(timeout=2)

        self._mark_timed_out()
        self._flush_outputs()
        self._write_summary()
        self.events_writer.close()
        log("done", f"results in {self.results_dir}")
        return 0

    def _connect(self) -> None:
        try:
            config.load_kube_config()
        except Exception:
            config.load_incluster_config()
        self.k8s_core = client.CoreV1Api()
        self.k8s_batch = client.BatchV1Api()
        self.k8s_custom = client.CustomObjectsApi()

    # -- submitter ------------------------------------------------------------

    def _submitter_loop(self) -> None:
        for t in self.tasks:
            if self.stop.is_set():
                return
            self._sleep_until(self.t0 + t.submit_offset_s)
            if self.stop.is_set():
                return
            self._submit_one(t)

    def _submit_one(self, t: Task) -> None:
        rec = self.records[t.task_id]
        if self.mode == "baseline":
            body = self._build_job_body(t)
            start = self._now()
            try:
                self.k8s_batch.create_namespaced_job(self.namespace, body)
                status = 201
            except ApiException as e:
                status = e.status or -1
            end = self._now()
        else:
            body = self._build_tr_body(t)
            start = self._now()
            try:
                self.k8s_custom.create_namespaced_custom_object(
                    group=self.conv.group,
                    version=self.conv.version,
                    namespace=self.namespace,
                    plural=self.conv.tr_plural,
                    body=body,
                )
                status = 201
            except ApiException as e:
                status = e.status or -1
            end = self._now()

        rec.t_submit_start = start
        rec.t_submit_end = end
        rec.admission_status = status
        rec.admitted = status == 201

    def _build_tr_body(self, t: Task) -> dict[str, Any]:
        spec: dict[str, Any] = {"issuer": t.issuer, "datasets": t.datasets}
        if t.requirements:
            spec["requirements"] = t.requirements
        if t.geo:
            spec["geo"] = t.geo
        return {
            "apiVersion": self.conv.api_version,
            "kind": "TaskRequest",
            "metadata": {"name": t.name, "namespace": self.namespace},
            "spec": spec,
        }

    def _build_job_body(self, t: Task) -> client.V1Job:
        """Baseline: a plain Job equivalent to the controller's output, on the
        default scheduler, with no TaskRequest / Gatekeeper / custom plugins."""
        duration = int(self.scenario["task_duration_seconds"])
        container = client.V1Container(
            name="task",
            image=self.args.baseline_image,
            command=[
                "sh",
                "-c",
                'echo "Task started"; i=0; '
                'while [ "$i" -lt "$D" ]; do i=$((i+1)); '
                'echo "Task executing ($i/$D)"; sleep 1; done; '
                'echo "Task ended"',
            ],
            env=[client.V1EnvVar(name="D", value=str(duration))],
        )
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"eval-baseline": t.name}),
            spec=client.V1PodSpec(restart_policy="Never", containers=[container]),
        )
        return client.V1Job(
            metadata=client.V1ObjectMeta(name=t.name, namespace=self.namespace),
            spec=client.V1JobSpec(
                template=template,
                backoff_limit=0,
                ttl_seconds_after_finished=3600,
            ),
        )

    # -- recorder pump --------------------------------------------------------

    def _recorder_loop(self) -> None:
        while not (self.stop.is_set() and self.events_q.empty()):
            try:
                ev = self.events_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.events_writer.append(ev)
                self.recorder.handle(ev)
            except Exception as e:
                log("recorder", f"error handling {ev.kind}/{ev.type}: {e}")

    # -- progress / termination ----------------------------------------------

    def _progress_loop(self) -> None:
        last_flush = time.perf_counter()
        n = len(self.tasks)
        while not self.stop.is_set():
            submitted = self._count(lambda r: is_num(r.t_submit_start))
            scheduled = self._count(lambda r: is_num(r.t_pod_scheduled))
            completed = self._count(lambda r: is_num(r.t_pod_succeeded))
            waiting = self._count(
                lambda r: r.n_failed_attempts > 0 and not is_num(r.t_pod_scheduled)
            )
            wall = self._count(
                lambda r: r.n_attempts_wall > 0 and not is_num(r.t_pod_scheduled)
            )
            taint = self._count(
                lambda r: r.n_attempts_taint > 0 and not is_num(r.t_pod_scheduled)
            )
            elapsed = self._now()

            print(
                f"\r[run] submitted {submitted}/{n} | scheduled {scheduled} | "
                f"completed {completed} | waiting {waiting} "
                f"(wall {wall}, taint {taint}) | {elapsed:6.1f}s",
                end="",
                flush=True,
            )

            terminal = self._count(
                lambda r: is_num(r.t_pod_succeeded) or is_num(r.t_pod_failed)
            )
            if terminal >= n:
                print()
                log("finish", "all tasks reached a terminal state")
                return
            if not self.no_timeout and elapsed >= self.timeout_seconds:
                print()
                log(
                    "finish",
                    f"timeout reached ({self.timeout_seconds:.0f}s); "
                    f"{n - terminal} tasks unfinished",
                )
                return

            if time.perf_counter() - last_flush >= self.args.flush_seconds:
                self._flush_outputs()
                last_flush = time.perf_counter()

            time.sleep(self.args.progress_seconds)

    def _count(self, pred) -> int:
        return sum(1 for r in self.records.values() if pred(r))

    def _mark_timed_out(self) -> None:
        for rec in self.records.values():
            if not (is_num(rec.t_pod_succeeded) or is_num(rec.t_pod_failed)):
                rec.timed_out = True

    # -- outputs --------------------------------------------------------------

    def _flush_outputs(self) -> None:
        write_tasks_csv(self.results_dir / "tasks.csv", self.records, self.order)
        if self.recorder:
            write_nodes_csv(self.results_dir / "nodes.csv", self.recorder.node_rows)

    def _write_summary(self) -> None:
        params = {
            "tasks": len(self.tasks),
            "rate_seconds": self.rate_seconds,
            "sanitize_interval_seconds": self.sanitize_interval,
            "task_duration_seconds": self.scenario["task_duration_seconds"],
            "conflict_density": self.scenario.get("conflict_density"),
            "timeout_seconds": None if self.no_timeout else self.timeout_seconds,
        }
        write_summary(
            self.results_dir / "summary.json",
            records=self.records,
            order=self.order,
            scenario=self.scenario,
            replica=self.replica,
            mode=self.mode,
            run_started_epoch=self.t0_epoch,
            params=params,
        )

    # -- clock ----------------------------------------------------------------

    def _now(self) -> float:
        return time.perf_counter() - self.t0

    def _sleep_until(self, target: float) -> None:
        while not self.stop.is_set():
            remaining = target - time.perf_counter()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.2))
