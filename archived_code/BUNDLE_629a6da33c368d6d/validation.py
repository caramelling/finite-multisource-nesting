from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from typing import Iterable

from .algorithms import Bar, Demand, EPSILON, NestingResult, StockUnit


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    demand_id: str | None = None
    bar_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    is_valid: bool
    input_count: int
    assigned_count: int
    unassigned_count: int
    bar_count: int
    issue_count: int
    issues: tuple[ValidationIssue, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "is_valid": self.is_valid,
                "input_count": self.input_count,
                "assigned_count": self.assigned_count,
                "unassigned_count": self.unassigned_count,
                "bar_count": self.bar_count,
                "issue_count": self.issue_count,
                "issues": [asdict(issue) for issue in self.issues],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class ResultValidationError(ValueError):
    def __init__(self, report: ValidationReport):
        self.report = report
        summary = "; ".join(
            "%s: %s" % (issue.code, issue.message) for issue in report.issues[:5]
        )
        super().__init__(
            "Nesting result failed feasibility validation (%d issue(s)): %s"
            % (report.issue_count, summary)
        )


def validate_result(
    demands: Iterable[Demand],
    result: NestingResult,
    *,
    stock_units: Iterable[StockUnit] = (),
    standard_lengths_mm: Iterable[float] = (),
    substitution_rules: dict[tuple[str, str, str], float] | None = None,
    require_purchase_weight: bool = False,
) -> ValidationReport:
    """Validate assignment, inventory, purchase and approved scenario rules."""

    demand_list = list(demands)
    stock_list = list(stock_units)
    standard_lengths = {
        round(float(value), 7)
        for value in standard_lengths_mm
        if float(value) > 0
    }
    issues: list[ValidationIssue] = []

    input_counts = Counter(item.demand_id for item in demand_list)
    for demand_id, count in input_counts.items():
        if count != 1:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_INPUT_ID",
                    "Input demand id occurs %d times." % count,
                    demand_id=demand_id,
                )
            )
    input_by_id = {item.demand_id: item for item in demand_list}

    stock_counts = Counter(item.stock_unit_id for item in stock_list)
    for stock_id, count in stock_counts.items():
        if count != 1:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_STOCK_ID",
                    "Input stock unit id occurs %d times." % count,
                    bar_id=stock_id,
                )
            )
    stock_by_id = {item.stock_unit_id: item for item in stock_list}
    used_stock_ids: Counter[str] = Counter()
    assigned_ids: list[str] = []

    bar_ids = Counter(bar.bar_id for bar in result.bars)
    for bar_id, count in bar_ids.items():
        if count != 1:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_BAR_ID",
                    "Result bar id occurs %d times." % count,
                    bar_id=bar_id,
                )
            )

    for bar in result.bars:
        _validate_bar(
            bar,
            result.boundary_allowance_mm,
            input_by_id,
            stock_by_id,
            used_stock_ids,
            standard_lengths,
            assigned_ids,
            issues,
            substitution_rules or {},
            require_purchase_weight,
        )

    expected_penalties: dict[str, float] = {}
    for bar in result.bars:
        stock_material = bar_group_key(bar)[0]
        for demand in bar.demands:
            required_material, profile_type, _ = demand.compatibility_key
            if required_material != stock_material:
                rule_key = (required_material, stock_material, profile_type)
                if rule_key in (substitution_rules or {}):
                    expected_penalties[demand.demand_id] = float(
                        (substitution_rules or {})[rule_key]
                    )
    for demand_id, expected in expected_penalties.items():
        actual = result.substitution_penalty_by_demand.get(demand_id)
        if actual is None or abs(float(actual) - expected) > EPSILON:
            issues.append(
                ValidationIssue(
                    "SUBSTITUTION_PENALTY_MISMATCH",
                    "Recorded penalty does not match the frozen substitution rule.",
                    demand_id=demand_id,
                )
            )
    for demand_id in result.substitution_penalty_by_demand:
        if demand_id not in expected_penalties:
            issues.append(
                ValidationIssue(
                    "UNEXPECTED_SUBSTITUTION_PENALTY",
                    "A penalty is recorded for an exact-material or unknown assignment.",
                    demand_id=demand_id,
                )
            )

    for stock_id, count in used_stock_ids.items():
        if count > 1:
            issues.append(
                ValidationIssue(
                    "STOCK_REUSED",
                    "Finite stock unit is used by %d bars." % count,
                    bar_id=stock_id,
                )
            )

    unassigned_ids = [item.demand.demand_id for item in result.unassigned]
    outcome_counts = Counter(assigned_ids + unassigned_ids)
    for demand_id, count in outcome_counts.items():
        if demand_id not in input_by_id:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_DEMAND",
                    "Result contains a demand that is not in the input.",
                    demand_id=demand_id,
                )
            )
        elif count != 1:
            issues.append(
                ValidationIssue(
                    "DEMAND_NOT_EXACTLY_ONCE",
                    "Demand occurs %d times across assigned and unassigned outputs." % count,
                    demand_id=demand_id,
                )
            )
    for demand_id in input_by_id:
        if outcome_counts[demand_id] == 0:
            issues.append(
                ValidationIssue(
                    "MISSING_DEMAND",
                    "Input demand is absent from both assigned and unassigned outputs.",
                    demand_id=demand_id,
                )
            )

    if result.input_count != len(demand_list):
        issues.append(
            ValidationIssue(
                "INPUT_COUNT_MISMATCH",
                "Result input_count=%d but actual input count=%d."
                % (result.input_count, len(demand_list)),
            )
        )
    if result.assigned_count != len(assigned_ids):
        issues.append(
            ValidationIssue(
                "ASSIGNED_COUNT_MISMATCH",
                "Result assigned count is internally inconsistent.",
            )
        )

    return ValidationReport(
        is_valid=not issues,
        input_count=len(demand_list),
        assigned_count=len(assigned_ids),
        unassigned_count=len(unassigned_ids),
        bar_count=len(result.bars),
        issue_count=len(issues),
        issues=tuple(issues),
    )


