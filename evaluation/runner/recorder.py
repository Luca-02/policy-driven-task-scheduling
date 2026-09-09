"""
recorder.py: turn raw watch events into per-task records and a node timeline.

The Recorder owns the correlation logic (TaskRequest -> Job -> Pod -> Events)
and the node modification log. It is deliberately free of threading and I/O: the
core drives it by calling handle() for each event and, at the end, reads records
and node_rows. This keeps the tricky correlation testable in isolation.
"""

from __future__ import annotations

import json
from typing import Any

from .record import Record, WatchEvent
from .util import get, is_num, count_nodes, rnd

# Standard label the job-controller puts on a Job's pods.
POD_JOB_LABEL = "job-name"


def _event_occurrences(obj) -> int:
    """Number of times this Event object represents an occurrence.

    Since Kubernetes 1.19, repeated identical events are aggregated into an
    EventSeries: the legacy top-level `count` field stays unset (None) and the
    running total lives in `series.count` instead. Older clusters (or events
    with no series) still use `count`. A first isolated event with neither has
    occurred exactly once.
    """
    series_count = get(obj, "series", "count")
    if series_count is not None:
        return int(series_count)
    count = get(obj, "count")
    if count is not None:
        return int(count)
    return 1


class Recorder:
    def __init__(self, records: dict[int, Record], conv):
        self.records = records
        self.conv = conv

        # Correlation indexes, filled as objects appear.
        self.by_tr_name: dict[str, Record] = {}
        self.by_job_name: dict[str, Record] = {}
        self.by_pod_name: dict[str, Record] = {}

        for rec in records.values():
            self.by_tr_name[rec.name] = rec

        self.node_rows: list[dict[str, Any]] = []

    # -- dispatch -------------------------------------------------------------

    def handle(self, ev: WatchEvent) -> None:
        if ev.type == "RESYNC" or ev.obj is None:
            return
        if ev.kind == "TaskRequest":
            self._on_task_request(ev)
        elif ev.kind == "Job":
            self._on_job(ev)
        elif ev.kind == "Pod":
            self._on_pod(ev)
        elif ev.kind == "Event":
            self._on_k8s_event(ev)
        elif ev.kind == "Node":
            self._on_node(ev)

    # -- handlers -------------------------------------------------------------

    def _on_task_request(self, ev: WatchEvent) -> None:
        obj = ev.obj
        name = get(obj, "metadata", "name")
        rec = self.by_tr_name.get(name)
        if rec is None:
            return
        phase = get(obj, "status", "phase") or ""
        job_name = get(obj, "status", "jobName") or ""
        if job_name and not rec.job_name:
            rec.job_name = job_name
            self.by_job_name[job_name] = rec
        if phase == "Pending" and not is_num(rec.t_tr_pending):
            rec.t_tr_pending = ev.t_recv
        elif phase == "Scheduled" and not is_num(rec.t_tr_scheduled):
            rec.t_tr_scheduled = ev.t_recv
        elif phase == "Complete" and not is_num(rec.t_tr_complete):
            rec.t_tr_complete = ev.t_recv
        elif phase == "Failed" and not is_num(rec.t_tr_failed):
            rec.t_tr_failed = ev.t_recv
        if phase:
            rec.tr_final_phase = phase

    def _on_job(self, ev: WatchEvent) -> None:
        obj = ev.obj
        name = get(obj, "metadata", "name")
        # The controller names the Job after the TaskRequest, so a name match
        # links them; status.jobName may also have registered it already.
        rec = self.by_job_name.get(name) or self.by_tr_name.get(name)
        if rec is None:
            return
        if not rec.job_name:
            rec.job_name = name
            self.by_job_name[name] = rec
        if not is_num(rec.t_job_seen):
            rec.t_job_seen = ev.t_recv

    def _on_pod(self, ev: WatchEvent) -> None:
        obj = ev.obj
        labels = get(obj, "metadata", "labels") or {}
        job = labels.get(POD_JOB_LABEL) or labels.get("eval-baseline")
        if not job:
            return
        rec = self.by_job_name.get(job) or self.by_tr_name.get(job)
        if rec is None:
            return
        pod_name = get(obj, "metadata", "name")
        if not rec.pod_name:
            rec.pod_name = pod_name
            self.by_pod_name[pod_name] = rec
        if not is_num(rec.t_pod_seen):
            rec.t_pod_seen = ev.t_recv
        node = get(obj, "spec", "nodeName")
        if node and not is_num(rec.t_pod_scheduled):
            rec.t_pod_scheduled = ev.t_recv
            rec.node = node
        phase = get(obj, "status", "phase") or ""
        if phase == "Running" and not is_num(rec.t_pod_running):
            rec.t_pod_running = ev.t_recv
        elif phase == "Succeeded" and not is_num(rec.t_pod_succeeded):
            rec.t_pod_succeeded = ev.t_recv
            rec.final_phase = phase
        elif phase == "Failed" and not is_num(rec.t_pod_failed):
            rec.t_pod_failed = ev.t_recv
            rec.final_phase = phase

    def _on_k8s_event(self, ev: WatchEvent) -> None:
        obj = ev.obj
        if (get(obj, "reason") or "") != "FailedScheduling":
            return
        involved = get(obj, "involvedObject", "name") or ""
        rec = self.by_pod_name.get(involved) or self._match_pod_prefix(involved)
        if rec is None:
            return

        uid = get(obj, "metadata", "uid") or involved
        occurrences = _event_occurrences(obj)
        prev = rec._event_counts.get(uid, 0)
        delta = occurrences - prev
        if delta <= 0:
            return
        rec._event_counts[uid] = occurrences

        msg = get(obj, "message") or ""
        is_wall = "c_wall violated" in msg
        # Kubernetes' TaintToleration plugin returns a fixed, generic message
        # ("node(s) had untolerated taint") with no taint key/value, so the
        # specific taint cannot be identified from the message. In this
        # evaluation's controlled cluster the only taint ever applied to a
        # worker is the sanitizing taint, so any untolerated-taint rejection
        # here is unambiguously attributable to it.
        is_taint = "untolerated taint" in msg

        rec.n_failed_attempts += delta
        if is_wall:
            rec.n_attempts_wall += delta
        if is_taint:
            rec.n_attempts_taint += delta
        if not is_wall and not is_taint:
            rec.n_attempts_other += delta

        if not is_num(rec.t_first_rejection):
            rec.t_first_rejection = ev.t_recv
            rec.first_rejection_msg = msg[:300]
            rec.nodes_wall_first = count_nodes(msg, "c_wall violated")
            rec.nodes_taint_first = count_nodes(msg, "untolerated taint")

    def _match_pod_prefix(self, pod_name: str) -> Record | None:
        """FailedScheduling's involvedObject is the Pod, whose name starts with
        the Job name; fall back to a prefix match when the Pod is not yet
        linked by label."""
        for job_name, rec in self.by_job_name.items():
            if pod_name.startswith(job_name):
                self.by_pod_name[pod_name] = rec
                if not rec.pod_name:
                    rec.pod_name = pod_name
                return rec
        return None

    def _on_node(self, ev: WatchEvent) -> None:
        obj = ev.obj
        name = get(obj, "metadata", "name")
        annotations = get(obj, "metadata", "annotations") or {}
        raw = annotations.get(self.conv.contexts_annotation_key)
        lambda_list: list[str] = []
        if raw:
            try:
                lambda_list = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                lambda_list = [raw]
        taints = get(obj, "spec", "taints") or []
        sanitizing = any((get(t, "key") or "").endswith("/sanitizing") for t in taints)
        self.node_rows.append(
            {
                "t_recv": rnd(ev.t_recv),
                "node": name,
                "sanitizing": sanitizing,
                "lambda_size": len(lambda_list),
                "lambda": json.dumps(sorted(lambda_list)),
            }
        )
