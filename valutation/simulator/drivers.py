"""Simulation drivers.

Two drivers, deliberately kept apart because they answer different questions:

``evaluate_space``  (Part A) measures how much the policies restrict the
    solution space *before* any state accumulates. Each task is evaluated
    independently on a clean, idle cluster; there is no sequence, no
    contextual footprint and no occupancy. What it produces is a property of
    the configuration, not of any particular execution order.

``run_batch``       (Part B, added next) plays the batch as an ordered
    sequence and lets the two state variables evolve.

Keeping them separate is what allows a result to be attributed either to the
cluster composition or to the accumulated state, rather than to an
indistinguishable mix of the two.
"""

from __future__ import annotations

import json

from config import SimConfig
from generate import Scenario, _stream, generate
from model import Cause
from policies import filter_nodes, select, translate
from records import RunResult, StepRecord, TaskRecord
from sanitize import tick


def _base_record(sweep: str, task, translation, req, n_nodes: int) -> TaskRecord:
    """Fill the request-shape fields shared by both drivers."""
    return TaskRecord(
        sweep=sweep,
        task=task.name,
        issuer=task.issuer,
        n_datasets=len(req),
        n_static_datasets=sum(1 for d in req if d.is_static),
        beta_star=json.dumps(translation.beta_star, sort_keys=True),
        beta_star_sum=sum(translation.beta_star.values()),
        geo_star_size=-1 if translation.geo_star is None else len(translation.geo_star),
        ctx_star_size=len(translation.ctx),
        total_size=sum(d.size for d in req),
        n_nodes=n_nodes,
    )


def evaluate_space(
    cfg: SimConfig,
    seed: int | None = None,
    sweep: str = "",
    scenario: Scenario | None = None,
) -> RunResult:
    """Characterise the solution space on a clean cluster, task by task.

    Every task in the batch is evaluated against the same pristine cluster:
    no footprint is deposited, no slot is occupied, no node is ever out of N.
    The batch is therefore just a sample of independent requests drawn from
    the workload distribution, and its order carries no meaning here.

    ``geo_star_size`` is -1 when geo*(t) is unconstrained, to keep that case
    distinguishable from an intersection that happens to be empty.
    """
    seed = cfg.seed if seed is None else seed
    scenario = scenario or generate(cfg, seed)
    state = scenario.state
    rng = _stream(seed, "select")

    nodes = list(state.nodes.values())
    result = RunResult()

    for task in scenario.batch:
        req = [state.datasets[name] for name in task.req_datasets]
        issuer = state.issuers[task.issuer]

        translation = translate(
            task_props=task.props,
            task_geo=task.geo,
            datasets=req,
            groups=state.geo_groups,
            max_levels=state.max_levels,
            issuer_auth=issuer.auth,
        )

        record = _base_record(sweep, task, translation, req, len(nodes))

        # Translation-time rejection: no node is inspected, so the funnel
        # stays at zero and the cause carries the whole information.
        if translation.rejected:
            record.cause = translation.cause.value
            result.tasks.append(record)
            continue

        outcome = filter_nodes(
            nodes=nodes,
            beta_star=translation.beta_star,
            geo_star=translation.geo_star,
            static=translation.static,
            issuer_auth=issuer.auth,
            conflicts=state.conflicts,
            check_state=False,
        )

        record.n_after_prop = outcome.funnel[Cause.PROP]
        record.n_after_geo = outcome.funnel[Cause.GEO]
        record.n_after_static = outcome.funnel[Cause.STATIC]
        record.n_after_wall = outcome.funnel[Cause.WALL]
        record.n_admissible = outcome.n_admissible

        if not outcome.admissible:
            record.cause = outcome.exhausting_cause().value
            result.tasks.append(record)
            continue

        chosen, ideal = select(
            candidates=outcome.admissible,
            beta_star=translation.beta_star,
            datasets=req,
            max_levels=state.max_levels,
            w_prop=cfg.scoring.w_prop,
            w_transfer=cfg.scoring.w_transfer,
            rng=rng,
            prop_weights=cfg.scoring.prop_weights,
        )

        record.assigned = True
        record.assigned_node = chosen.node
        record.delta = chosen.delta
        record.phi_prop = chosen.phi_prop
        record.phi_transfer = chosen.phi_transfer
        record.score = chosen.total
        record.remote_size = chosen.remote_size
        record.ideal_exists = ideal

        result.tasks.append(record)

    return result


