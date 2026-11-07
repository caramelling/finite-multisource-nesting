from __future__ import annotations

from collections import defaultdict
from time import perf_counter

import highspy

from .algorithms import Bar, Demand, EPSILON, NestingResult, StockUnit


def solve_resource_purchase_milp(
    demands: list[Demand],
    stock_units: list[StockUnit],
    standard_lengths_mm: list[float],
    boundary_allowance_mm: float,
    *,
    time_limit_seconds: float = 300.0,
    threads: int = 1,
) -> NestingResult:
    """Exact small-instance model for finite initial stock plus new purchases."""

    if not demands:
        return NestingResult(
            "RESOURCE_PURCHASE_MILP", boundary_allowance_mm, [], [], 0, 0, "OPTIMAL", 0.0, 0.0
        )
    lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
    if not lengths:
        raise ValueError("RESOURCE_PURCHASE_MILP requires positive purchase lengths.")
    if boundary_allowance_mm < 0:
        raise ValueError("Boundary allowance must be non-negative.")

    started = perf_counter()
    demands_by_compatibility: dict[tuple[str, str, str], list[Demand]] = defaultdict(list)
    for demand in demands:
        if demand.net_length_mm <= 0:
            raise ValueError("Demand %s has non-positive length." % demand.demand_id)
        if demand.net_length_mm + 2.0 * boundary_allowance_mm > max(lengths) + EPSILON:
            raise ValueError("Demand %s does not fit purchasable stock." % demand.demand_id)
        demands_by_compatibility[demand.compatibility_key].append(demand)
    stocks_by_compatibility: dict[tuple[str, str, str], list[StockUnit]] = defaultdict(list)
    unit_weights_by_compatibility: dict[tuple[str, str, str], float] = {}
    for stock in stock_units:
        if stock.unit_weight_kg_per_m and stock.unit_weight_kg_per_m > 0:
            unit_weight = float(stock.unit_weight_kg_per_m)
            unit_weights_by_compatibility[stock.group_key] = min(
                unit_weights_by_compatibility.get(stock.group_key, unit_weight),
                unit_weight,
            )
        if stock.stock_length_mm > 0:
            stocks_by_compatibility[stock.group_key].append(stock)

    result_bars: list[Bar] = []
    statuses: list[str] = []
    gaps: list[float] = []
    next_bar = 1
    for compatibility in sorted(demands_by_compatibility):
        elapsed = perf_counter() - started
        remaining_time = time_limit_seconds - elapsed
        if remaining_time <= 0.01:
            raise TimeoutError("Finite-stock MILP time budget exhausted between groups.")
        group_demands = sorted(
            demands_by_compatibility[compatibility],
            key=lambda item: (-item.net_length_mm, item.demand_id),
        )
        # For the primary objective, at most one initial bar per demand can be useful;
        # longer exact-compatible bars dominate shorter unused bars.
        group_stocks = sorted(
            stocks_by_compatibility.get(compatibility, []),
            key=lambda item: (-item.stock_length_mm, item.stock_unit_id),
        )[: len(group_demands)]
        bars, status, gap = _solve_compatibility_group(
            group_demands,
            group_stocks,
            lengths,
            boundary_allowance_mm,
            remaining_time,
            threads,
            unit_weights_by_compatibility.get(compatibility),
        )
        for bar in bars:
            bar.bar_id = "BAR-%06d" % next_bar
            next_bar += 1
            result_bars.append(bar)
        statuses.append(status)
        gaps.append(gap)

    elapsed_ms = int(round((perf_counter() - started) * 1000.0))
    overall_status = "OPTIMAL" if all(value == "OPTIMAL" for value in statuses) else "FEASIBLE"
    result = NestingResult(
        algorithm="RESOURCE_PURCHASE_MILP",
        boundary_allowance_mm=boundary_allowance_mm,
        bars=result_bars,
        unassigned=[],
        input_count=len(demands),
        elapsed_ms=elapsed_ms,
        solver_status=overall_status,
        mip_gap=max(gaps, default=0.0),
    )
    result.solver_objective = result.additional_purchase_weight_t
    return result


