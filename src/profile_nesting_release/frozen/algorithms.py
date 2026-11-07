from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterable


EPSILON = 1.0e-7
MAX_EXPERIMENT_DEMAND_LENGTH_MM = 11980.0
MIN_REUSABLE_REMNANT_MM = 1000.0


@dataclass(frozen=True, slots=True)
class Demand:
    demand_id: str
    project_code: str
    block_name: str
    material: str
    profile_type: str
    specification: str
    net_length_mm: float

    @property
    def compatibility_key(self) -> tuple[str, str, str]:
        return (
            normalize_material(self.material),
            normalize_profile_type(self.profile_type),
            normalize_specification(self.specification),
        )

    @property
    def group_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.project_code.strip().upper(),
            self.block_name.strip().upper(),
            *self.compatibility_key,
        )


@dataclass(frozen=True, slots=True)
class StockUnit:
    stock_unit_id: str
    stock_id: str
    material: str
    profile_type: str
    specification: str
    stock_length_mm: float
    source_type: str = "PURCHASE"
    unit_weight_kg_per_m: float | None = None

    @property
    def group_key(self) -> tuple[str, str, str]:
        return (
            normalize_material(self.material),
            normalize_profile_type(self.profile_type),
            normalize_specification(self.specification),
        )


@dataclass(slots=True)
class Bar:
    bar_id: str
    material: str
    profile_type: str
    specification: str
    stock_length_mm: float
    stock_source_type: str = "STANDARD"
    stock_unit_id: str | None = None
    unit_weight_kg_per_m: float | None = None
    demands: list[Demand] = field(default_factory=list)

    @property
    def net_length_mm(self) -> float:
        return sum(item.net_length_mm for item in self.demands)

    def allowance_length_mm(self, boundary_allowance_mm: float) -> float:
        if not self.demands:
            return 0.0
        return (len(self.demands) + 1) * boundary_allowance_mm

    def used_length_mm(self, boundary_allowance_mm: float) -> float:
        return self.net_length_mm + self.allowance_length_mm(boundary_allowance_mm)

    def remaining_length_mm(self, boundary_allowance_mm: float) -> float:
        return self.stock_length_mm - self.used_length_mm(boundary_allowance_mm)

    def can_fit(self, demand: Demand, boundary_allowance_mm: float) -> bool:
        new_used = (
            self.net_length_mm
            + demand.net_length_mm
            + (len(self.demands) + 2) * boundary_allowance_mm
        )
        return new_used <= self.stock_length_mm + EPSILON


@dataclass(frozen=True, slots=True)
class UnassignedDemand:
    demand: Demand
    reason_code: str
    reason: str


