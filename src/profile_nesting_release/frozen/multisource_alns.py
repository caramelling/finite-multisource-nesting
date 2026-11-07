from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import random
from time import perf_counter

from .algorithms import (
    Bar,
    Demand,
    EPSILON,
    NestingResult,
    StockUnit,
    UnassignedDemand,
    normalize_material,
)


@dataclass(frozen=True, slots=True)
class MultiSourceScenario:
    name: str
    use_remnants: bool
    use_substitution: bool
    joint_material_nesting: bool


@dataclass(frozen=True, slots=True)
class MultiSourceAlnsConfig:
    seed: int = 0
    iterations_per_active_geometry: int = 500
    cooling_rate: float = 0.995
    segment_length: int = 50
    reaction_factor: float = 0.20
    enabled_operators: tuple[str, ...] = (
        "random_swap",
        "random_relocate",
        "related_reverse",
        "purchase_first",
    )
    regret_k: int = 2
    enable_bar_merge: bool = False
    use_adaptive_weights: bool = False
    enable_local_milp: bool = True
    local_milp_max_group_parts: int = 30
    local_milp_max_groups: int = 5
    local_milp_seconds_per_group: float = 2.0
    local_milp_total_seconds: float = 10.0


def solve_multisource_alns(
    demands: list[Demand],
    initial_stocks: list[StockUnit],
    remnants: list[StockUnit],
    standard_lengths_mm: list[float],
    allowance: float,
    substitution_rules: dict[tuple[str, str, str], float],
    scenario: MultiSourceScenario,
    config: MultiSourceAlnsConfig,
) -> NestingResult:
    lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
    if not lengths:
        raise ValueError("Multi-source ALNS requires positive purchase lengths.")
    if not config.enabled_operators:
        raise ValueError("At least one ALNS operator must be enabled.")
    started = perf_counter()
    effective_rules = substitution_rules if scenario.use_substitution else {}
    stocks = list(initial_stocks)
    if scenario.use_remnants:
        stocks.extend(remnants)

    demand_by_geometry: dict[tuple[str, str], list[Demand]] = defaultdict(list)
    for demand in demands:
        demand_by_geometry[demand.compatibility_key[1:]].append(demand)
    stock_by_geometry: dict[tuple[str, str], list[StockUnit]] = defaultdict(list)
    for stock in stocks:
        stock_by_geometry[stock.group_key[1:]].append(stock)

    all_bars: list[Bar] = []
    all_unassigned: list[UnassignedDemand] = []
    all_penalties: dict[str, float] = {}
    evaluations = 0
    for geometry in sorted(demand_by_geometry):
        geometry_demands = demand_by_geometry[geometry]
        geometry_stocks = stock_by_geometry.get(geometry, [])
        groups = _demand_groups(geometry_demands)
        order = sorted(groups)
        serial_plan = (
            _serial_material_plan(groups, geometry_stocks, allowance, effective_rules)
            if scenario.use_substitution
            else None
        )
        forced_material = serial_plan if not scenario.joint_material_nesting else None
        geometry_seed = "%d|%s|%s" % (config.seed, geometry[0], geometry[1])
        serial_rng = random.Random(geometry_seed + "|SERIAL")
        joint_rng = random.Random(geometry_seed + "|JOINT")
        bars, unassigned, penalties = _pack_geometry(
            geometry_demands,
            geometry_stocks,
            lengths,
            allowance,
            effective_rules,
            order,
            forced_material,
            False,
        )
        evaluations += 1
        active = (
            len(groups) > 1
            and config.iterations_per_active_geometry > 0
            and (
                any(bar.stock_source_type == "NEW_PURCHASE" for bar in bars)
                or _substitution_is_relevant(groups, geometry_stocks, effective_rules)
                or (
                    scenario.use_remnants
                    and any(stock.source_type == "CONTROLLED_REMNANT" for stock in geometry_stocks)
                )
            )
        )
        if active:
            if scenario.use_substitution and serial_plan is not None:
                serial_bars, serial_unassigned, serial_penalties = _pack_geometry(
                    geometry_demands,
                    geometry_stocks,
                    lengths,
                    allowance,
                    effective_rules,
                    order,
                    serial_plan,
                    False,
                )
                evaluations += 1
                (
                    serial_order,
                    serial_bars,
                    serial_unassigned,
                    serial_penalties,
                    serial_evaluations,
                ) = _search_geometry(
                    geometry_demands,
                    geometry_stocks,
                    lengths,
                    allowance,
                    effective_rules,
                    serial_plan,
                    order,
                    serial_bars,
                    serial_unassigned,
                    serial_penalties,
                    config,
                    serial_rng,
                )
                evaluations += serial_evaluations
                if not scenario.joint_material_nesting:
                    order, bars, unassigned, penalties = (
                        serial_order,
                        serial_bars,
                        serial_unassigned,
                        serial_penalties,
                    )
                else:
                    joint_bars, joint_unassigned, joint_penalties = _pack_geometry(
                        geometry_demands,
                        geometry_stocks,
                        lengths,
                        allowance,
                        effective_rules,
                        serial_order,
                        None,
                        False,
                    )
                    evaluations += 1
                    if _result_score(
                        joint_bars, joint_unassigned, joint_penalties, allowance
                    ) < _result_score(
                        serial_bars, serial_unassigned, serial_penalties, allowance
                    ):
                        serial_bars = joint_bars
                        serial_unassigned = joint_unassigned
                        serial_penalties = joint_penalties
                    (
                        order,
                        bars,
                        unassigned,
                        penalties,
                        joint_evaluations,
                    ) = _search_geometry(
                        geometry_demands,
                        geometry_stocks,
                        lengths,
                        allowance,
                        effective_rules,
                        None,
                        serial_order,
                        serial_bars,
                        serial_unassigned,
                        serial_penalties,
                        config,
                        joint_rng,
                    )
                    evaluations += joint_evaluations
            else:
                (
                    order,
                    bars,
                    unassigned,
                    penalties,
                    group_evaluations,
                ) = _search_geometry(
                    geometry_demands,
                    geometry_stocks,
                    lengths,
                    allowance,
                    effective_rules,
                    forced_material,
                    order,
                    bars,
                    unassigned,
                    penalties,
                    config,
                    joint_rng,
                )
                evaluations += group_evaluations
        if config.enable_bar_merge:
            _merge_bars(bars, allowance, effective_rules, penalties)
        all_bars.extend(bars)
        all_unassigned.extend(unassigned)
        all_penalties.update(penalties)

    repaired_groups = 0
    if config.enable_local_milp:
        repaired_groups = _repair_purchased_bars_with_milp(
            all_bars,
            lengths,
            allowance,
            effective_rules,
            all_penalties,
            config,
        )

    for number, bar in enumerate(all_bars, start=1):
        bar.bar_id = "BAR-%06d" % number
    result = NestingResult(
        algorithm="MULTISOURCE_ALNS_%s" % scenario.name,
        boundary_allowance_mm=allowance,
        bars=all_bars,
        unassigned=all_unassigned,
        input_count=len(demands),
        elapsed_ms=int(round((perf_counter() - started) * 1000.0)),
        solver_status=(
            "HEURISTIC_MULTISOURCE_ALNS_%d_EVALUATIONS_%d_MILP_REPAIRS"
            % (evaluations, repaired_groups)
        ),
        substitution_penalty_by_demand=all_penalties,
    )
    result.solver_objective = result.additional_purchase_weight_t
    return result