def _solve_compatibility_group(
    demands: list[Demand],
    stocks: list[StockUnit],
    lengths: list[float],
    allowance: float,
    time_limit: float,
    threads: int,
    unit_weight_per_m: float | None,
) -> tuple[list[Bar], str, float]:
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    model.setOptionValue("threads", max(1, int(threads)))
    model.setOptionValue("time_limit", max(0.01, float(time_limit)))
    model.setOptionValue("mip_rel_gap", 0.0)

    count = len(demands)
    demand_groups: dict[tuple[str, str, str, str, str], list[int]] = defaultdict(list)
    for item, demand in enumerate(demands):
        demand_groups[demand.group_key].append(item)
    group_keys = sorted(demand_groups)
    group_index = {key: index for index, key in enumerate(group_keys)}
    weight_per_m = unit_weight_per_m
    if weight_per_m is None:
        raise ValueError(
            "A positive nominal kg/m reference is required for finite-stock purchase MILP."
        )
    maximum_secondary = count * max(lengths) * (count + 1) + count
    primary_multiplier = maximum_secondary + 1.0

    initial_active: dict[int, object] = {}
    initial_group: dict[tuple[int, int], object] = {}
    initial_assignment: dict[tuple[int, int], object] = {}
    for stock_no, stock in enumerate(stocks):
        initial_active[stock_no] = model.addVariable(
            lb=0, ub=1, type=highspy.HighsVarType.kInteger, name="s_%d" % stock_no
        )
        for group_no, _ in enumerate(group_keys):
            initial_group[(stock_no, group_no)] = model.addVariable(
                lb=0,
                ub=1,
                type=highspy.HighsVarType.kInteger,
                name="z_%d_%d" % (stock_no, group_no),
            )
        for item in range(count):
            initial_assignment[(item, stock_no)] = model.addVariable(
                lb=0,
                ub=1,
                type=highspy.HighsVarType.kInteger,
                name="xs_%d_%d" % (item, stock_no),
            )

    purchase_choice: dict[tuple[int, int, int], object] = {}
    purchase_assignment: dict[tuple[int, int, int], object] = {}
    for group_no, key in enumerate(group_keys):
        slot_count = len(demand_groups[key])
        for slot in range(slot_count):
            for length_no, length in enumerate(lengths):
                grams = (
                    round(length * weight_per_m)
                    if weight_per_m is not None
                    else round(length)
                )
                cost = (
                    grams * primary_multiplier
                    + length * (count + 1)
                    + 1.0
                )
                purchase_choice[(group_no, slot, length_no)] = model.addVariable(
                    lb=0,
                    ub=1,
                    obj=cost,
                    type=highspy.HighsVarType.kInteger,
                    name="y_%d_%d_%d" % (group_no, slot, length_no),
                )
            for item in demand_groups[key]:
                purchase_assignment[(item, group_no, slot)] = model.addVariable(
                    lb=0,
                    ub=1,
                    type=highspy.HighsVarType.kInteger,
                    name="xp_%d_%d_%d" % (item, group_no, slot),
                )

    for item, demand in enumerate(demands):
        group_no = group_index[demand.group_key]
        model.addConstr(
            sum(initial_assignment[(item, stock_no)] for stock_no in range(len(stocks)))
            + sum(
                purchase_assignment[(item, group_no, slot)]
                for slot in range(len(demand_groups[demand.group_key]))
            )
            == 1
        )

    for stock_no, stock in enumerate(stocks):
        active = initial_active[stock_no]
        model.addConstr(
            sum(initial_group[(stock_no, group_no)] for group_no in range(len(group_keys)))
            == active
        )
        model.addConstr(
            active
            <= sum(initial_assignment[(item, stock_no)] for item in range(count))
        )
        for item, demand in enumerate(demands):
            model.addConstr(
                initial_assignment[(item, stock_no)]
                <= initial_group[(stock_no, group_index[demand.group_key])]
            )
        model.addConstr(
            sum(
                (demand.net_length_mm + allowance)
                * initial_assignment[(item, stock_no)]
                for item, demand in enumerate(demands)
            )
            <= (stock.stock_length_mm - allowance) * active
        )

    for group_no, key in enumerate(group_keys):
        slot_count = len(demand_groups[key])
        actives: list[object] = []
        for slot in range(slot_count):
            active = sum(
                purchase_choice[(group_no, slot, length_no)]
                for length_no in range(len(lengths))
            )
            actives.append(active)
            model.addConstr(active <= 1)
            model.addConstr(
                active
                <= sum(
                    purchase_assignment[(item, group_no, slot)]
                    for item in demand_groups[key]
                )
            )
            for item in demand_groups[key]:
                model.addConstr(purchase_assignment[(item, group_no, slot)] <= active)
            model.addConstr(
                sum(
                    (demands[item].net_length_mm + allowance)
                    * purchase_assignment[(item, group_no, slot)]
                    for item in demand_groups[key]
                )
                <= sum(
                    (length - allowance)
                    * purchase_choice[(group_no, slot, length_no)]
                    for length_no, length in enumerate(lengths)
                )
            )
        for slot in range(slot_count - 1):
            model.addConstr(actives[slot] >= actives[slot + 1])

    model.setMinimize()
    model.run()
    model_status = model.getModelStatus()
    solution = model.getSolution()
    if not solution.value_valid:
        raise RuntimeError(
            "HiGHS did not return a finite-stock MILP solution: %s"
            % model.modelStatusToString(model_status)
        )
    status = (
        "OPTIMAL"
        if model_status == highspy.HighsModelStatus.kOptimal
        else model.modelStatusToString(model_status).upper().replace(" ", "_")
    )

    bars: list[Bar] = []
    for stock_no, stock in enumerate(stocks):
        if model.val(initial_active[stock_no]) <= 0.5:
            continue
        assigned = [
            demand
            for item, demand in enumerate(demands)
            if model.val(initial_assignment[(item, stock_no)]) > 0.5
        ]
        if assigned:
            bars.append(
                Bar(
                    bar_id="",
                    material=stock.material,
                    profile_type=stock.profile_type,
                    specification=stock.specification,
                    stock_length_mm=stock.stock_length_mm,
                    stock_source_type=stock.source_type,
                    stock_unit_id=stock.stock_unit_id,
                    unit_weight_kg_per_m=stock.unit_weight_kg_per_m,
                    demands=assigned,
                )
            )
    for group_no, key in enumerate(group_keys):
        slot_count = len(demand_groups[key])
        for slot in range(slot_count):
            selected_length = next(
                (
                    length
                    for length_no, length in enumerate(lengths)
                    if model.val(purchase_choice[(group_no, slot, length_no)]) > 0.5
                ),
                None,
            )
            if selected_length is None:
                continue
            assigned = [
                demands[item]
                for item in demand_groups[key]
                if model.val(purchase_assignment[(item, group_no, slot)]) > 0.5
            ]
            if assigned:
                first = assigned[0]
                bars.append(
                    Bar(
                        bar_id="",
                        material=first.material,
                        profile_type=first.profile_type,
                        specification=first.specification,
                        stock_length_mm=selected_length,
                        stock_source_type="NEW_PURCHASE",
                        unit_weight_kg_per_m=weight_per_m,
                        demands=assigned,
                    )
                )
    info = model.getInfo()
    return bars, status, float(info.mip_gap)