@dataclass(slots=True)
class NestingResult:
    algorithm: str
    boundary_allowance_mm: float
    bars: list[Bar]
    unassigned: list[UnassignedDemand]
    input_count: int
    elapsed_ms: int
    solver_status: str | None = None
    mip_gap: float | None = None
    solver_objective: float | None = None
    substitution_penalty_by_demand: dict[str, float] = field(default_factory=dict)

    @property
    def assigned_count(self) -> int:
        return sum(len(bar.demands) for bar in self.bars)

    @property
    def total_net_length_mm(self) -> float:
        return sum(bar.net_length_mm for bar in self.bars)

    @property
    def total_stock_length_mm(self) -> float:
        return sum(bar.stock_length_mm for bar in self.bars)

    @property
    def total_used_length_mm(self) -> float:
        return sum(bar.used_length_mm(self.boundary_allowance_mm) for bar in self.bars)

    @property
    def total_waste_length_mm(self) -> float:
        return sum(
            remaining
            for remaining in self._remaining_lengths()
            if remaining < MIN_REUSABLE_REMNANT_MM - EPSILON
        )

    @property
    def total_remaining_length_mm(self) -> float:
        return sum(self._remaining_lengths())

    @property
    def total_reusable_remnant_length_mm(self) -> float:
        return sum(
            remaining
            for remaining in self._remaining_lengths()
            if remaining >= MIN_REUSABLE_REMNANT_MM - EPSILON
        )

    def _remaining_lengths(self) -> list[float]:
        return [
            max(0.0, bar.remaining_length_mm(self.boundary_allowance_mm))
            for bar in self.bars
        ]

    @property
    def utilization(self) -> float:
        stock = self.total_stock_length_mm
        return self.total_net_length_mm / stock if stock > 0 else 0.0

    @property
    def additional_purchase_count(self) -> int:
        return sum(bar.stock_source_type == "NEW_PURCHASE" for bar in self.bars)

    @property
    def additional_purchase_length_mm(self) -> float:
        return sum(
            bar.stock_length_mm
            for bar in self.bars
            if bar.stock_source_type == "NEW_PURCHASE"
        )

    @property
    def additional_purchase_weight_t(self) -> float:
        return sum(
            bar.stock_length_mm
            / 1000.0
            * float(bar.unit_weight_kg_per_m or 0.0)
            / 1000.0
            for bar in self.bars
            if bar.stock_source_type == "NEW_PURCHASE"
        )

    @property
    def controlled_remnant_used_count(self) -> int:
        return sum(bar.stock_source_type == "CONTROLLED_REMNANT" for bar in self.bars)

    @property
    def controlled_remnant_used_length_mm(self) -> float:
        return sum(
            bar.stock_length_mm
            for bar in self.bars
            if bar.stock_source_type == "CONTROLLED_REMNANT"
        )

    @property
    def substitution_count(self) -> int:
        return sum(
            normalize_material(demand.material) != normalize_material(bar.material)
            for bar in self.bars
            for demand in bar.demands
        )

    @property
    def substitution_length_mm(self) -> float:
        return sum(
            demand.net_length_mm
            for bar in self.bars
            for demand in bar.demands
            if normalize_material(demand.material) != normalize_material(bar.material)
        )

    @property
    def substitution_penalty(self) -> float:
        return sum(float(value) for value in self.substitution_penalty_by_demand.values())


