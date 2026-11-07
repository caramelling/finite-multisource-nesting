from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import math
import random
from time import perf_counter

from .algorithms import (
    Bar, Demand, EPSILON, MIN_REUSABLE_REMNANT_MM, StockUnit,
    UnassignedDemand, normalize_material,
)


DESTROY_OPERATORS = (
    "random",
    "related",
    "purchase",
    "remnant",
    "substitution",
    "high_remaining",
)


@dataclass(frozen=True, slots=True)
class AssignmentAlnsConfig:
    seed: int = 0
    iterations: int = 500
    destroy_fraction: float = 0.15
    max_removed: int = 24
    regret_k: int = 2
    segment_length: int = 50
    reaction_factor: float = 0.2
    cooling_rate: float = 0.995
    time_limit_seconds: float = 600.0
    operators: tuple[str, ...] = DESTROY_OPERATORS
    adaptive_weights: bool = True
    min_reusable_remnant_mm: float = MIN_REUSABLE_REMNANT_MM

    def validate(self) -> None:
        if self.iterations < 0 or not 0.0 < self.destroy_fraction <= 1.0:
            raise ValueError("Positive iterations and destroy fraction in (0,1] are required.")
        if self.regret_k < 1 or self.segment_length <= 0 or self.max_removed <= 0:
            raise ValueError("regret_k>=1 and positive segment length are required.")
        if not self.operators or any(name not in DESTROY_OPERATORS for name in self.operators):
            raise ValueError("An allowed destroy operator is required.")
        if not 0.0 < self.reaction_factor <= 1.0 or not 0.0 < self.cooling_rate <= 1.0:
            raise ValueError("Reaction and cooling factors must be in (0,1].")
        if self.time_limit_seconds <= 0:
            raise ValueError("Positive time limit is required.")
        if self.min_reusable_remnant_mm <= 0:
            raise ValueError("Positive reusable remnant threshold is required.")


def improve_assignment(
    initial_bars: list[Bar],
    initial_unassigned: list[UnassignedDemand],
    stocks: list[StockUnit],
    standard_lengths_mm: list[float],
    allowance: float,
    substitution_rules: dict[tuple[str, str, str], float],
    *,
    forced_material: dict[tuple[str, str, str, str, str], str] | None = None,
    config: AssignmentAlnsConfig | None = None,
) -> tuple[list[Bar], list[UnassignedDemand], dict[str, float], dict[str, object]]:
    """Search assignments by destroying bars/parts and regret-k resource repair."""

    settings = config or AssignmentAlnsConfig()
    settings.validate()
    lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
    if not lengths:
        raise ValueError("At least one purchasable standard length is required.")
    started = perf_counter()
    rng = random.Random(settings.seed)
    current = _copy_bars(initial_bars)
    current_unassigned = list(initial_unassigned)
    best = _copy_bars(current)
    best_unassigned = list(current_unassigned)
    best_score = _score(
        best, best_unassigned, allowance, substitution_rules,
        settings.min_reusable_remnant_mm,
    )
    current_score = best_score
    weights = {name: 1.0 for name in settings.operators}
    rewards = {name: 0.0 for name in settings.operators}
    uses = {name: 0 for name in settings.operators}
    operator_uses = {name: 0 for name in settings.operators}
    improvements = {name: 0 for name in settings.operators}
    temperature = max(1.0, _scalar(current_score) * 0.01)
    completed = 0

    for iteration in range(settings.iterations):
        if perf_counter() - started >= settings.time_limit_seconds:
            break
        operator = rng.choices(
            settings.operators,
            weights=[weights[name] for name in settings.operators],
            k=1,
        )[0]
        candidate, removed = _destroy(
            current, current_unassigned, operator, allowance,
            settings.destroy_fraction, settings.max_removed, rng,
        )
        candidate_unassigned = _repair(
            candidate, removed, stocks, lengths, allowance,
            substitution_rules, forced_material, settings.regret_k,
        )
        candidate_score = _score(
            candidate, candidate_unassigned, allowance, substitution_rules,
            settings.min_reusable_remnant_mm,
        )
        completed += 1
        uses[operator] += 1
        operator_uses[operator] += 1
        accepted = candidate_score <= current_score
        if not accepted:
            delta = _scalar(candidate_score) - _scalar(current_score)
            accepted = rng.random() < math.exp(-max(0.0, delta) / temperature)
        if accepted:
            rewards[operator] += 2.0 if candidate_score < current_score else 0.5
            current = candidate
            current_unassigned = candidate_unassigned
            current_score = candidate_score
        if candidate_score < best_score:
            best = _copy_bars(candidate)
            best_unassigned = list(candidate_unassigned)
            best_score = candidate_score
            rewards[operator] += 5.0
            improvements[operator] += 1
        temperature = max(0.01, temperature * settings.cooling_rate)
        if settings.adaptive_weights and (iteration + 1) % settings.segment_length == 0:
            for name in settings.operators:
                observed = rewards[name] / uses[name] if uses[name] else 0.1
                weights[name] = (
                    (1.0 - settings.reaction_factor) * weights[name]
                    + settings.reaction_factor * max(0.1, observed)
                )
                rewards[name] = 0.0
                uses[name] = 0

    penalties = _penalties(best, substitution_rules)
    return best, best_unassigned, penalties, {
        "completed_iterations": completed,
        "elapsed_ms": int(round((perf_counter() - started) * 1000.0)),
        "best_score": list(best_score),
        "operator_uses": operator_uses,
        "operator_improvements": improvements,
    }