def _search_geometry(
    demands: list[Demand],
    stocks: list[StockUnit],
    lengths: list[float],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    forced_material: dict[tuple[str, str, str, str, str], str] | None,
    initial_order: list[tuple[str, str, str, str, str]],
    initial_bars: list[Bar],
    initial_unassigned: list[UnassignedDemand],
    initial_penalties: dict[str, float],
    config: MultiSourceAlnsConfig,
    rng: random.Random,
) -> tuple[
    list[tuple[str, str, str, str, str]],
    list[Bar],
    list[UnassignedDemand],
    dict[str, float],
    int,
]:
    groups = _demand_groups(demands)
    current_order = list(initial_order)
    current_bars = initial_bars
    current_unassigned = initial_unassigned
    current_penalties = initial_penalties
    current_score = _result_score(current_bars, current_unassigned, current_penalties, allowance)
    best_order = list(current_order)
    best_bars = current_bars
    best_unassigned = current_unassigned
    best_penalties = current_penalties
    best_score = current_score
    evaluations = 0
    operators = config.enabled_operators
    weights = {name: 1.0 for name in operators}
    rewards = {name: 0.0 for name in operators}
    uses = {name: 0 for name in operators}
    temperature = max(1.0, _scalar(current_score) * 0.01)
    for iteration in range(config.iterations_per_active_geometry):
        operator = rng.choices(
            operators, weights=[weights[name] for name in operators], k=1
        )[0]
        candidate_order = _mutate_order(
            current_order, operator, current_bars, groups, stocks, rules, rng
        )
        bars, unassigned, penalties = _pack_geometry(
            demands,
            stocks,
            lengths,
            allowance,
            rules,
            candidate_order,
            forced_material,
            False,
        )
        score = _result_score(bars, unassigned, penalties, allowance)
        evaluations += 1
        uses[operator] += 1
        accepted = score <= current_score
        if not accepted:
            delta = _scalar(score) - _scalar(current_score)
            accepted = rng.random() < math.exp(-max(0.0, delta) / temperature)
        if accepted:
            if score < current_score:
                rewards[operator] += 2.0
            else:
                rewards[operator] += 0.5
            current_order = candidate_order
            current_bars = bars
            current_unassigned = unassigned
            current_penalties = penalties
            current_score = score
        if score < best_score:
            best_order = list(candidate_order)
            best_bars = bars
            best_unassigned = unassigned
            best_penalties = penalties
            best_score = score
            rewards[operator] += 5.0
        temperature = max(0.01, temperature * config.cooling_rate)
        if config.use_adaptive_weights and (iteration + 1) % config.segment_length == 0:
            for name in operators:
                observed = rewards[name] / uses[name] if uses[name] else 0.1
                weights[name] = (
                    (1.0 - config.reaction_factor) * weights[name]
                    + config.reaction_factor * max(0.1, observed)
                )
                rewards[name] = 0.0
                uses[name] = 0
    return best_order, best_bars, best_unassigned, best_penalties, evaluations