def solve(
    demands: Iterable[Demand],
    algorithm: str,
    standard_lengths_mm: Iterable[float],
    boundary_allowance_mm: float,
    stock_units: Iterable[StockUnit] | None = None,
    *,
    random_seed: int = 0,
    iteration_limit: int = 500,
    time_limit_seconds: float = 120.0,
) -> NestingResult:
    name = algorithm.strip().upper()
    demand_list = list(demands)
    if boundary_allowance_mm < 0:
        raise ValueError("Boundary allowance must be non-negative.")
    if name not in (
        "FFD",
        "BFD",
        "RESOURCE_BFD",
        "RESOURCE_BFD_PURCHASE",
        "RESOURCE_ALNS_PURCHASE",
        "RESOURCE_PURCHASE_MILP",
        "GA",
        "ALNS",
        "ALNS_MILP",
        "MILP",
    ):
        raise ValueError("Unsupported algorithm: %s" % algorithm)

    if name == "MILP":
        from .exact import solve_milp

        return solve_milp(
            demand_list,
            list(standard_lengths_mm),
            boundary_allowance_mm,
            time_limit_seconds=300.0,
            threads=1,
        )

    if name == "RESOURCE_PURCHASE_MILP":
        from .finite_exact import solve_resource_purchase_milp

        return solve_resource_purchase_milp(
            demand_list,
            list(stock_units or []),
            list(standard_lengths_mm),
            boundary_allowance_mm,
            time_limit_seconds=300.0,
            threads=1,
        )

    if name in ("GA", "ALNS", "ALNS_MILP"):
        from .metaheuristics import MetaheuristicConfig, solve_alns, solve_genetic

        lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
        if not lengths:
            raise ValueError("Metaheuristics require positive standard stock lengths.")
        config = MetaheuristicConfig(
            seed=random_seed,
            iterations=iteration_limit,
            total_time_limit_seconds=time_limit_seconds,
        )
        if name == "GA":
            return solve_genetic(demand_list, lengths, boundary_allowance_mm, config)
        return solve_alns(
            demand_list,
            lengths,
            boundary_allowance_mm,
            config,
            with_milp_repair=name == "ALNS_MILP",
        )

    if name == "RESOURCE_ALNS_PURCHASE":
        from .resource_alns import solve_resource_alns_purchase
        from .resource_alns import ResourceAlnsConfig

        return solve_resource_alns_purchase(
            demand_list,
            list(stock_units or []),
            list(standard_lengths_mm),
            boundary_allowance_mm,
            ResourceAlnsConfig(
                iterations_per_shortage_group=iteration_limit,
                seed=random_seed,
            ),
        )

    started = perf_counter()
    if name == "RESOURCE_BFD":
        bars, unassigned = _solve_resource_bfd(
            demand_list, list(stock_units or []), boundary_allowance_mm
        )
    elif name == "RESOURCE_BFD_PURCHASE":
        lengths = sorted(
            {float(value) for value in standard_lengths_mm if float(value) > 0}
        )
        if not lengths:
            raise ValueError(
                "RESOURCE_BFD_PURCHASE requires positive additional-purchase lengths."
            )
        bars, unassigned = _solve_resource_bfd_purchase(
            demand_list,
            list(stock_units or []),
            lengths,
            boundary_allowance_mm,
        )
    else:
        lengths = sorted({float(value) for value in standard_lengths_mm if float(value) > 0})
        if not lengths:
            raise ValueError("At least one positive standard stock length is required.")
        bars, unassigned = _solve_unlimited(
            demand_list, name, lengths, boundary_allowance_mm
        )

    elapsed_ms = int(round((perf_counter() - started) * 1000.0))
    return NestingResult(
        algorithm=name,
        boundary_allowance_mm=boundary_allowance_mm,
        bars=bars,
        unassigned=unassigned,
        input_count=len(demand_list),
        elapsed_ms=elapsed_ms,
        solver_status="HEURISTIC",
    )


def _solve_unlimited(
    demands: list[Demand],
    algorithm: str,
    standard_lengths: list[float],
    allowance: float,
) -> tuple[list[Bar], list[UnassignedDemand]]:
    maximum = max(standard_lengths)
    groups = _group_demands(demands)
    result_bars: list[Bar] = []
    unassigned: list[UnassignedDemand] = []
    next_bar = 1

    for key in sorted(groups):
        group = sorted(groups[key], key=lambda item: (-item.net_length_mm, item.demand_id))
        open_bars: list[Bar] = []
        for demand in group:
            if demand.net_length_mm <= 0:
                unassigned.append(
                    UnassignedDemand(demand, "INVALID_LENGTH", "Net length must be positive.")
                )
                continue
            required_empty = demand.net_length_mm + 2.0 * allowance
            if required_empty > maximum + EPSILON:
                unassigned.append(
                    UnassignedDemand(
                        demand,
                        "NO_STOCK_LENGTH",
                        "Demand plus end allowances exceeds the longest standard stock.",
                    )
                )
                continue

            candidates = [bar for bar in open_bars if bar.can_fit(demand, allowance)]
            selected: Bar | None = None
            if candidates:
                if algorithm == "FFD":
                    selected = candidates[0]
                else:
                    selected = min(
                        candidates,
                        key=lambda bar: (
                            bar.remaining_length_mm(allowance)
                            - demand.net_length_mm
                            - allowance,
                            bar.bar_id,
                        ),
                    )
            if selected is None:
                selected = Bar(
                    bar_id="BAR-%06d" % next_bar,
                    material=demand.material,
                    profile_type=demand.profile_type,
                    specification=demand.specification,
                    stock_length_mm=maximum,
                )
                next_bar += 1
                open_bars.append(selected)
                result_bars.append(selected)
            selected.demands.append(demand)

        for bar in open_bars:
            used = bar.used_length_mm(allowance)
            bar.stock_length_mm = next(
                length for length in standard_lengths if length + EPSILON >= used
            )
    return result_bars, unassigned


