from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import random
from time import perf_counter

from .algorithms import Bar, Demand, EPSILON, NestingResult, UnassignedDemand, _group_demands


@dataclass(frozen=True, slots=True)
class MetaheuristicConfig:
    seed: int = 0
    iterations: int = 100
    population_size: int = 24
    mutation_probability: float = 0.25
    alns_cooling_rate: float = 0.995
    milp_neighborhood_size: int = 30
    milp_seconds_per_group: float = 5.0
    milp_max_groups: int = 5
    total_time_limit_seconds: float = 120.0


def solve_genetic(
    demands: list[Demand],
    lengths: list[float],
    allowance: float,
    config: MetaheuristicConfig,
) -> NestingResult:
    started = perf_counter()
    rng = random.Random(config.seed)
    all_bars: list[Bar] = []
    unassigned: list[UnassignedDemand] = []
    evaluations = 0
    for key, values in sorted(_group_demands(demands).items()):
        valid, invalid = _valid_group(values, max(lengths), allowance)
        unassigned.extend(invalid)
        if not valid:
            continue
        best_bars, group_evaluations = _ga_group(valid, lengths, allowance, config, rng)
        evaluations += group_evaluations
        all_bars.extend(best_bars)
    _renumber(all_bars)
    return NestingResult(
        "GA",
        allowance,
        all_bars,
        unassigned,
        len(demands),
        int(round((perf_counter() - started) * 1000.0)),
        "HEURISTIC_GA_%d_EVALUATIONS" % evaluations,
        solver_objective=_score(all_bars, allowance)[0],
    )


def solve_alns(
    demands: list[Demand],
    lengths: list[float],
    allowance: float,
    config: MetaheuristicConfig,
    *,
    with_milp_repair: bool = False,
) -> NestingResult:
    started = perf_counter()
    rng = random.Random(config.seed)
    all_bars: list[Bar] = []
    unassigned: list[UnassignedDemand] = []
    evaluations = 0
    repaired = 0
    optimal_repairs = 0
    grouped = sorted(_group_demands(demands).items())
    repair_keys = {
        key
        for key, values in sorted(
            (
                (key, values)
                for key, values in grouped
                if 1 < len(values) <= config.milp_neighborhood_size
            ),
            key=lambda item: (-len(item[1]), item[0]),
        )[: config.milp_max_groups]
    }
    for key, values in grouped:
        valid, invalid = _valid_group(values, max(lengths), allowance)
        unassigned.extend(invalid)
        if not valid:
            continue
        bars, group_evaluations = _alns_group(valid, lengths, allowance, config, rng)
        evaluations += group_evaluations
        remaining_seconds = config.total_time_limit_seconds - (perf_counter() - started)
        if with_milp_repair and key in repair_keys and remaining_seconds > 0.05:
            repaired += 1
            try:
                from .exact import _solve_group

                exact_bars, status, _, _ = _solve_group(
                    sorted(valid, key=lambda item: (-item.net_length_mm, item.demand_id)),
                    lengths,
                    allowance,
                    min(config.milp_seconds_per_group, remaining_seconds),
                    1,
                )
                if status == "OPTIMAL":
                    optimal_repairs += 1
                if _score(exact_bars, allowance) < _score(bars, allowance):
                    bars = exact_bars
            except (RuntimeError, TimeoutError):
                pass
        all_bars.extend(bars)
    _renumber(all_bars)
    algorithm = "ALNS_MILP" if with_milp_repair else "ALNS"
    status = "HEURISTIC_ALNS_%d_EVALUATIONS" % evaluations
    if with_milp_repair:
        status += "_%d_OF_%d_LOCAL_GROUPS_OPTIMAL" % (optimal_repairs, repaired)
    return NestingResult(
        algorithm,
        allowance,
        all_bars,
        unassigned,
        len(demands),
        int(round((perf_counter() - started) * 1000.0)),
        status,
        solver_objective=_score(all_bars, allowance)[0],
    )


