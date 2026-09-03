"""Sanitization strategies.

The model describes sanitization as the mechanism that bounds the growth of
the contextual footprint, and names two ways of triggering it beyond the
periodic one the prototype implements: a threshold on the footprint size.
That alternative is evaluated here, which is the point of having a reference
implementation at all.

Sanitization is a two-phase procedure, mirroring the node-controller: a node
is first taken out of N, then waits for the tasks running on it to finish, and
only afterwards has its footprint cleared and re-enters N. The wait is what
couples sanitization to node occupancy: a busy node stays unavailable longer,
so the cost of the mechanism depends on how loaded the cluster is.
"""

from __future__ import annotations

from config import SanitizationConfig, SanitizationStrategy
from model import ClusterState, Node


def _dirty(node: Node) -> bool:
    return bool(node.lambda_ctx) and not node.sanitizing


def select_for_sanitization(state: ClusterState, cfg: SanitizationConfig) -> list[Node]:
    """Nodes that should enter sanitization at the current step.

    NONE:      never. Yields the asymptotic starvation rate, the upper
               bound against which every other strategy is read.
    PERIODIC:  every ``period`` steps, every node carrying a footprint.
               Simple and implemented, but indiscriminate: it takes nodes
               out of N regardless of how contaminated or how busy they
               are.
    THRESHOLD: only nodes whose footprint has reached ``threshold``
               contexts. Spends availability only where the footprint is
               actually large.
    """
    if cfg.strategy is SanitizationStrategy.NONE:
        return []

    if cfg.strategy is SanitizationStrategy.PERIODIC:
        if cfg.period <= 0 or state.step % cfg.period != 0:
            return []
        return [n for n in state.nodes.values() if _dirty(n)]

    if cfg.strategy is SanitizationStrategy.THRESHOLD:
        return [
            n
            for n in state.nodes.values()
            if _dirty(n) and len(n.lambda_ctx) >= cfg.threshold
        ]

    raise ValueError(f"unknown sanitization strategy: {cfg.strategy}")


def complete_ready(state: ClusterState) -> int:
    """Finish sanitization on every node whose tasks have all finished.

    Returns how many nodes re-entered N. This is the simulator's counterpart
    of the controller clearing the footprint and removing the taint once no
    task is left running on the node.
    """
    done = 0
    for node in state.nodes.values():
        if node.sanitizing and node.is_idle:
            node.clear_traces()
            node.sanitizing = False
            node.sanitize_since = None
            done += 1
    return done


def tick(state: ClusterState, cfg: SanitizationConfig) -> tuple[int, int]:
    """Advance sanitization by one step.

    Nodes already sanitizing are completed first, then new ones are selected,
    then completion is attempted again so that an idle node selected in this
    same step is cleared without spending a step out of N. That immediacy is
    faithful: the controller's wait returns at once when nothing is running.

    Returns the number of nodes started and the number completed.
    """
    completed = complete_ready(state)

    started = 0
    for node in select_for_sanitization(state, cfg):
        node.sanitizing = True
        node.sanitize_since = state.step
        started += 1

    completed += complete_ready(state)
    return started, completed