def _solve_resource_bfd(
    demands: list[Demand], stock_units: list[StockUnit], allowance: float
) -> tuple[list[Bar], list[UnassignedDemand]]:
    grouped_demands = _group_demands(demands)
    grouped_stock: dict[tuple[str, str, str], list[StockUnit]] = {}
    for stock in stock_units:
        if stock.stock_length_mm > 0:
            grouped_stock.setdefault(stock.group_key, []).append(stock)
    for values in grouped_stock.values():
        values.sort(key=lambda item: (item.stock_length_mm, item.stock_unit_id))

    result_bars: list[Bar] = []
    unassigned: list[UnassignedDemand] = []
    next_bar = 1
    for key in sorted(grouped_demands):
        group = sorted(
            grouped_demands[key], key=lambda item: (-item.net_length_mm, item.demand_id)
        )
        compatibility_key = group[0].compatibility_key
        available = grouped_stock.setdefault(compatibility_key, [])
        open_bars: list[Bar] = []
        for demand in group:
            if demand.net_length_mm <= 0:
                unassigned.append(
                    UnassignedDemand(demand, "INVALID_LENGTH", "Net length must be positive.")
                )
                continue
            candidates = [bar for bar in open_bars if bar.can_fit(demand, allowance)]
            if candidates:
                selected = min(
                    candidates,
                    key=lambda bar: (
                        bar.remaining_length_mm(allowance)
                        - demand.net_length_mm
                        - allowance,
                        bar.bar_id,
                    ),
                )
                selected.demands.append(demand)
                continue

            required = demand.net_length_mm + 2.0 * allowance
            stock_index = next(
                (
                    index
                    for index, stock in enumerate(available)
                    if stock.stock_length_mm + EPSILON >= required
                ),
                None,
            )
            if stock_index is None:
                unassigned.append(
                    UnassignedDemand(
                        demand,
                        "NO_COMPATIBLE_STOCK",
                        "No remaining exact-material/profile/specification stock can fit demand.",
                    )
                )
                continue
            stock = available.pop(stock_index)
            bar = Bar(
                bar_id="BAR-%06d" % next_bar,
                stock_unit_id=stock.stock_unit_id,
                stock_source_type=stock.source_type,
                material=stock.material,
                profile_type=stock.profile_type,
                specification=stock.specification,
                stock_length_mm=stock.stock_length_mm,
                unit_weight_kg_per_m=stock.unit_weight_kg_per_m,
                demands=[demand],
            )
            next_bar += 1
            open_bars.append(bar)
            result_bars.append(bar)
    return result_bars, unassigned