def _destroy(
    bars: list[Bar],
    unassigned: list[UnassignedDemand],
    operator: str,
    allowance: float,
    fraction: float,
    max_removed: int,
    rng: random.Random,
) -> tuple[list[Bar], list[Demand]]:
    candidate = _copy_bars(bars)
    entries = [
        (bar, demand)
        for bar in candidate
        for demand in bar.demands
    ]
    if not entries:
        return candidate, [item.demand for item in unassigned]
    remove_count = min(max_removed, max(1, math.ceil(len(entries) * fraction)))
    rng.shuffle(entries)
    if operator == "related":
        anchor = entries[0][1]
        entries.sort(
            key=lambda item: (
                item[1].project_code != anchor.project_code,
                item[1].block_name != anchor.block_name,
                item[1].compatibility_key != anchor.compatibility_key,
                abs(item[1].net_length_mm - anchor.net_length_mm),
            )
        )
    elif operator == "purchase":
        entries.sort(key=lambda item: item[0].stock_source_type != "NEW_PURCHASE")
    elif operator == "remnant":
        entries.sort(key=lambda item: item[0].stock_source_type != "CONTROLLED_REMNANT")
    elif operator == "substitution":
        entries.sort(
            key=lambda item: (
                normalize_material(item[0].material)
                == item[1].compatibility_key[0]
            )
        )
    elif operator == "high_remaining":
        entries.sort(
            key=lambda item: -item[0].remaining_length_mm(allowance)
        )
    elif operator != "random":
        raise ValueError("Unknown destroy operator: %s" % operator)
    selected = entries[:remove_count]
    selected_ids = {demand.demand_id for _, demand in selected}
    for bar in candidate:
        bar.demands[:] = [
            demand for demand in bar.demands if demand.demand_id not in selected_ids
        ]
    candidate[:] = [bar for bar in candidate if bar.demands]
    removed = [demand for _, demand in selected]
    removed.extend(item.demand for item in unassigned)
    return candidate, removed


