"""
watchers.py: one watch stream per resource, funnelling events into a queue.

Each watcher is a thin loop around kubernetes.watch.Watch that stamps every
event with the run clock the moment it arrives and pushes a WatchEvent. The
reconnection policy lives in Watchers.run_forever: watches expire (their
server-side timeout, or a 410 Gone when the resourceVersion is too old), and we
simply reopen, emitting a RESYNC marker on 410 so the recorder/events.csv can
note a possible gap.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from kubernetes import watch
from kubernetes.client.rest import ApiException

from .record import WatchEvent

# Server-side watch timeout; the loop reopens transparently on expiry.
WATCH_TIMEOUT_SECONDS = 60


class Watchers:
    """Owns the watcher threads for one run."""

    def __init__(
        self,
        *,
        k8s_core,
        k8s_batch,
        k8s_custom,
        conv,
        namespace: str,
        mode: str,
        events_q: "queue.Queue[WatchEvent]",
        stop: threading.Event,
        now: Callable[[], float],
    ):
        self.core = k8s_core
        self.batch = k8s_batch
        self.custom = k8s_custom
        self.conv = conv
        self.namespace = namespace
        self.mode = mode
        self.events_q = events_q
        self.stop = stop
        self.now = now

    def start(self) -> list[threading.Thread]:
        specs: list[tuple[str, Callable[[], None]]] = [
            ("Pod", self._watch_pods),
            ("Job", self._watch_jobs),
            ("Event", self._watch_events),
            ("Node", self._watch_nodes),
        ]
        if self.mode != "baseline":
            specs.append(("TaskRequest", self._watch_task_requests))

        threads = []
        for kind, fn in specs:
            th = threading.Thread(
                target=self._run_forever,
                args=(kind, fn),
                name=f"watch-{kind}",
                daemon=True,
            )
            th.start()
            threads.append(th)
        return threads

    def _run_forever(self, kind: str, fn: Callable[[], None]) -> None:
        while not self.stop.is_set():
            try:
                fn()
            except ApiException as e:
                if e.status == 410:  # Gone: resourceVersion too old, resync.
                    self.events_q.put(WatchEvent(self.now(), kind, "RESYNC", None))
                    continue
                if self.stop.is_set():
                    return
                time.sleep(1)
            except Exception:
                if self.stop.is_set():
                    return
                time.sleep(1)

    def _emit(self, kind: str, ev: dict) -> None:
        self.events_q.put(WatchEvent(self.now(), kind, ev["type"], ev["object"]))

    def _watch_pods(self) -> None:
        w = watch.Watch()
        for ev in w.stream(
            self.core.list_namespaced_pod,
            namespace=self.namespace,
            timeout_seconds=WATCH_TIMEOUT_SECONDS,
        ):
            if self.stop.is_set():
                w.stop()
                return
            self._emit("Pod", ev)

    def _watch_jobs(self) -> None:
        w = watch.Watch()
        for ev in w.stream(
            self.batch.list_namespaced_job,
            namespace=self.namespace,
            timeout_seconds=WATCH_TIMEOUT_SECONDS,
        ):
            if self.stop.is_set():
                w.stop()
                return
            self._emit("Job", ev)

    def _watch_events(self) -> None:
        w = watch.Watch()
        for ev in w.stream(
            self.core.list_namespaced_event,
            namespace=self.namespace,
            timeout_seconds=WATCH_TIMEOUT_SECONDS,
        ):
            if self.stop.is_set():
                w.stop()
                return
            self._emit("Event", ev)

    def _watch_nodes(self) -> None:
        w = watch.Watch()
        for ev in w.stream(
            self.core.list_node,
            timeout_seconds=WATCH_TIMEOUT_SECONDS,
        ):
            if self.stop.is_set():
                w.stop()
                return
            self._emit("Node", ev)

    def _watch_task_requests(self) -> None:
        w = watch.Watch()
        for ev in w.stream(
            self.custom.list_namespaced_custom_object,
            group=self.conv.group,
            version=self.conv.version,
            namespace=self.namespace,
            plural=self.conv.tr_plural,
            timeout_seconds=WATCH_TIMEOUT_SECONDS,
        ):
            if self.stop.is_set():
                w.stop()
                return
            self._emit("TaskRequest", ev)