def _ga_group(
    demands: list[Demand],
    lengths: list[float],
    allowance: float,
    config: MetaheuristicConfig,
    rng: random.Random,
) -> tuple[list[Bar], int]:
    count = len(demands)
    base = sorted(range(count), key=lambda index: (-demands[index].net_length_mm, demands[index].demand_id))
    ascending = list(reversed(base))
    population = [base, ascending]
    while len(population) < max(4, config.population_size):
        individual = list(base)
        rng.shuffle(individual)
        population.append(individual)
    evaluations = 0

    def evaluate(individual: list[int]) -> tuple[tuple[float, ...], list[Bar]]:
        nonlocal evaluations
        bars = _decode_order([demands[index] for index in individual], lengths, allowance)
        evaluations += 1
        return _score(bars, allowance), bars

    scored = [(evaluate(individual), individual) for individual in population]
    for _ in range(max(0, config.iterations)):
        scored.sort(key=lambda item: item[0][0])
        next_population = [list(scored[0][1]), list(scored[1][1])]
        while len(next_population) < len(population):
            parent1 = _tournament(scored, rng)
            parent2 = _tournament(scored, rng)
            child = _order_crossover(parent1, parent2, rng)
            if rng.random() < config.mutation_probability:
                _mutate_permutation(child, rng)
            next_population.append(child)
        scored = [(evaluate(individual), individual) for individual in next_population]
    best = min(scored, key=lambda item: item[0][0])
    return best[0][1], evaluations


def _alns_group(
    demands: list[Demand],
    lengths: list[float],
    allowance: float,
    config: MetaheuristicConfig,
    rng: random.Random,
) -> tuple[list[Bar], int]:
    current = sorted(range(len(demands)), key=lambda index: (-demands[index].net_length_mm, demands[index].demand_id))
    current_bars = _decode_order([demands[index] for index in current], lengths, allowance)
    current_score = _score(current_bars, allowance)
    best = list(current)
    best_bars = current_bars
    best_score = current_score
    evaluations = 1
    operators = ("swap", "relocate", "reverse", "shuffle", "longest_first")
    weights = {name: 1.0 for name in operators}
    reward = {name: 0.0 for name in operators}
    uses = {name: 0 for name in operators}
    temperature = max(1.0, current_score[0] * 0.01)
    for iteration in range(max(0, config.iterations)):
        operator = rng.choices(operators, [weights[name] for name in operators], k=1)[0]
        candidate = _alns_mutation(current, demands, operator, rng)
        bars = _decode_order([demands[index] for index in candidate], lengths, allowance)
        score = _score(bars, allowance)
        evaluations += 1
        uses[operator] += 1
        accepted = score <= current_score
        if not accepted:
            delta = _scalar(score) - _scalar(current_score)
            accepted = rng.random() < math.exp(-max(0.0, delta) / temperature)
        if accepted:
            if score < current_score:
                reward[operator] += 2.0
            else:
                reward[operator] += 0.5
            current, current_bars, current_score = candidate, bars, score
        if score < best_score:
            best, best_bars, best_score = list(candidate), bars, score
            reward[operator] += 5.0
        temperature = max(0.01, temperature * config.alns_cooling_rate)
        if (iteration + 1) % 25 == 0:
            for name in operators:
                observed = reward[name] / uses[name] if uses[name] else 0.1
                weights[name] = 0.8 * weights[name] + 0.2 * max(0.1, observed)
                reward[name] = 0.0
                uses[name] = 0
    return best_bars, evaluations