def _repair(
    bars: list[Bar],
    removed: list[Demand],
    stocks: list[StockUnit],
    lengths: list[float],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    forced_material: dict[tuple[str, str, str, str, str], str] | None,
    regret_k: int,
) -> list[UnassignedDemand]:
    used_stock_ids = {
        bar.stock_unit_id for bar in bars if bar.stock_unit_id is not None
    }
    available: dict[str, list[StockUnit]] = defaultdict(list)
    weights: dict[str, float] = {}
    fallback_weight: float | None = None
    for stock in stocks:
        material = stock.group_key[0]
        if stock.stock_unit_id not in used_stock_ids:
            available[material].append(stock)
        if stock.unit_weight_kg_per_m and stock.unit_weight_kg_per_m > 0:
            weights[material] = float(stock.unit_weight_kg_per_m)
            fallback_weight = float(stock.unit_weight_kg_per_m)
    for stock_list in available.values():
        stock_list.sort(
            key=lambda stock: (
                0 if stock.source_type == "CONTROLLED_REMNANT" else 1,
                stock.stock_length_mm,
                stock.stock_unit_id,
            )
        )
    for bar in bars:
        if bar.stock_source_type == "NEW_PURCHASE":
            bar.stock_length_mm = max(lengths)
    pending = list(removed)
    unassigned: list[UnassignedDemand] = []
    next_bar = 1
    used_bar_ids = {bar.bar_id for bar in bars}
    while pending:
        choices = []
        for demand in pending:
            options = _options(
                demand, bars, available, weights, fallback_weight, lengths,
                allowance, rules, forced_material,
            )
            if not options:
                choices.append((float("inf"), demand, None))
                continue
            options.sort(key=lambda item: (item[0], item[1], item[2]))
            kth = options[min(regret_k, len(options)) - 1][0]
            regret = kth - options[0][0]
            choices.append((regret, demand, options[0]))
        _, demand, selected = max(
            choices,
            key=lambda item: (
                item[0], item[1].net_length_mm, item[1].demand_id,
            ),
        )
        pending.remove(demand)
        if selected is None:
            unassigned.append(
                UnassignedDemand(
                    demand, "NO_COMPATIBLE_RESOURCE",
                    "No compatible stock or purchasable length can fit demand.",
                )
            )
            continue
        _, source, _, payload = selected
        if source == "OPEN":
            bar = payload
        elif source == "STOCK":
            stock = payload
            available[stock.group_key[0]].remove(stock)
            while "REPAIR-%06d" % next_bar in used_bar_ids:
                next_bar += 1
            bar_id = "REPAIR-%06d" % next_bar
            used_bar_ids.add(bar_id)
            bar = Bar(
                bar_id=bar_id,
                material=stock.material,
                profile_type=stock.profile_type,
                specification=stock.specification,
                stock_length_mm=stock.stock_length_mm,
                stock_source_type=stock.source_type,
                stock_unit_id=stock.stock_unit_id,
                unit_weight_kg_per_m=stock.unit_weight_kg_per_m,
            )
            next_bar += 1
            bars.append(bar)
        else:
            material, unit_weight = payload
            while "REPAIR-%06d" % next_bar in used_bar_ids:
                next_bar += 1
            bar_id = "REPAIR-%06d" % next_bar
            used_bar_ids.add(bar_id)
            bar = Bar(
                bar_id=bar_id,
                material=material,
                profile_type=demand.profile_type,
                specification=demand.specification,
                stock_length_mm=max(lengths),
                stock_source_type="NEW_PURCHASE",
                unit_weight_kg_per_m=unit_weight,
            )
            next_bar += 1
            bars.append(bar)
        bar.demands.append(demand)
    for bar in bars:
        if bar.stock_source_type == "NEW_PURCHASE":
            used = bar.used_length_mm(allowance)
            bar.stock_length_mm = next(
                length for length in lengths if length + EPSILON >= used
            )
    return unassigned