def _pack_geometry(
    demands: list[Demand],
    stocks: list[StockUnit],
    lengths: list[float],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    order: list[tuple[str, str, str, str, str]],
    forced_material: dict[tuple[str, str, str, str, str], str] | None,
    enable_bar_merge: bool,
) -> tuple[list[Bar], list[UnassignedDemand], dict[str, float]]:
    groups = _demand_groups(demands)
    available: dict[str, list[StockUnit]] = defaultdict(list)
    weight_by_material: dict[str, float] = {}
    geometry_weight: float | None = None
    for stock in stocks:
        material = stock.group_key[0]
        available[material].append(stock)
        if stock.unit_weight_kg_per_m and stock.unit_weight_kg_per_m > 0:
            weight_by_material[material] = float(stock.unit_weight_kg_per_m)
            geometry_weight = float(stock.unit_weight_kg_per_m)
    for values in available.values():
        values.sort(
            key=lambda item: (
                0 if item.source_type == "CONTROLLED_REMNANT" else 1,
                item.stock_length_mm,
                item.stock_unit_id,
            )
        )
    bars: list[Bar] = []
    open_by_block: dict[tuple[str, str, str, str], list[Bar]] = defaultdict(list)
    unassigned: list[UnassignedDemand] = []
    penalties: dict[str, float] = {}
    new_bars: list[Bar] = []
    next_bar = 1
    maximum = max(lengths)

    for group_key in order:
        group = sorted(groups[group_key], key=lambda item: (-item.net_length_mm, item.demand_id))
        for demand in group:
            if demand.net_length_mm <= 0:
                unassigned.append(
                    UnassignedDemand(demand, "INVALID_LENGTH", "Net length must be positive.")
                )
                continue
            if demand.net_length_mm + 2.0 * allowance > maximum + EPSILON:
                unassigned.append(
                    UnassignedDemand(
                        demand, "NO_PURCHASABLE_LENGTH",
                        "Demand exceeds the longest purchase length.",
                    )
                )
                continue
            required_material = demand.compatibility_key[0]
            allowed = _allowed_materials(demand, rules)
            if forced_material is not None:
                selected_material = forced_material[group_key]
                allowed = {
                    selected_material: allowed.get(selected_material, 0.0)
                }
            block_key = (
                demand.project_code.strip().upper(),
                demand.block_name.strip().upper(),
                demand.compatibility_key[1],
                demand.compatibility_key[2],
            )
            options: list[tuple[tuple[float, ...], str, object]] = []
            for bar in open_by_block[block_key]:
                material = normalize_material(bar.material)
                if material in allowed and bar.can_fit(demand, allowance):
                    options.append(
                        (
                            (
                                0.0,
                                float(allowed[material]),
                                0.0,
                                0.0 if bar.stock_source_type == "CONTROLLED_REMNANT" else 1.0,
                                bar.remaining_length_mm(allowance)
                                - demand.net_length_mm
                                - allowance,
                            ),
                            "OPEN",
                            bar,
                        )
                    )
            required = demand.net_length_mm + 2.0 * allowance
            for material, penalty in allowed.items():
                candidates = [
                    (index, stock)
                    for index, stock in enumerate(available.get(material, []))
                    if stock.stock_length_mm + EPSILON >= required
                ]
                if candidates:
                    index, stock = min(
                        candidates,
                        key=lambda item: (
                            0 if item[1].source_type == "CONTROLLED_REMNANT" else 1,
                            item[1].stock_length_mm,
                            item[1].stock_unit_id,
                        ),
                    )
                    options.append(
                        (
                            (
                                0.0,
                                float(penalty),
                                1.0,
                                0.0 if stock.source_type == "CONTROLLED_REMNANT" else 1.0,
                                stock.stock_length_mm - required,
                            ),
                            "STOCK",
                            (material, index, stock),
                        )
                    )
            purchase_material = (
                next(iter(allowed)) if forced_material is not None else required_material
            )
            purchase_penalty = float(allowed.get(purchase_material, 0.0))
            purchase_weight = weight_by_material.get(purchase_material, geometry_weight or 0.0)
            if purchase_weight <= 0:
                raise ValueError(
                    "A positive nominal kg/m reference is required for additional purchase."
                )
            options.append(
                (
                    (1.0, purchase_penalty, 1.0, 2.0, maximum - required),
                    "PURCHASE",
                    (purchase_material, purchase_weight),
                )
            )
            _, option_type, payload = min(options, key=lambda item: item[0])
            if option_type == "OPEN":
                bar = payload
            elif option_type == "STOCK":
                material, index, stock = payload
                available[material].pop(index)
                bar = Bar(
                    bar_id="TMP-%06d" % next_bar,
                    stock_unit_id=stock.stock_unit_id,
                    stock_source_type=stock.source_type,
                    material=stock.material,
                    profile_type=stock.profile_type,
                    specification=stock.specification,
                    stock_length_mm=stock.stock_length_mm,
                    unit_weight_kg_per_m=stock.unit_weight_kg_per_m,
                )
                next_bar += 1
                bars.append(bar)
                open_by_block[block_key].append(bar)
            else:
                material, unit_weight = payload
                bar = Bar(
                    bar_id="TMP-%06d" % next_bar,
                    stock_source_type="NEW_PURCHASE",
                    material=material,
                    profile_type=demand.profile_type,
                    specification=demand.specification,
                    stock_length_mm=maximum,
                    unit_weight_kg_per_m=unit_weight,
                )
                next_bar += 1
                bars.append(bar)
                new_bars.append(bar)
                open_by_block[block_key].append(bar)
            bar.demands.append(demand)
            actual_material = normalize_material(bar.material)
            if actual_material != required_material:
                penalties[demand.demand_id] = float(allowed[actual_material])

    for bar in new_bars:
        used = bar.used_length_mm(allowance)
        bar.stock_length_mm = next(length for length in lengths if length + EPSILON >= used)
    if enable_bar_merge:
        _merge_bars(bars, allowance, rules, penalties)
    return bars, unassigned, penalties


