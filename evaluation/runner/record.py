"""
record.py: the per-task record and the watch-event envelope.

A Record accumulates raw timestamps as events arrive; finalize() turns them into
the flat dict of columns written to tasks.csv (derived durations, block cause,
outcome). Every timestamp is seconds since run start, NaN when unseen, so a
missing observation is never silently read as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .utils import NAN, is_num, rnd


@dataclass
class Record:
    task_id: int
    name: str
    issuer: str
    context: str
    context_degree: int
    datasets: str
    replica: int

    # Submission / admission.
    t_submit_planned: float = NAN
    t_submit_start: float = NAN
    t_submit_end: float = NAN
    admission_status: int = 0
    admitted: bool = False

    # Translation (TaskRequest phases + Job).
    t_tr_pending: float = NAN
    t_tr_scheduled: float = NAN
    t_tr_complete: float = NAN
    t_tr_failed: float = NAN
    tr_final_phase: str = ""
    job_name: str = ""
    t_job_seen: float = NAN

    # Pod creation / scheduling.
    pod_name: str = ""
    t_pod_seen: float = NAN
    t_pod_scheduled: float = NAN
    node: str = ""

    # Rejections (FailedScheduling events).
    n_failed_attempts: int = 0
    n_attempts_wall: int = 0
    n_attempts_taint: int = 0
    n_attempts_other: int = 0
    nodes_wall_first: int = 0
    nodes_taint_first: int = 0
    t_first_rejection: float = NAN
    first_rejection_msg: str = ""

    # Execution / outcome.
    t_pod_running: float = NAN
    t_pod_succeeded: float = NAN
    t_pod_failed: float = NAN
    final_phase: str = ""
    timed_out: bool = False

    # Internal: last-seen FailedScheduling count per event object, so repeated
    # observations of the same Event accumulate deltas rather than re-counting.
    _event_counts: dict[str, int] = field(default_factory=dict, repr=False)

    def finalize(self) -> dict[str, Any]:
        def diff(a: float, b: float) -> float:
            return a - b if is_num(a) and is_num(b) else NAN

        blocked = self.n_failed_attempts > 0
        cause = "none"
        if blocked:
            has_wall = self.n_attempts_wall > 0
            has_taint = self.n_attempts_taint > 0
            if has_wall and has_taint:
                cause = "mixed"
            elif has_wall:
                cause = "wall"
            elif has_taint:
                cause = "taint"
            else:
                cause = "other"

        return {
            "task_id": self.task_id,
            "name": self.name,
            "issuer": self.issuer,
            "context": self.context,
            "context_degree": self.context_degree,
            "datasets": self.datasets,
            "replica": self.replica,
            # submission / admission
            "t_submit_planned": rnd(self.t_submit_planned),
            "t_submit_start": rnd(self.t_submit_start),
            "t_submit_end": rnd(self.t_submit_end),
            "submit_jitter_s": rnd(diff(self.t_submit_start, self.t_submit_planned)),
            "admission_s": rnd(diff(self.t_submit_end, self.t_submit_start)),
            "admission_status": self.admission_status,
            "admitted": self.admitted,
            # translation
            "t_tr_pending": rnd(self.t_tr_pending),
            "t_tr_scheduled": rnd(self.t_tr_scheduled),
            "t_tr_complete": rnd(self.t_tr_complete),
            "t_tr_failed": rnd(self.t_tr_failed),
            "job_name": self.job_name,
            "t_job_seen": rnd(self.t_job_seen),
            "translation_s": rnd(diff(self.t_job_seen, self.t_submit_end)),
            # pod creation
            "pod_name": self.pod_name,
            "t_pod_seen": rnd(self.t_pod_seen),
            "pod_creation_s": rnd(diff(self.t_pod_seen, self.t_job_seen)),
            # scheduling
            "t_pod_scheduled": rnd(self.t_pod_scheduled),
            "scheduling_s": rnd(diff(self.t_pod_scheduled, self.t_pod_seen)),
            "node": self.node,
            "latency_s": rnd(diff(self.t_pod_scheduled, self.t_submit_start)),
            # rejections
            "n_failed_attempts": self.n_failed_attempts,
            "n_attempts_wall": self.n_attempts_wall,
            "n_attempts_taint": self.n_attempts_taint,
            "n_attempts_other": self.n_attempts_other,
            "nodes_wall_first": self.nodes_wall_first,
            "nodes_taint_first": self.nodes_taint_first,
            "block_cause": cause,
            "blocked": blocked,
            "t_first_rejection": rnd(self.t_first_rejection),
            "wait_s": (
                rnd(diff(self.t_pod_scheduled, self.t_first_rejection))
                if blocked
                else NAN
            ),
            "first_rejection_msg": self.first_rejection_msg,
            # execution / outcome
            "t_pod_running": rnd(self.t_pod_running),
            "t_pod_succeeded": rnd(self.t_pod_succeeded),
            "t_pod_failed": rnd(self.t_pod_failed),
            "startup_s": rnd(diff(self.t_pod_running, self.t_pod_scheduled)),
            "execution_s": rnd(diff(self.t_pod_succeeded, self.t_pod_running)),
            "completion_s": rnd(diff(self.t_pod_succeeded, self.t_submit_start)),
            "final_phase": self.final_phase,
            "tr_final_phase": self.tr_final_phase,
            "timed_out": self.timed_out,
        }


# Column order for tasks.csv, derived from an empty record so header and rows
# can never disagree.
TASKS_CSV_FIELDS = list(Record(0, "", "", "", 0, "", 0).finalize().keys())


@dataclass
class WatchEvent:
    """One event from a watcher, stamped on arrival with the run clock."""

    t_recv: float
    kind: str  # "TaskRequest" | "Job" | "Pod" | "Event" | "Node"
    type: str  # "ADDED" | "MODIFIED" | "DELETED" | "RESYNC"
    obj: Any