def _options(
    demand: Demand,
    bars: list[Bar],
    available: dict[str, list[StockUnit]],
    weights: dict[str, float],
    fallback_weight: float | None,
    lengths: list[float],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    forced_material: dict[tuple[str, str, str, str, str], str] | None,
) -> list[tuple[float, str, str, object]]:
    allowed = _allowed_materials(demand, rules)
    if forced_material is not None:
        chosen = forced_material[demand.group_key]
        if chosen not in allowed:
            return []
        allowed = {chosen: allowed[chosen]}
    required = demand.net_length_mm + 2.0 * allowance
    if demand.net_length_mm <= 0 or required > max(lengths) + EPSILON:
        return []
    choices: list[tuple[float, str, str, object]] = []
    for bar in bars:
        if (
            not bar.demands
            or bar.demands[0].project_code != demand.project_code
            or bar.demands[0].block_name != demand.block_name
            or bar.demands[0].compatibility_key[1:]
            != demand.compatibility_key[1:]
            or normalize_material(bar.material) not in allowed
            or not bar.can_fit(demand, allowance)
        ):
            continue
        penalty = allowed[normalize_material(bar.material)]
        if bar.stock_source_type == "NEW_PURCHASE":
            before = _standard_length(bar.used_length_mm(allowance), lengths)
            after = _standard_length(
                bar.used_length_mm(allowance) + demand.net_length_mm + allowance,
                lengths,
            )
            extra = after - before
            unit_weight = float(bar.unit_weight_kg_per_m or fallback_weight or 1.0)
            score = _option_cost(
                extra * unit_weight / 1_000_000.0,
                extra, 0, 0.0, penalty,
            )
        else:
            score = _option_cost(0.0, 0.0, 0, 0.0, penalty)
        choices.append((score, "OPEN", bar.bar_id, bar))
    for material, penalty in allowed.items():
        stock = next(
            (
                item for item in available.get(material, [])
                if item.stock_length_mm + EPSILON >= required
            ),
            None,
        )
        if stock is not None:
            score = _option_cost(
                0.0, 0.0, 0, stock.stock_length_mm, penalty
            )
            choices.append((score, "STOCK", stock.stock_unit_id, stock))
    purchase_material = (
        forced_material[demand.group_key]
        if forced_material is not None else demand.compatibility_key[0]
    )
    purchase_length = _standard_length(required, lengths)
    unit_weight = weights.get(purchase_material, fallback_weight or 1.0)
    score = _option_cost(
        purchase_length * unit_weight / 1_000_000.0,
        purchase_length, 1, purchase_length,
        allowed[purchase_material],
    )
    choices.append(
        (score, "PURCHASE", purchase_material,
         (purchase_material, unit_weight))
    )
    return choices


def _option_cost(
    purchase_weight_t: float,
    purchase_length_mm: float,
    purchase_count: int,
    opened_stock_length_mm: float,
    substitution_penalty: float,
) -> float:
    return (
        purchase_weight_t * 1.0e12
        + purchase_length_mm * 1.0e5
        + purchase_count * 1.0e4
        + opened_stock_length_mm
        + substitution_penalty * 0.01
    )


def _standard_length(used_mm: float, lengths: list[float]) -> float:
    return next(length for length in lengths if length + EPSILON >= used_mm)


def _allowed_materials(
    demand: Demand,
    rules: dict[tuple[str, str, str], float],
) -> dict[str, float]:
    required, profile_type, _ = demand.compatibility_key
    allowed = {required: 0.0}
    for (demand_material, stock_material, rule_profile), penalty in rules.items():
        if demand_material == required and rule_profile == profile_type:
            allowed[stock_material] = float(penalty)
    return allowed


def _penalties(
    bars: list[Bar], rules: dict[tuple[str, str, str], float]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for bar in bars:
        stock_material = normalize_material(bar.material)
        for demand in bar.demands:
            required, profile_type, _ = demand.compatibility_key
            if required != stock_material:
                result[demand.demand_id] = float(
                    rules[(required, stock_material, profile_type)]
                )
    return result


def _score(
    bars: list[Bar],
    unassigned: list[UnassignedDemand],
    allowance: float,
    rules: dict[tuple[str, str, str], float],
    min_reusable_remnant_mm: float = MIN_REUSABLE_REMNANT_MM,
) -> tuple[float, ...]:
    purchases = [bar for bar in bars if bar.stock_source_type == "NEW_PURCHASE"]
    purchase_weight = sum(
        bar.stock_length_mm * float(bar.unit_weight_kg_per_m or 1.0) / 1_000_000.0
        for bar in purchases
    )
    purchase_length = sum(bar.stock_length_mm for bar in purchases)
    remaining = [max(0.0, bar.remaining_length_mm(allowance)) for bar in bars]
    waste = sum(
        value for value in remaining
        if value < min_reusable_remnant_mm - EPSILON
    )
    penalties = _penalties(bars, rules)
    return (
        float(len(unassigned)),
        sum(item.demand.net_length_mm for item in unassigned),
        round(purchase_weight, 9),
        round(purchase_length, 7),
        float(len(purchases)),
        round(sum(bar.stock_length_mm for bar in bars), 7),
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


def _copy_bars(bars: list[Bar]) -> list[Bar]:
    return [replace(bar, demands=list(bar.demands)) for bar in bars]