def _serial_material_plan(
    groups: dict[tuple[str, str, str, str, str], list[Demand]],
    stocks: list[StockUnit],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
) -> dict[tuple[str, str, str, str, str], str]:
    capacity: dict[str, float] = defaultdict(float)
    for stock in stocks:
        capacity[stock.group_key[0]] += max(0.0, stock.stock_length_mm - allowance)
    result = {}
    for key in sorted(
        groups,
        key=lambda item: (
            -sum(demand.net_length_mm + allowance for demand in groups[item]),
            item,
        ),
    ):
        probe = groups[key][0]
        allowed = _allowed_materials(probe, rules)
        required = sum(demand.net_length_mm + allowance for demand in groups[key])
        selected = min(
            allowed,
            key=lambda material: (
                0 if capacity[material] + EPSILON >= required else 1,
                float(allowed[material]),
                -capacity[material],
                material,
            ),
        )
        capacity[selected] = max(0.0, capacity[selected] - required)
        result[key] = selected
    return result


def _allowed_materials(
    demand: Demand, rules: dict[tuple[str, str, str], float]
) -> dict[str, float]:
    required = demand.compatibility_key[0]
    profile = demand.compatibility_key[1]
    result = {required: 0.0}
    for (demand_material, stock_material, rule_profile), penalty in rules.items():
        if demand_material == required and rule_profile == profile:
            result[stock_material] = float(penalty)
    return result