def run_batch(
    cfg: SimConfig,
    seed: int | None = None,
    sweep: str = "",
    scenario: Scenario | None = None,
) -> RunResult:
    """Play the batch as an ordered sequence and let the state evolve.

    One step corresponds to one submitted task. The step is a counting device,
    not a unit of time: absolute latencies belong to the prototype, and
    conflating the two would mean measuring a model of the system instead of
    the system. Task duration and the sanitization period are therefore both
    expressed in steps.

    Each step, in order: finished tasks release their slots, sanitization is
    advanced, the task is filtered against the current state, and if a node is
    chosen the task occupies a slot and deposits ctx*(t) on it.

    A blocked task is *not* retried. Retrying would introduce a queue, and a
    queue is the prototype's behaviour, measured on the cluster. What this
    driver measures is instantaneous admissibility: whether the state left by
    previous tasks allows this one to run at the moment it is submitted.
    """
    seed = cfg.seed if seed is None else seed
    scenario = scenario or generate(cfg, seed)
    state = scenario.state
    rng = _stream(seed, "select")

    result = RunResult()
    assigned_total = 0
    blocked_total = 0

    for step, task in enumerate(scenario.batch):
        state.step = step
        state.release_finished()
        tick(state, cfg.sanitization)

        req = [state.datasets[name] for name in task.req_datasets]
        issuer = state.issuers[task.issuer]

        translation = translate(
            task_props=task.props,
            task_geo=task.geo,
            datasets=req,
            groups=state.geo_groups,
            max_levels=state.max_levels,
            issuer_auth=issuer.auth,
        )

        nodes = list(state.nodes.values())
        record = _base_record(sweep, task, translation, req, len(nodes))
        record.step = step

        # State at decision time, recorded before this task perturbs it.
        record.mean_footprint = state.mean_footprint()
        record.n_sanitizing = state.sanitizing_count()
        record.occupied_slots = state.occupied_slots()

        if translation.rejected:
            record.cause = translation.cause.value
            blocked_total += 1
            result.tasks.append(record)
            result.steps.append(
                _step_record(sweep, state, assigned_total, blocked_total)
            )
            continue

        outcome = filter_nodes(
            nodes=nodes,
            beta_star=translation.beta_star,
            geo_star=translation.geo_star,
            static=translation.static,
            issuer_auth=issuer.auth,
            conflicts=state.conflicts,
            check_state=True,
        )

        record.n_after_prop = outcome.funnel[Cause.PROP]
        record.n_after_geo = outcome.funnel[Cause.GEO]
        record.n_after_static = outcome.funnel[Cause.STATIC]
        record.n_after_sanitizing = outcome.funnel[Cause.SANITIZING]
        record.n_after_wall = outcome.funnel[Cause.WALL]
        record.n_admissible = outcome.n_admissible

        if not outcome.admissible:
            record.cause = outcome.exhausting_cause().value
            # The configuration alone would have left candidates: what removed
            # them is the accumulated state, not the cluster composition.
            record.blocked_by_state = outcome.n_after_static_policies > 0
            blocked_total += 1
            result.tasks.append(record)
            result.steps.append(
                _step_record(sweep, state, assigned_total, blocked_total)
            )
            continue

        chosen, ideal = select(
            candidates=outcome.admissible,
            beta_star=translation.beta_star,
            datasets=req,
            max_levels=state.max_levels,
            w_prop=cfg.scoring.w_prop,
            w_transfer=cfg.scoring.w_transfer,
            rng=rng,
            prop_weights=cfg.scoring.prop_weights,
        )

        node = state.nodes[chosen.node]
        node.occupy(step + cfg.workload.duration)
        node.deposit(translation.ctx)

        record.assigned = True
        record.assigned_node = chosen.node
        record.delta = chosen.delta
        record.phi_prop = chosen.phi_prop
        record.phi_transfer = chosen.phi_transfer
        record.score = chosen.total
        record.remote_size = chosen.remote_size
        record.ideal_exists = ideal
        assigned_total += 1

        result.tasks.append(record)
        result.steps.append(_step_record(sweep, state, assigned_total, blocked_total))

    return result


def _step_record(sweep: str, state, assigned: int, blocked: int) -> StepRecord:
    """Snapshot the cluster at the end of a step."""
    footprints = [len(n.lambda_ctx) for n in state.nodes.values()]
    return StepRecord(
        sweep=sweep,
        step=state.step,
        mean_footprint=sum(footprints) / len(footprints) if footprints else 0.0,
        max_footprint=max(footprints) if footprints else 0,
        n_sanitizing=state.sanitizing_count(),
        n_available=len(state.nodes) - state.sanitizing_count(),
        occupied_slots=state.occupied_slots(),
        cumulative_assigned=assigned,
        cumulative_blocked=blocked,
    )
