from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from time import perf_counter

from .algorithms import (
    Bar, Demand, MIN_REUSABLE_REMNANT_MM, NestingResult, StockUnit,
    UnassignedDemand,
)
from .assignment_alns import (
    AssignmentAlnsConfig,
    DESTROY_OPERATORS,
    _penalties,
    improve_assignment,
)
from .multisource_alns import (
    MultiSourceAlnsConfig,
    MultiSourceScenario,
    _demand_groups,
    _pack_geometry,
    _repair_purchased_bars_with_milp,
    _serial_material_plan,
)


@dataclass(frozen=True, slots=True)
class TrueMultiSourceAlnsConfig:
    seed: int = 0
    iterations_per_active_geometry: int = 500
    destroy_fraction: float = 0.15
    max_removed: int = 24
    regret_k: int = 2
    operators: tuple[str, ...] = DESTROY_OPERATORS
    adaptive_weights: bool = True
    with_local_milp: bool = False
    total_time_limit_seconds: float = 600.0
    geometry_time_limit_seconds: float = 90.0
    local_milp_max_group_parts: int = 30
    local_milp_max_groups: int = 5
    local_milp_seconds_per_group: float = 2.0
    local_milp_total_seconds: float = 10.0
    min_reusable_remnant_mm: float = MIN_REUSABLE_REMNANT_MM


def solve_true_multisource_alns(
    demands: list[Demand],
    initial_stocks: list[StockUnit],
    remnants: list[StockUnit],
    standard_lengths_mm: list[float],
    allowance: float,
    substitution_rules: dict[tuple[str, str, str], float],
    scenario: MultiSourceScenario,
    config: TrueMultiSourceAlnsConfig,
) -> NestingResult:
    if config.iterations_per_active_geometry < 0:
        raise ValueError("ALNS iteration count must be non-negative.")
    if config.min_reusable_remnant_mm <= 0:
        raise ValueError("Positive reusable remnant threshold is required.")
    lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
    if not lengths:
        raise ValueError("At least one positive standard length is required.")
    started = perf_counter()
    effective_rules = substitution_rules if scenario.use_substitution else {}
    stocks = list(initial_stocks)
    if scenario.use_remnants:
        stocks.extend(remnants)
    demands_by_geometry: dict[tuple[str, str], list[Demand]] = defaultdict(list)
    stocks_by_geometry: dict[tuple[str, str], list[StockUnit]] = defaultdict(list)
    for demand in demands:
        demands_by_geometry[demand.compatibility_key[1:]].append(demand)
    for stock in stocks:
        stocks_by_geometry[stock.group_key[1:]].append(stock)

    all_bars: list[Bar] = []
    all_unassigned: list[UnassignedDemand] = []
    all_penalties: dict[str, float] = {}
    completed_iterations = 0
    active_geometries = 0
    operator_uses = {name: 0 for name in config.operators}
    operator_improvements = {name: 0 for name in config.operators}
    for geometry in sorted(demands_by_geometry):
        group_demands = demands_by_geometry[geometry]
        group_stocks = stocks_by_geometry.get(geometry, [])
        groups = _demand_groups(group_demands)
        order = sorted(groups)
        serial_plan = (
            _serial_material_plan(groups, group_stocks, allowance, effective_rules)
            if scenario.use_substitution else None
        )
        initial_plan = serial_plan if scenario.use_substitution else None
        bars, unassigned, penalties = _pack_geometry(
            group_demands, group_stocks, lengths, allowance, effective_rules,
            order, initial_plan, False,
        )
        can_improve = (
            config.iterations_per_active_geometry > 0
            and len(group_demands) > 1
            and (
                any(bar.stock_source_type == "NEW_PURCHASE" for bar in bars)
                or _substitution_inventory_relevant(
                    group_demands, group_stocks, effective_rules
                )
            )
        )
        if can_improve:
            active_geometries += 1
            forced_for_first_stage = (
                serial_plan
                if scenario.use_substitution
                else None
            )
            bars, unassigned, penalties, stats = _improve_stage(
                bars, unassigned, group_stocks, lengths, allowance,
                effective_rules, forced_for_first_stage, config,
                _stage_seed(config.seed, geometry, "SERIAL"),
                started,
            )
            completed_iterations += int(stats["completed_iterations"])
            _merge_stats(operator_uses, stats["operator_uses"])
            _merge_stats(operator_improvements, stats["operator_improvements"])
            if scenario.use_substitution and scenario.joint_material_nesting:
                bars, unassigned, penalties, stats = _improve_stage(
                    bars, unassigned, group_stocks, lengths, allowance,
                    effective_rules, None, config,
                    _stage_seed(config.seed, geometry, "JOINT"),
                    started,
                )
                completed_iterations += int(stats["completed_iterations"])
                _merge_stats(operator_uses, stats["operator_uses"])
                _merge_stats(operator_improvements, stats["operator_improvements"])
        all_bars.extend(bars)
        all_unassigned.extend(unassigned)
        all_penalties.update(penalties)

    local_repairs = 0
    if config.with_local_milp:
        remaining = config.total_time_limit_seconds - (perf_counter() - started)
        if remaining > 0.05:
            local_config = MultiSourceAlnsConfig(
                enable_local_milp=True,
                local_milp_max_group_parts=config.local_milp_max_group_parts,
                local_milp_max_groups=config.local_milp_max_groups,
                local_milp_seconds_per_group=config.local_milp_seconds_per_group,
                local_milp_total_seconds=min(config.local_milp_total_seconds, remaining),
            )
            local_repairs = _repair_purchased_bars_with_milp(
                all_bars, lengths, allowance, effective_rules, all_penalties,
                local_config,
            )
    for number, bar in enumerate(all_bars, start=1):
        bar.bar_id = "BAR-%06d" % number
    result = NestingResult(
        algorithm=(
            "TRUE_MULTISOURCE_ALNS_MILP_%s" % scenario.name
            if config.with_local_milp
            else "TRUE_MULTISOURCE_ALNS_%s" % scenario.name
        ),
        boundary_allowance_mm=allowance,
        bars=all_bars,
        unassigned=all_unassigned,
        input_count=len(demands),
        elapsed_ms=int(round((perf_counter() - started) * 1000.0)),
        solver_status=(
            "HEURISTIC_DESTROY_REPAIR_%d_ITERATIONS_%d_LOCAL_MILP_REPAIRS"
            % (completed_iterations, local_repairs)
        ),
        substitution_penalty_by_demand=all_penalties,
        min_reusable_remnant_mm=config.min_reusable_remnant_mm,
    )
    result.solver_objective = result.additional_purchase_weight_t
    return result


