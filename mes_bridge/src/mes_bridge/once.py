"""One-shot scheduling (task 1.6): fetch the problem, plan with the SPT rule, check, publish.

    MES_SCHEDULER_PASSWORD=... uv run python -m mes_bridge.once [--url http://localhost:8080] [--dry-run]

Credentials from the environment (`MES_SCHEDULER_USERNAME`, default `scheduler`; `MES_SCHEDULER_PASSWORD`), never
from a file (decision 16). A plan with violations is printed and not published (decision 23).
"""

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from simulation.check.feasibility import Violation, check_schedule
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.schedule import Assignment, Plan

from mes_bridge.api import ProblemOut, ScheduleBreakIn, ScheduleIn, ScheduleStepIn
from mes_bridge.assumed import Aliases, assume_plates, publish_keys
from mes_bridge.client import MesClient, http
from mes_bridge.config import SchedulerConfig
from mes_bridge.instance import build_instance, epoch_of
from mes_bridge.state import out_of_service, IdMap, build_snapshot, id_map, pin

# decision 4: BOUND (the default view) plans with the assignments as pins, FREE without them (suggestions)
BOUND, FREE = "BOUND", "FREE"


@dataclass(frozen=True)
class Outcome:
    schedule: ScheduleIn | None  # None: not publishable
    violations: list[Violation]


def solve(
    problem: ProblemOut,
    *,
    epoch: datetime,
    solved_at: datetime,
    config: SchedulerConfig | None = None,
    variant: str = BOUND,
) -> Outcome:
    """The configured planner's plan for the problem as the variant's schedule, or the checker's violations."""
    if not problem.instance.operations:  # nothing has arrived: an empty schedule says so
        return Outcome(_schedule(problem, solved_at, [], variant=variant), [])
    problem, aliases = assume_plates(problem)  # orders not nested yet (planned nesting flow)
    ci = compile_instance(build_instance(problem, epoch=epoch))
    ids = id_map(problem, ci)
    snap = build_snapshot(problem, ci, ids, epoch=epoch)
    started = {(f.order_id, f.op_id) for f in snap.frozen}
    ci = out_of_service(ci, problem, started)  # no new work on a machine that is down
    if variant == BOUND:  # the assignments as pins (state.pin)
        ci = pin(ci, problem, ids, started).ci
    plan = (config or SchedulerConfig()).solver.planner()(ci, snap, [])
    if violations := check_schedule(ci, plan.assignments, snapshot=snap, breaks=plan.breaks):
        return Outcome(None, violations)
    return Outcome(
        _schedule(
            problem,
            solved_at,
            steps(problem, ci, ids, plan, epoch, aliases=aliases),
            schedule_breaks(problem, plan, epoch),
            variant=variant,
        ),
        [],
    )


def _schedule(
    problem: ProblemOut,
    solved_at: datetime,
    steps_: list[ScheduleStepIn],
    breaks_: list[ScheduleBreakIn] = (),
    *,
    variant: str = BOUND,
) -> ScheduleIn:
    return ScheduleIn(
        variant=variant, snapshot_as_of=problem.as_of, solved_at=solved_at, steps=steps_, breaks=list(breaks_)
    )


def schedule_breaks(problem: ProblemOut, plan: Plan, epoch: datetime) -> list[ScheduleBreakIn]:
    """The plan's breaks (decision 21): one per worker and day, `break_minutes` long."""
    length = timedelta(minutes=problem.instance.calendar.break_minutes)
    return [
        ScheduleBreakIn(worker_id=b.worker, start=_dt(epoch, b.start), end=_dt(epoch, b.start) + length)
        for b in sorted(plan.breaks, key=lambda b: (b.start, b.worker))
    ]


def steps(
    problem: ProblemOut,
    ci: CompiledInstance,
    ids: IdMap,
    plan: Plan,
    epoch: datetime,
    *,
    aliases: Aliases | None = None,
) -> list[ScheduleStepIn]:
    """One schedule step per MES step that is not finished: from its first operation's start to its last one's end;
    attended until the handoff (setup + run) or the end of the worker's share. A step on an assumed plate or print
    (`assumed`) is published under each MES key it stands for (the order's own step), with the same times."""
    by_op = {(a.order_id, a.op_id): a for a in plan.assignments}
    done = {o.key for o in problem.instance.operations if o.done}
    out = []
    for key, ops in ids.ops.items():
        if not ops or key in done:
            continue
        asg = [by_op[k] for k in ops]
        first, last = asg[0], asg[-1]
        attended = first.end if len(asg) > 1 else _attended_end(ci, first)
        for mes_key in publish_keys(key, aliases or {}):
            out.append(
                ScheduleStepIn(
                    key=mes_key,
                    worker_id=next((w for a in asg for w in a.workers if w), None),
                    equipment_id=next((a.machine for a in asg if a.machine), None),
                    start=_dt(epoch, first.start),
                    attended_end=_dt(epoch, attended),
                    end=_dt(epoch, last.end),
                )
            )
    return out


def _attended_end(ci: CompiledInstance, a: Assignment) -> int:
    shares = ci.shares[ci.op_index[a.order_id, a.op_id]]
    if not shares:
        return a.start  # unattended throughout
    sh = shares[0]
    if sh.kind == "whole":
        return a.end
    length = a.share_lengths[0] if a.share_lengths else sh.length
    return a.start + length if sh.kind == "prefix" else a.end  # a suffix: attended until the end


def _dt(epoch: datetime, minute: int) -> datetime:
    return (epoch + timedelta(minutes=minute)).astimezone(UTC)


def run(
    client: MesClient,
    *,
    now: datetime,
    dry_run: bool = False,
    config: SchedulerConfig | None = None,
    variant: str = BOUND,
) -> Outcome:
    problem = client.problem()
    epoch = epoch_of(now, ZoneInfo(problem.instance.calendar.time_zone))  # decision 17: the start week
    outcome = solve(problem, epoch=epoch, solved_at=now, config=config, variant=variant)
    if outcome.schedule is not None and not dry_run:
        client.publish(outcome.schedule)
    return outcome


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=os.environ.get("MES_URL", "http://localhost:8080"))
    ap.add_argument("--dry-run", action="store_true", help="plan and check, do not publish")
    ap.add_argument("--config", help="SchedulerConfig JSON file (default: the defaults)")
    args = ap.parse_args(argv)
    password = os.environ.get("MES_SCHEDULER_PASSWORD")
    if not password:
        print("MES_SCHEDULER_PASSWORD is not set", file=sys.stderr)
        return 2
    client = MesClient(http(args.url))
    client.login(os.environ.get("MES_SCHEDULER_USERNAME", "scheduler"), password)
    config, failed = SchedulerConfig.load(args.config), False
    for variant in config.variants:
        outcome = run(client, now=datetime.now(UTC), dry_run=args.dry_run, config=config, variant=variant)
        if outcome.schedule is None:
            print(f"{variant} not published: {len(outcome.violations)} violations", file=sys.stderr)
            for v in outcome.violations:
                print(f"  {v.constraint}: {v.message}", file=sys.stderr)
            failed = True
            continue
        print(f"{variant} {'planned' if args.dry_run else 'published'}: {len(outcome.schedule.steps)} steps")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