def _decode_order(demands: list[Demand], lengths: list[float], allowance: float) -> list[Bar]:
    maximum = max(lengths)
    bars: list[Bar] = []
    for demand in demands:
        candidates = [bar for bar in bars if bar.can_fit(demand, allowance)]
        if candidates:
            selected = min(
                candidates,
                key=lambda bar: (
                    bar.remaining_length_mm(allowance) - demand.net_length_mm - allowance,
                    bar.bar_id,
                ),
            )
        else:
            selected = Bar(
                bar_id="TMP-%06d" % (len(bars) + 1),
                material=demand.material,
                profile_type=demand.profile_type,
                specification=demand.specification,
                stock_length_mm=maximum,
            )
            bars.append(selected)
        selected.demands.append(demand)
    for bar in bars:
        used = bar.used_length_mm(allowance)
        bar.stock_length_mm = next(length for length in lengths if length + EPSILON >= used)
    return bars


def _valid_group(
    demands: list[Demand], maximum: float, allowance: float
) -> tuple[list[Demand], list[UnassignedDemand]]:
    valid = []
    invalid = []
    for demand in demands:
        if demand.net_length_mm <= 0:
            invalid.append(UnassignedDemand(demand, "INVALID_LENGTH", "Net length must be positive."))
        elif demand.net_length_mm + 2.0 * allowance > maximum + EPSILON:
            invalid.append(
                UnassignedDemand(
                    demand, "NO_STOCK_LENGTH",
                    "Demand plus end allowances exceeds the longest standard stock.",
                )
            )
        else:
            valid.append(demand)
    return valid, invalid


def _score(bars: list[Bar], allowance: float) -> tuple[float, ...]:
    total_stock = sum(bar.stock_length_mm for bar in bars)
    remaining = [max(0.0, bar.remaining_length_mm(allowance)) for bar in bars]
    waste = sum(value for value in remaining if value < 1000.0 - EPSILON)
    return (total_stock, waste, sum(remaining), float(len(bars)))


def _scalar(score: tuple[float, ...]) -> float:
    return score[0] * 1.0e6 + score[1] * 100.0 + score[2] + score[3]


def _tournament(
    scored: list[tuple[tuple[tuple[float, ...], list[Bar]], list[int]]],
    rng: random.Random,
) -> list[int]:
    contenders = rng.sample(scored, min(3, len(scored)))
    return list(min(contenders, key=lambda item: item[0][0])[1])


def _order_crossover(parent1: list[int], parent2: list[int], rng: random.Random) -> list[int]:
    if len(parent1) < 2:
        return list(parent1)
    left, right = sorted(rng.sample(range(len(parent1)), 2))
    child: list[int | None] = [None] * len(parent1)
    child[left : right + 1] = parent1[left : right + 1]
    remaining = [item for item in parent2 if item not in child]
    positions = [index for index, item in enumerate(child) if item is None]
    for position, item in zip(positions, remaining):
        child[position] = item
    return [int(item) for item in child]


def _mutate_permutation(values: list[int], rng: random.Random) -> None:
    if len(values) < 2:
        return
    left, right = sorted(rng.sample(range(len(values)), 2))
    if rng.random() < 0.5:
        values[left], values[right] = values[right], values[left]
    else:
        values[left : right + 1] = reversed(values[left : right + 1])


def _alns_mutation(
    order: list[int], demands: list[Demand], operator: str, rng: random.Random
) -> list[int]:
    candidate = list(order)
    if len(candidate) < 2:
        return candidate
    left, right = sorted(rng.sample(range(len(candidate)), 2))
    if operator == "swap":
        candidate[left], candidate[right] = candidate[right], candidate[left]
    elif operator == "relocate":
        value = candidate.pop(left)
        candidate.insert(right, value)
    elif operator == "reverse":
        candidate[left : right + 1] = reversed(candidate[left : right + 1])
    elif operator == "shuffle":
        segment = candidate[left : right + 1]
        rng.shuffle(segment)
        candidate[left : right + 1] = segment
    elif operator == "longest_first":
        candidate.sort(key=lambda index: (-demands[index].net_length_mm, demands[index].demand_id))
    else:
        raise ValueError("Unknown ALNS operator: %s" % operator)
    return candidate


def _renumber(bars: list[Bar]) -> None:
    for index, bar in enumerate(bars, start=1):
        bar.bar_id = "BAR-%06d" % index