def _improve_stage(
    bars: list[Bar],
    unassigned: list[UnassignedDemand],
    stocks: list[StockUnit],
    lengths: list[float],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    forced_material: dict[tuple[str, str, str, str, str], str] | None,
    config: TrueMultiSourceAlnsConfig,
    seed: int,
    started: float,
) -> tuple[list[Bar], list[UnassignedDemand], dict[str, float], dict[str, object]]:
    remaining = min(
        config.geometry_time_limit_seconds,
        config.total_time_limit_seconds - (perf_counter() - started),
    )
    if remaining <= 0.05:
        return bars, unassigned, _penalties(bars, rules), {
            "completed_iterations": 0,
            "operator_uses": {},
            "operator_improvements": {},
        }
    return improve_assignment(
        bars, unassigned, stocks, lengths, allowance, rules,
        forced_material=forced_material,
        config=AssignmentAlnsConfig(
            seed=seed,
            iterations=config.iterations_per_active_geometry,
            destroy_fraction=config.destroy_fraction,
            max_removed=config.max_removed,
            regret_k=config.regret_k,
            time_limit_seconds=remaining,
            operators=config.operators,
            adaptive_weights=config.adaptive_weights,
            min_reusable_remnant_mm=config.min_reusable_remnant_mm,
        ),
    )


def _stage_seed(seed: int, geometry: tuple[str, str], stage: str) -> int:
    digest = hashlib.sha256(
        ("%d|%s|%s|%s" % (seed, geometry[0], geometry[1], stage)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _substitution_inventory_relevant(
    demands: list[Demand],
    stocks: list[StockUnit],
    rules: dict[tuple[str, str, str], float],
) -> bool:
    available_materials = {stock.group_key[0] for stock in stocks}
    return any(
        (demand.compatibility_key[0], stock_material, demand.compatibility_key[1])
        in rules
        for demand in demands
        for stock_material in available_materials
        if stock_material != demand.compatibility_key[0]
    )


def _merge_stats(target: dict[str, int], source: dict[str, object]) -> None:
    for name, value in source.items():
        target[name] = target.get(name, 0) + int(value)
