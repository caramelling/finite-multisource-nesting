from __future__ import annotations

from collections import defaultdict
from time import perf_counter

import highspy

from .algorithms import Bar, Demand, EPSILON, NestingResult


def solve_milp(
    demands: list[Demand],
    standard_lengths_mm: list[float],
    boundary_allowance_mm: float,
    *,
    time_limit_seconds: float = 300.0,
    threads: int = 1,
) -> NestingResult:
    if not demands:
        return NestingResult("MILP", boundary_allowance_mm, [], [], 0, 0, "OPTIMAL", 0.0, 0.0)
    lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
    if not lengths:
        raise ValueError("MILP requires positive standard stock lengths.")
    if boundary_allowance_mm < 0:
        raise ValueError("Boundary allowance must be non-negative.")

    started = perf_counter()
    groups: dict[tuple[str, str, str, str, str], list[Demand]] = defaultdict(list)
    for demand in demands:
        groups[demand.group_key].append(demand)

    bars: list[Bar] = []
    statuses: list[str] = []
    gaps: list[float] = []
    objectives: list[float] = []
    next_bar = 1
    for key in sorted(groups):
        elapsed = perf_counter() - started
        remaining_time = max(0.01, time_limit_seconds - elapsed)
        if remaining_time <= 0.01 and bars:
            raise TimeoutError("MILP block time budget was exhausted before all groups solved.")
        group_bars, status, gap, objective = _solve_group(
            sorted(groups[key], key=lambda item: (-item.net_length_mm, item.demand_id)),
            lengths,
            boundary_allowance_mm,
            remaining_time,
            threads,
        )
        for bar in group_bars:
            bar.bar_id = "BAR-%06d" % next_bar
            next_bar += 1
            bars.append(bar)
        statuses.append(status)
        gaps.append(gap)
        objectives.append(objective)

    elapsed_ms = int(round((perf_counter() - started) * 1000.0))
    overall_status = "OPTIMAL" if all(status == "OPTIMAL" for status in statuses) else "FEASIBLE"
    return NestingResult(
        algorithm="MILP",
        boundary_allowance_mm=boundary_allowance_mm,
        bars=bars,
        unassigned=[],
        input_count=len(demands),
        elapsed_ms=elapsed_ms,
        solver_status=overall_status,
        mip_gap=max(gaps, default=0.0),
        solver_objective=sum(objectives),
    )


def _solve_group(
    demands: list[Demand],
    lengths: list[float],
    allowance: float,
    time_limit: float,
    threads: int,
) -> tuple[list[Bar], str, float, float]:
    maximum = max(lengths)
    for demand in demands:
        if demand.net_length_mm + 2.0 * allowance > maximum + EPSILON:
            raise ValueError("Demand %s does not fit the longest stock." % demand.demand_id)

    count = len(demands)
    bar_limit = _best_fit_bar_upper_bound(demands, maximum, allowance)
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    model.setOptionValue("threads", max(1, int(threads)))
    model.setOptionValue("time_limit", float(time_limit))
    model.setOptionValue("mip_rel_gap", 0.0)

    assignment: dict[tuple[int, int], object] = {}
    stock_choice: dict[tuple[int, int], object] = {}
    multiplier = count + 1
    for bar in range(bar_limit):
        for length_index, length in enumerate(lengths):
            stock_choice[(bar, length_index)] = model.addVariable(
                lb=0,
                ub=1,
                obj=length * multiplier + 1.0,
                type=highspy.HighsVarType.kInteger,
                name="y_%d_%d" % (bar, length_index),
            )
        for item in range(count):
            if bar > item:
                continue
            assignment[(item, bar)] = model.addVariable(
                lb=0,
                ub=1,
                type=highspy.HighsVarType.kInteger,
                name="x_%d_%d" % (item, bar),
            )

    for item in range(count):
        model.addConstr(
            sum(
                assignment[(item, bar)]
                for bar in range(min(bar_limit, item + 1))
            )
            == 1
        )

    active = []
    for bar in range(bar_limit):
        active_bar = sum(
            stock_choice[(bar, length_index)] for length_index in range(len(lengths))
        )
        active.append(active_bar)
        model.addConstr(active_bar <= 1)
        for item in range(bar, count):
            model.addConstr(assignment[(item, bar)] <= active_bar)
        used = sum(
            (demand.net_length_mm + allowance) * assignment[(item, bar)]
            for item, demand in enumerate(demands)
            if (item, bar) in assignment
        ) + allowance * active_bar
        capacity = sum(
            lengths[length_index] * stock_choice[(bar, length_index)]
            for length_index in range(len(lengths))
        )
        model.addConstr(used <= capacity)
    for bar in range(bar_limit - 1):
        model.addConstr(active[bar] >= active[bar + 1])

    model.setMinimize()
    model.run()
    model_status = model.getModelStatus()
    solution = model.getSolution()
    if not solution.value_valid:
        raise RuntimeError(
            "HiGHS did not return a feasible MILP solution: %s"
            % model.modelStatusToString(model_status)
        )
    status = (
        "OPTIMAL"
        if model_status == highspy.HighsModelStatus.kOptimal
        else model.modelStatusToString(model_status).upper().replace(" ", "_")
    )
    info = model.getInfo()
    result: list[Bar] = []
    for bar in range(bar_limit):
        selected_length = None
        for length_index, length in enumerate(lengths):
            if model.val(stock_choice[(bar, length_index)]) > 0.5:
                selected_length = length
                break
        if selected_length is None:
            continue
        selected_demands = [
            demand
            for item, demand in enumerate(demands)
            if (item, bar) in assignment
            and model.val(assignment[(item, bar)]) > 0.5
        ]
        if not selected_demands:
            continue
        first = selected_demands[0]
        result.append(
            Bar(
                bar_id="",
                material=first.material,
                profile_type=first.profile_type,
                specification=first.specification,
                stock_length_mm=selected_length,
                stock_source_type="STANDARD",
                demands=selected_demands,
            )
        )
    return result, status, float(info.mip_gap), float(model.getObjectiveValue())


def _best_fit_bar_upper_bound(
    demands: list[Demand], capacity: float, allowance: float
) -> int:
    """Return a feasible BFD bar count using the longest standard stock."""

    used_lengths: list[float] = []
    for demand in demands:
        candidates = [
            (capacity - (used + demand.net_length_mm + allowance), index)
            for index, used in enumerate(used_lengths)
            if used + demand.net_length_mm + allowance <= capacity + EPSILON
        ]
        if candidates:
            _, index = min(candidates)
            used_lengths[index] += demand.net_length_mm + allowance
        else:
            used_lengths.append(demand.net_length_mm + 2.0 * allowance)
    return len(used_lengths)