def _demand_groups(
    demands: list[Demand],
) -> dict[tuple[str, str, str, str, str], list[Demand]]:
    groups: dict[tuple[str, str, str, str, str], list[Demand]] = defaultdict(list)
    for demand in demands:
        groups[demand.group_key].append(demand)
    return groups


def _mutate_order(
    order: list[tuple[str, str, str, str, str]],
    operator: str,
    bars: list[Bar],
    groups: dict[tuple[str, str, str, str, str], list[Demand]],
    stocks: list[StockUnit],
    rules: dict[tuple[str, str, str], float],
    rng: random.Random,
) -> list[tuple[str, str, str, str, str]]:
    candidate = list(order)
    if len(candidate) < 2:
        return candidate
    left, right = sorted(rng.sample(range(len(candidate)), 2))
    if operator == "random_swap":
        candidate[left], candidate[right] = candidate[right], candidate[left]
    elif operator == "random_relocate":
        item = candidate.pop(left)
        candidate.insert(right, item)
    elif operator == "related_reverse":
        candidate[left : right + 1] = reversed(candidate[left : right + 1])
    elif operator == "purchase_first":
        purchase: dict[tuple[str, str, str, str, str], float] = defaultdict(float)
        for bar in bars:
            if bar.stock_source_type == "NEW_PURCHASE" and bar.demands:
                purchase[bar.demands[0].group_key] += bar.stock_length_mm
        candidate.sort(key=lambda key: (-purchase[key], key))
    elif operator == "remnant_first":
        remnant_materials = {
            stock.group_key[0]
            for stock in stocks
            if stock.source_type == "CONTROLLED_REMNANT"
        }
        candidate.sort(
            key=lambda key: (
                0 if any(material in remnant_materials for material in _allowed_materials(groups[key][0], rules)) else 1,
                -sum(item.net_length_mm for item in groups[key]),
                key,
            )
        )
    elif operator == "substitution_conflict":
        candidate.sort(
            key=lambda key: (
                -len(_allowed_materials(groups[key][0], rules)),
                -sum(item.net_length_mm for item in groups[key]),
                key,
            )
        )
    elif operator == "regret_k_repair":
        capacity: dict[str, float] = defaultdict(float)
        for stock in stocks:
            capacity[stock.group_key[0]] += stock.stock_length_mm
        regret: dict[tuple[str, str, str, str, str], float] = {}
        for key in candidate:
            required = sum(item.net_length_mm for item in groups[key])
            material_costs = sorted(
                float(penalty) * 1.0e9 + max(0.0, required - capacity[material])
                for material, penalty in _allowed_materials(groups[key][0], rules).items()
            )
            if len(material_costs) >= 2:
                position = min(len(material_costs), 2) - 1
                regret[key] = material_costs[position] - material_costs[0]
            else:
                regret[key] = 0.0
        candidate.sort(
            key=lambda key: (
                -regret[key],
                -sum(item.net_length_mm for item in groups[key]),
                key,
            )
        )
    elif operator == "resource_regret_repair":
        capacity: dict[str, float] = defaultdict(float)
        remnant_capacity: dict[str, float] = defaultdict(float)
        for stock in stocks:
            material = stock.group_key[0]
            capacity[material] += stock.stock_length_mm
            if stock.source_type == "CONTROLLED_REMNANT":
                remnant_capacity[material] += stock.stock_length_mm
        purchase_by_group: dict[tuple[str, str, str, str, str], float] = defaultdict(float)
        for bar in bars:
            if bar.stock_source_type == "NEW_PURCHASE" and bar.demands:
                purchase_by_group[bar.demands[0].group_key] += bar.stock_length_mm
        priority = {}
        for key in candidate:
            required = sum(item.net_length_mm for item in groups[key])
            options = []
            for material, penalty in _allowed_materials(groups[key][0], rules).items():
                shortage = max(0.0, required - capacity[material])
                remnant_fit = min(required, remnant_capacity[material])
                cost = float(penalty) * 1.0e9 + shortage - remnant_fit * 0.001
                options.append((cost, remnant_fit))
            options.sort()
            best_cost = options[0][0]
            kth = options[min(configured_regret_index(len(options), 2), len(options) - 1)][0]
            priority[key] = (
                purchase_by_group[key],
                kth - best_cost,
                max(value[1] for value in options),
                required,
            )
        candidate.sort(
            key=lambda key: (
                -priority[key][0],
                -priority[key][1],
                -priority[key][2],
                -priority[key][3],
                key,
            )
        )
    else:
        raise ValueError("Unknown multi-source ALNS operator: %s" % operator)
    return candidate