def assert_valid_result(
    demands: Iterable[Demand],
    result: NestingResult,
    *,
    stock_units: Iterable[StockUnit] = (),
    standard_lengths_mm: Iterable[float] = (),
    substitution_rules: dict[tuple[str, str, str], float] | None = None,
    require_purchase_weight: bool = False,
) -> ValidationReport:
    report = validate_result(
        demands,
        result,
        stock_units=stock_units,
        standard_lengths_mm=standard_lengths_mm,
        substitution_rules=substitution_rules,
        require_purchase_weight=require_purchase_weight,
    )
    if not report.is_valid:
        raise ResultValidationError(report)
    return report


def _validate_bar(
    bar: Bar,
    allowance: float,
    input_by_id: dict[str, Demand],
    stock_by_id: dict[str, StockUnit],
    used_stock_ids: Counter[str],
    standard_lengths: set[float],
    assigned_ids: list[str],
    issues: list[ValidationIssue],
    substitution_rules: dict[tuple[str, str, str], float],
    require_purchase_weight: bool,
) -> None:
    if not bar.demands:
        issues.append(
            ValidationIssue("EMPTY_BAR", "A result bar has no assigned demand.", bar_id=bar.bar_id)
        )
        return
    if bar.stock_length_mm <= 0:
        issues.append(
            ValidationIssue(
                "INVALID_STOCK_LENGTH",
                "Bar stock length must be positive.",
                bar_id=bar.bar_id,
            )
        )
    used_length = sum(item.net_length_mm for item in bar.demands) + (
        len(bar.demands) + 1
    ) * allowance
    if used_length > bar.stock_length_mm + EPSILON:
        issues.append(
            ValidationIssue(
                "BAR_OVER_CAPACITY",
                "Used %.7f mm exceeds stock length %.7f mm."
                % (used_length, bar.stock_length_mm),
                bar_id=bar.bar_id,
            )
        )

    first = bar.demands[0]
    for demand in bar.demands:
        assigned_ids.append(demand.demand_id)
        if demand.net_length_mm <= 0:
            issues.append(
                ValidationIssue(
                    "INVALID_ASSIGNED_LENGTH",
                    "Assigned demand has non-positive net length.",
                    demand_id=demand.demand_id,
                    bar_id=bar.bar_id,
                )
            )
        original = input_by_id.get(demand.demand_id)
        if original is not None and original != demand:
            issues.append(
                ValidationIssue(
                    "DEMAND_MUTATED",
                    "Assigned demand fields differ from the frozen input.",
                    demand_id=demand.demand_id,
                    bar_id=bar.bar_id,
                )
            )
        if demand.project_code != first.project_code or demand.block_name != first.block_name:
            issues.append(
                ValidationIssue(
                    "CROSS_BLOCK_MIXING",
                    "A bar contains demands from more than one project/block.",
                    demand_id=demand.demand_id,
                    bar_id=bar.bar_id,
                )
            )
        if (
            demand.compatibility_key[1:] != first.compatibility_key[1:]
        ):
            issues.append(
                ValidationIssue(
                    "INCOMPATIBLE_DEMANDS",
                    "A bar mixes material/profile/specification groups.",
                    demand_id=demand.demand_id,
                    bar_id=bar.bar_id,
                )
            )
        bar_key = bar_group_key(bar)
        exact_material = demand.compatibility_key[0] == bar_key[0]
        allowed_substitution = (
            demand.compatibility_key[0],
            bar_key[0],
            demand.compatibility_key[1],
        ) in substitution_rules
        if demand.compatibility_key[1:] != bar_key[1:] or not (
            exact_material or allowed_substitution
        ):
            issues.append(
                ValidationIssue(
                    "BAR_DEMAND_MISMATCH",
                    "Demand is not exactly compatible with its assigned bar.",
                    demand_id=demand.demand_id,
                    bar_id=bar.bar_id,
                )
            )

    if bar.stock_source_type == "NEW_PURCHASE":
        if require_purchase_weight and not (
            bar.unit_weight_kg_per_m and bar.unit_weight_kg_per_m > 0
        ):
            issues.append(
                ValidationIssue(
                    "MISSING_PURCHASE_WEIGHT",
                    "Additional purchase has no positive nominal unit weight.",
                    bar_id=bar.bar_id,
                )
            )
        if bar.stock_unit_id is not None:
            issues.append(
                ValidationIssue(
                    "PURCHASE_HAS_STOCK_ID",
                    "Additional-purchase bar must not consume an initial stock id.",
                    bar_id=bar.bar_id,
                )
            )
        if standard_lengths and round(bar.stock_length_mm, 7) not in standard_lengths:
            issues.append(
                ValidationIssue(
                    "INVALID_PURCHASE_LENGTH",
                    "Additional-purchase length is outside the frozen standard lengths.",
                    bar_id=bar.bar_id,
                )
            )
    elif bar.stock_unit_id is not None:
        used_stock_ids[bar.stock_unit_id] += 1
        stock = stock_by_id.get(bar.stock_unit_id)
        if stock is None:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_STOCK_ID",
                    "Bar references a stock unit that is not in the input inventory.",
                    bar_id=bar.bar_id,
                )
            )
        elif (
            stock.group_key != bar_group_key(bar)
            or abs(stock.stock_length_mm - bar.stock_length_mm) > EPSILON
            or stock.source_type != bar.stock_source_type
        ):
            issues.append(
                ValidationIssue(
                    "STOCK_BAR_MISMATCH",
                    "Bar properties differ from the referenced finite stock unit.",
                    bar_id=bar.bar_id,
                )
            )
    elif bar.stock_source_type != "STANDARD":
        issues.append(
            ValidationIssue(
                "MISSING_STOCK_ID",
                "A finite-stock or remnant bar has no inventory unit id.",
                bar_id=bar.bar_id,
            )
        )


def bar_group_key(bar: Bar) -> tuple[str, str, str]:
    probe = Demand(
        demand_id="",
        project_code="",
        block_name="",
        material=bar.material,
        profile_type=bar.profile_type,
        specification=bar.specification,
        net_length_mm=1.0,
    )
    return probe.compatibility_key