def _solve_resource_bfd_purchase(
    demands: list[Demand],
    stock_units: list[StockUnit],
    standard_lengths: list[float],
    allowance: float,
    group_order: list[tuple[str, str, str, str, str]] | None = None,
) -> tuple[list[Bar], list[UnassignedDemand]]:
    """BFD baseline with finite initial stock and unlimited additional purchase."""

    grouped_demands = _group_demands(demands)
    grouped_stock: dict[tuple[str, str, str], list[StockUnit]] = {}
    unit_weights: dict[tuple[str, str, str], float] = {}
    for stock in stock_units:
        if stock.stock_length_mm <= 0:
            continue
        grouped_stock.setdefault(stock.group_key, []).append(stock)
        if stock.unit_weight_kg_per_m and stock.unit_weight_kg_per_m > 0:
            unit_weights[stock.group_key] = stock.unit_weight_kg_per_m
    for values in grouped_stock.values():
        values.sort(key=lambda item: (item.stock_length_mm, item.stock_unit_id))

    maximum = max(standard_lengths)
    result_bars: list[Bar] = []
    unassigned: list[UnassignedDemand] = []
    next_bar = 1
    ordered_keys = _validated_group_order(grouped_demands, group_order)
    for key in ordered_keys:
        group = sorted(
            grouped_demands[key], key=lambda item: (-item.net_length_mm, item.demand_id)
        )
        compatibility_key = group[0].compatibility_key
        available = grouped_stock.setdefault(compatibility_key, [])
        open_bars: list[Bar] = []
        new_bars: list[Bar] = []
        for demand in group:
            candidates = [bar for bar in open_bars if bar.can_fit(demand, allowance)]
            if candidates:
                selected = min(
                    candidates,
                    key=lambda bar: (
                        bar.remaining_length_mm(allowance)
                        - demand.net_length_mm
                        - allowance,
                        bar.bar_id,
                    ),
                )
                selected.demands.append(demand)
                continue

            required = demand.net_length_mm + 2.0 * allowance
            stock_index = next(
                (
                    index
                    for index, stock in enumerate(available)
                    if stock.stock_length_mm + EPSILON >= required
                ),
                None,
            )
            if stock_index is not None:
                stock = available.pop(stock_index)
                bar = Bar(
                    bar_id="BAR-%06d" % next_bar,
                    stock_unit_id=stock.stock_unit_id,
                    stock_source_type=stock.source_type,
                    material=stock.material,
                    profile_type=stock.profile_type,
                    specification=stock.specification,
                    stock_length_mm=stock.stock_length_mm,
                    unit_weight_kg_per_m=stock.unit_weight_kg_per_m,
                    demands=[demand],
                )
            elif required <= maximum + EPSILON:
                bar = Bar(
                    bar_id="BAR-%06d" % next_bar,
                    stock_source_type="NEW_PURCHASE",
                    material=demand.material,
                    profile_type=demand.profile_type,
                    specification=demand.specification,
                    stock_length_mm=maximum,
                    unit_weight_kg_per_m=unit_weights.get(compatibility_key),
                    demands=[demand],
                )
                new_bars.append(bar)
            else:
                unassigned.append(
                    UnassignedDemand(
                        demand,
                        "NO_PURCHASABLE_LENGTH",
                        "Demand exceeds the longest additional-purchase length.",
                    )
                )
                continue
            next_bar += 1
            open_bars.append(bar)
            result_bars.append(bar)

        for bar in new_bars:
            used = bar.used_length_mm(allowance)
            bar.stock_length_mm = next(
                length for length in standard_lengths if length + EPSILON >= used
            )
    return result_bars, unassigned


def _validated_group_order(
    grouped_demands: dict[tuple[str, str, str, str, str], list[Demand]],
    group_order: list[tuple[str, str, str, str, str]] | None,
) -> list[tuple[str, str, str, str, str]]:
    if group_order is None:
        return sorted(grouped_demands)
    if len(group_order) != len(grouped_demands) or set(group_order) != set(
        grouped_demands
    ):
        raise ValueError("Group order must contain every demand group exactly once.")
    return list(group_order)


def _group_demands(
    demands: Iterable[Demand],
) -> dict[tuple[str, str, str, str, str], list[Demand]]:
    groups: dict[tuple[str, str, str, str, str], list[Demand]] = {}
    for demand in demands:
        groups.setdefault(demand.group_key, []).append(demand)
    return groups


def normalize_material(value: str) -> str:
    text = _compact(value).upper()
    for prefix in ("ABS-", "ABS/", "ABS_"):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def normalize_profile_type(value: str) -> str:
    return _compact(value).upper()


def normalize_specification(value: str) -> str:
    text = _compact(value).upper().replace("×", "*").replace("＊", "*").replace("X", "*")
    if text.startswith("HP"):
        text = text[2:]
    parts = [part for part in text.split("*") if part]
    if not parts:
        return text
    normalized: list[str] = []
    for part in parts:
        try:
            number = float(part)
        except ValueError:
            return text
        normalized.append(("%.3f" % number).rstrip("0").rstrip("."))
    return "*".join(normalized)


def _compact(value: str) -> str:
    return "".join((value or "").split())