def configured_regret_index(option_count: int, regret_k: int) -> int:
    return max(0, min(option_count, regret_k) - 1)


def _substitution_is_relevant(
    groups: dict[tuple[str, str, str, str, str], list[Demand]],
    stocks: list[StockUnit],
    rules: dict[tuple[str, str, str], float],
) -> bool:
    stock_materials = {stock.group_key[0] for stock in stocks}
    return any(
        any(
            material != demand.compatibility_key[0] and material in stock_materials
            for material in _allowed_materials(demand, rules)
        )
        for values in groups.values()
        for demand in values[:1]
    )


def _merge_bars(
    bars: list[Bar],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    penalties: dict[str, float],
) -> None:
    """Remove a bar when all of its demands fit compatible open bars."""

    while True:
        merged = False
        donors = sorted(
            list(bars),
            key=lambda bar: (
                0 if bar.stock_source_type == "NEW_PURCHASE" else 1,
                len(bar.demands),
                -bar.remaining_length_mm(allowance),
                bar.bar_id,
            ),
        )
        for donor in donors:
            if not donor.demands:
                continue
            recipients = [bar for bar in bars if bar is not donor]
            demand_snapshots = {id(bar): list(bar.demands) for bar in recipients}
            penalty_snapshot = dict(penalties)
            success = True
            for demand in sorted(
                donor.demands, key=lambda item: (-item.net_length_mm, item.demand_id)
            ):
                allowed = _allowed_materials(demand, rules)
                candidates = [
                    bar
                    for bar in recipients
                    if bar.demands
                    and bar.demands[0].project_code == demand.project_code
                    and bar.demands[0].block_name == demand.block_name
                    and bar_group_geometry(bar) == demand.compatibility_key[1:]
                    and normalize_material(bar.material) in allowed
                    and bar.can_fit(demand, allowance)
                ]
                if not candidates:
                    success = False
                    break
                selected = min(
                    candidates,
                    key=lambda bar: (
                        float(allowed[normalize_material(bar.material)]),
                        bar.remaining_length_mm(allowance)
                        - demand.net_length_mm
                        - allowance,
                        bar.bar_id,
                    ),
                )
                selected.demands.append(demand)
                material = normalize_material(selected.material)
                if material == demand.compatibility_key[0]:
                    penalties.pop(demand.demand_id, None)
                else:
                    penalties[demand.demand_id] = float(allowed[material])
            if success:
                bars.remove(donor)
                for demand in donor.demands:
                    if all(demand not in bar.demands for bar in bars):
                        penalties.pop(demand.demand_id, None)
                merged = True
                break
            for bar in recipients:
                bar.demands[:] = demand_snapshots[id(bar)]
            penalties.clear()
            penalties.update(penalty_snapshot)
        if not merged:
            return


def bar_group_geometry(bar: Bar) -> tuple[str, str]:
    if bar.demands:
        return bar.demands[0].compatibility_key[1:]
    return ("", "")


def _repair_purchased_bars_with_milp(
    bars: list[Bar],
    lengths: list[float],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    penalties: dict[str, float],
    config: MultiSourceAlnsConfig,
) -> int:
    from .exact import _solve_group

    purchase_groups: dict[tuple[str, str, str, str, str], list[Bar]] = defaultdict(list)
    for bar in bars:
        if bar.stock_source_type != "NEW_PURCHASE" or not bar.demands:
            continue
        first = bar.demands[0]
        key = (
            first.project_code,
            first.block_name,
            normalize_material(bar.material),
            first.compatibility_key[1],
            first.compatibility_key[2],
        )
        purchase_groups[key].append(bar)
    candidates = []
    for key, group_bars in purchase_groups.items():
        demands = [demand for bar in group_bars for demand in bar.demands]
        if 1 < len(demands) <= config.local_milp_max_group_parts:
            candidates.append(
                (
                    -sum(bar.stock_length_mm for bar in group_bars),
                    key,
                    group_bars,
                    demands,
                )
            )
    candidates.sort(key=lambda item: (item[0], item[1]))
    deadline = perf_counter() + config.local_milp_total_seconds
    repaired = 0
    for _, key, current_bars, original_demands in candidates[: config.local_milp_max_groups]:
        remaining = deadline - perf_counter()
        if remaining <= 0.05:
            break
        material = key[2]
        original_by_id = {demand.demand_id: demand for demand in original_demands}
        pseudo = [
            Demand(
                demand_id=demand.demand_id,
                project_code=demand.project_code,
                block_name=demand.block_name,
                material=material,
                profile_type=demand.profile_type,
                specification=demand.specification,
                net_length_mm=demand.net_length_mm,
            )
            for demand in original_demands
        ]
        try:
            exact_bars, _, _, _ = _solve_group(
                sorted(pseudo, key=lambda item: (-item.net_length_mm, item.demand_id)),
                lengths,
                allowance,
                min(config.local_milp_seconds_per_group, remaining),
                1,
            )
        except (RuntimeError, TimeoutError):
            continue
        current_score = (
            sum(bar.stock_length_mm for bar in current_bars), len(current_bars)
        )
        exact_score = (sum(bar.stock_length_mm for bar in exact_bars), len(exact_bars))
        if exact_score >= current_score:
            continue
        unit_weight = next(
            (bar.unit_weight_kg_per_m for bar in current_bars if bar.unit_weight_kg_per_m),
            None,
        )
        replacements = []
        for exact_bar in exact_bars:
            replacement_demands = [
                original_by_id[demand.demand_id] for demand in exact_bar.demands
            ]
            first = replacement_demands[0]
            replacement = Bar(
                bar_id="",
                stock_source_type="NEW_PURCHASE",
                material=material,
                profile_type=first.profile_type,
                specification=first.specification,
                stock_length_mm=exact_bar.stock_length_mm,
                unit_weight_kg_per_m=unit_weight,
                demands=replacement_demands,
            )
            replacements.append(replacement)
            for demand in replacement_demands:
                if material == demand.compatibility_key[0]:
                    penalties.pop(demand.demand_id, None)
                else:
                    penalty = rules.get(
                        (demand.compatibility_key[0], material, demand.compatibility_key[1])
                    )
                    if penalty is None:
                        raise ValueError("MILP repair produced an invalid material substitution.")
                    penalties[demand.demand_id] = float(penalty)
        for bar in current_bars:
            bars.remove(bar)
        bars.extend(replacements)
        repaired += 1
    return repaired


def _result_score(
    bars: list[Bar],
    unassigned: list[UnassignedDemand],
    penalties: dict[str, float],
    allowance: float,
) -> tuple[float, ...]:
    purchase = [bar for bar in bars if bar.stock_source_type == "NEW_PURCHASE"]
    purchase_weight = sum(
        bar.stock_length_mm / 1000.0 * float(bar.unit_weight_kg_per_m or 0.0) / 1000.0
        for bar in purchase
    )
    purchase_length = sum(bar.stock_length_mm for bar in purchase)
    total_stock = sum(bar.stock_length_mm for bar in bars)
    remaining = [max(0.0, bar.remaining_length_mm(allowance)) for bar in bars]
    waste = sum(value for value in remaining if value < 1000.0 - EPSILON)
    return (
        float(len(unassigned)),
        sum(item.demand.net_length_mm for item in unassigned),
        round(purchase_weight, 9),
        round(purchase_length, 7),
        float(len(purchase)),
        round(total_stock, 7),
        round(waste, 7),
        round(sum(penalties.values()), 7),
        float(len(penalties)),
    )


def _scalar(score: tuple[float, ...]) -> float:
    return (
        score[0] * 1.0e18
        + score[1] * 1.0e12
        + score[2] * 1.0e9
        + score[3] * 1.0e3
        + score[4]
    )
