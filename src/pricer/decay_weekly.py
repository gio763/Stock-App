"""
Weekly decay engine for accurate revenue projections.

HOW IT WORKS:
-------------
1. YEAR 1: Uses explicit week-over-week rates from Excel sheet.
   - Week 0 = user input (weekly_streams x blended_rate)
   - Weeks 1-52 = apply the 52 weekly rates from Excel
   - Year 1 total = sum of weeks 0-52 (53 weeks)

2. YEARS 2-10: For each year, solve for a weekly decay factor d_y such that:
   - Year total = Year1_total x Excel_multiplier[y]
   - Continuity: start_level[y] = end_level[y-1]

3. This handles NON-EXPONENTIAL decay curves because each year gets its own
   factor solved to match the target.

4. NO DOUBLE DECAY: Annual multipliers are targets relative to Year 1 total,
   not compounded year over year.

IMPORTANT:
----------
The Excel multipliers are YEAR TOTAL multipliers relative to Year 1 total.
The weekly rates are week-over-week multipliers for Year 1 decay.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class WeeklyDecayResult:
    """Results from weekly decay calculation."""

    # Weekly vectors (530 weeks = Year 1 has 53 weeks + 9 years x 52 weeks)
    weekly_revenues: List[float]
    weekly_multipliers: List[float]  # Relative to Week 0

    # Annual aggregates (years 1-10)
    annual_revenues: Dict[int, float]
    annual_multipliers: Dict[int, float]  # Relative to Year 1 total

    # Key values
    week0_revenue: float  # User input level (baseline for Year 1)
    year1_total: float  # Sum of weeks 0-52 (reference for subsequent years)

    # Per-year decay factors (Year 1 = None since explicit rates)
    yearly_decay_factors: Dict[int, Optional[float]]

    # Original Excel multipliers for reference
    excel_multipliers: Dict[int, float]

    # Year 1 weekly rates from Excel (for debugging)
    year1_weekly_rates: Optional[List[float]] = None


def geometric_sum(start: float, factor: float, n: int) -> float:
    """Compute sum: start x (1 + d + d^2 + ... + d^(n-1))"""
    if abs(factor - 1.0) < 1e-12:
        return start * n
    return start * (1 - factor**n) / (1 - factor)


def solve_weekly_factor_for_target(
    start_level: float,
    target_sum: float,
    num_weeks: int = 52,
    tolerance: float = 1e-9,
    max_iterations: int = 200,
) -> float:
    """
    Solve for weekly factor d such that:
        sum_{k=0..num_weeks-1} (start_level x d^k) = target_sum

    Uses binary search in range [0.001, 10.0] to handle steep decay and growth.
    """
    if start_level <= 0:
        raise ValueError(f"start_level must be positive, got {start_level}")
    if target_sum <= 0:
        raise ValueError(f"target_sum must be positive, got {target_sum}")

    # Edge case: if target equals flat sum
    if abs(target_sum - start_level * num_weeks) < tolerance:
        return 1.0

    # Binary search
    d_low, d_high = 0.001, 10.0

    for _ in range(max_iterations):
        d_mid = (d_low + d_high) / 2
        current_sum = geometric_sum(start_level, d_mid, num_weeks)

        if abs(current_sum - target_sum) < tolerance:
            return d_mid

        # Higher d -> higher sum
        if current_sum < target_sum:
            d_low = d_mid
        else:
            d_high = d_mid

    return (d_low + d_high) / 2


def build_weekly_curve_with_rates(
    week0_revenue: float,
    weekly_rates: List[float],
    excel_multipliers: Dict[int, float],
    num_years: int = 10,
) -> WeeklyDecayResult:
    """
    Build weekly revenue curve using explicit Year 1 rates from Excel.

    Year 1: Apply the 52 weekly rates to decay from week 0.
    Years 2-10: Solve d_y per year to match Year1_total x M_y.

    Args:
        week0_revenue: Week 0 revenue (user input: weekly_streams x blended_rate)
        weekly_rates: List of 52 week-over-week multipliers for weeks 1-52
        excel_multipliers: {year: multiplier} from Excel. Year 1 should be ~1.0.

    Returns:
        WeeklyDecayResult with weekly curve and annual totals
    """
    if len(weekly_rates) != 52:
        raise ValueError(f"Expected 52 weekly rates, got {len(weekly_rates)}")
    if 1 not in excel_multipliers:
        raise ValueError("excel_multipliers must include Year 1")

    # Normalize multipliers so Year 1 = 1.0
    m1 = excel_multipliers.get(1, 1.0)
    normalized = {y: m / m1 for y, m in excel_multipliers.items()}

    weekly_revenues: List[float] = []
    weekly_multipliers: List[float] = []
    yearly_decay_factors: Dict[int, Optional[float]] = {}

    # === YEAR 1: Use explicit weekly rates ===
    yearly_decay_factors[1] = None  # Not a single factor, but explicit rates

    # Week 0
    weekly_revenues.append(week0_revenue)
    weekly_multipliers.append(1.0)

    # Weeks 1-52: apply the 52 weekly rates
    current_rev = week0_revenue
    for rate in weekly_rates:
        current_rev = current_rev * rate
        weekly_revenues.append(current_rev)
        weekly_multipliers.append(current_rev / week0_revenue)

    # Year 1 total = sum of weeks 0-52 (53 weeks)
    year1_total = sum(weekly_revenues[:53])

    # === YEARS 2-10 ===
    # For each year, solve for d_y to match target = year1_total x multiplier[y]
    for year in range(2, num_years + 1):
        target_mult = normalized.get(year)
        if target_mult is None or target_mult <= 0:
            raise ValueError(f"Missing or invalid multiplier for Year {year}")

        target_sum = year1_total * target_mult

        # Start where previous year ended (continuity)
        start_level = weekly_revenues[-1]

        # Solve for this year's weekly factor
        d_y = solve_weekly_factor_for_target(
            start_level=start_level,
            target_sum=target_sum,
            num_weeks=52,
        )
        yearly_decay_factors[year] = d_y

        # Generate 52 weeks for this year
        for week in range(52):
            rev = start_level * (d_y ** week)
            weekly_revenues.append(rev)
            weekly_multipliers.append(rev / week0_revenue)

    # Aggregate to annual totals
    annual_revenues: Dict[int, float] = {}

    # Year 1: weeks 0-52 (indices 0-52, 53 weeks)
    annual_revenues[1] = sum(weekly_revenues[0:53])

    # Years 2-10: 52 weeks each
    for year in range(2, num_years + 1):
        # Year 2 starts at index 53, etc.
        start_idx = 53 + (year - 2) * 52
        end_idx = start_idx + 52
        annual_revenues[year] = sum(weekly_revenues[start_idx:end_idx])

    # Annual multipliers relative to Year 1 total
    annual_multipliers = {y: rev / year1_total for y, rev in annual_revenues.items()}

    return WeeklyDecayResult(
        weekly_revenues=weekly_revenues,
        weekly_multipliers=weekly_multipliers,
        annual_revenues=annual_revenues,
        annual_multipliers=annual_multipliers,
        week0_revenue=week0_revenue,
        year1_total=year1_total,
        yearly_decay_factors=yearly_decay_factors,
        excel_multipliers=normalized,
        year1_weekly_rates=weekly_rates,
    )


def build_weekly_curve(
    week1_revenue: float,
    excel_multipliers: Dict[int, float],
    num_years: int = 10,
) -> WeeklyDecayResult:
    """
    Build 520-week revenue curve matching Excel annual multipliers.

    LEGACY INTERFACE: Uses flat Year 1 (no weekly rates).
    For accurate Year 1 decay, use build_weekly_curve_with_rates().

    Year 1: Flat (no decay). All 53 weeks = week1_revenue.
    Years 2-10: Solve d_y per year to match Year1_total x M_y.

    Args:
        week1_revenue: Week 1 revenue (user input: weekly_streams x blended_rate)
        excel_multipliers: {year: multiplier} from Excel. Year 1 should be ~1.0.

    Returns:
        WeeklyDecayResult with weekly curve and annual totals
    """
    if 1 not in excel_multipliers:
        raise ValueError("excel_multipliers must include Year 1")

    # Normalize multipliers so Year 1 = 1.0
    m1 = excel_multipliers.get(1, 1.0)
    normalized = {y: m / m1 for y, m in excel_multipliers.items()}

    weekly_revenues: List[float] = []
    weekly_multipliers: List[float] = []
    yearly_decay_factors: Dict[int, Optional[float]] = {}

    # === YEAR 1: Flat (no intra-year decay) ===
    yearly_decay_factors[1] = 1.0  # Flat

    for week in range(53):  # 53 weeks for Year 1 (weeks 0-52)
        weekly_revenues.append(week1_revenue)
        weekly_multipliers.append(1.0)

    year1_total = week1_revenue * 53  # = sum of Year 1

    # === YEARS 2-10 ===
    for year in range(2, num_years + 1):
        target_mult = normalized.get(year)
        if target_mult is None or target_mult <= 0:
            raise ValueError(f"Missing or invalid multiplier for Year {year}")

        target_sum = year1_total * target_mult

        # Start where previous year ended (continuity)
        start_level = weekly_revenues[-1]

        # Solve for this year's weekly factor
        d_y = solve_weekly_factor_for_target(
            start_level=start_level,
            target_sum=target_sum,
            num_weeks=52,
        )
        yearly_decay_factors[year] = d_y

        # Generate 52 weeks for this year
        for week in range(52):
            rev = start_level * (d_y ** week)
            weekly_revenues.append(rev)
            weekly_multipliers.append(rev / week1_revenue)

    # Aggregate to annual totals
    annual_revenues: Dict[int, float] = {}
    annual_revenues[1] = sum(weekly_revenues[0:53])

    for year in range(2, num_years + 1):
        start_idx = 53 + (year - 2) * 52
        end_idx = start_idx + 52
        annual_revenues[year] = sum(weekly_revenues[start_idx:end_idx])

    # Annual multipliers relative to Year 1 total
    annual_multipliers = {y: rev / year1_total for y, rev in annual_revenues.items()}

    return WeeklyDecayResult(
        weekly_revenues=weekly_revenues,
        weekly_multipliers=weekly_multipliers,
        annual_revenues=annual_revenues,
        annual_multipliers=annual_multipliers,
        week0_revenue=week1_revenue,
        year1_total=year1_total,
        yearly_decay_factors=yearly_decay_factors,
        excel_multipliers=normalized,
        year1_weekly_rates=None,
    )


def validate_weekly_curve(
    result: WeeklyDecayResult,
    tolerance: float = 0.01,
) -> Dict[str, any]:
    """
    Validate that Years 1-10 match Excel multipliers within tolerance.
    """
    errors = []
    max_error = 0.0
    worst_year = None

    for year in range(1, 11):
        excel_mult = result.excel_multipliers.get(year, 0)
        model_mult = result.annual_multipliers.get(year, 0)

        if excel_mult > 0:
            rel_error = abs(model_mult - excel_mult) / excel_mult
            if rel_error > max_error:
                max_error = rel_error
                worst_year = year

            if rel_error > tolerance:
                errors.append({
                    "year": year,
                    "excel": excel_mult,
                    "model": model_mult,
                    "error": rel_error,
                })

    return {
        "valid": len(errors) == 0,
        "max_error": max_error,
        "worst_year": worst_year,
        "errors": errors,
        "tolerance": tolerance,
    }


def validate_all_genres(
    decay_by_genre: Dict[str, Dict[int, float]],
    weekly_rates_by_genre: Optional[Dict[str, Dict[str, any]]] = None,
    base_weekly_revenue: float = 1000.0,
    tolerance: float = 0.01,
) -> Dict[str, any]:
    """
    Validate weekly decay for ALL genres.

    Args:
        decay_by_genre: {genre: {year: multiplier}}
        weekly_rates_by_genre: Optional {genre: {"weekly_rates": [...], ...}}
        base_weekly_revenue: Base weekly revenue for testing
        tolerance: Maximum allowed relative error

    Returns:
        Validation results dict
    """
    results = {}
    all_valid = True

    for genre, multipliers in decay_by_genre.items():
        try:
            if weekly_rates_by_genre and genre in weekly_rates_by_genre:
                # Use explicit weekly rates
                rates_data = weekly_rates_by_genre[genre]
                result = build_weekly_curve_with_rates(
                    base_weekly_revenue,
                    rates_data["weekly_rates"],
                    multipliers,
                )
            else:
                # Fall back to flat Year 1
                result = build_weekly_curve(base_weekly_revenue, multipliers)

            validation = validate_weekly_curve(result, tolerance)

            worst_year = validation["worst_year"]

            results[genre] = {
                "valid": validation["valid"],
                "max_error": validation["max_error"],
                "worst_year": worst_year,
            }

            if not validation["valid"]:
                all_valid = False

        except Exception as e:
            results[genre] = {"valid": False, "error": str(e)}
            all_valid = False

    if not all_valid:
        raise ValueError("Weekly decay validation failed.")

    return {"all_valid": all_valid, "results": results}


def compare_decay_modes(
    week1_revenue: float,
    excel_multipliers: Dict[int, float],
    weekly_rates: Optional[List[float]] = None,
    discount_rate: float = 0.10,
) -> Dict[str, any]:
    """
    Compare annual vs weekly decay modes.

    In this implementation, both modes produce the SAME annual totals.
    The difference is that weekly mode provides week-by-week granularity.
    """
    m1 = excel_multipliers.get(1, 1.0)
    normalized = {y: m / m1 for y, m in excel_multipliers.items()}

    # Annual mode: Year totals directly (using 53 weeks for Year 1)
    annual_year1 = week1_revenue * 53
    annual_revenues = {year: annual_year1 * mult for year, mult in normalized.items()}

    # Weekly mode
    if weekly_rates:
        weekly_result = build_weekly_curve_with_rates(week1_revenue, weekly_rates, excel_multipliers)
    else:
        weekly_result = build_weekly_curve(week1_revenue, excel_multipliers)

    # PV calculation
    def compute_pv(revenues: Dict[int, float], rate: float) -> float:
        return sum(rev / ((1 + rate) ** year) for year, rev in revenues.items())

    annual_pv = compute_pv(annual_revenues, discount_rate)
    weekly_pv = compute_pv(weekly_result.annual_revenues, discount_rate)

    return {
        "annual": {
            "year1_revenue": annual_year1,
            "year2_revenue": annual_revenues.get(2, 0),
            "total_revenue": sum(annual_revenues.values()),
            "total_pv": annual_pv,
            "revenues": annual_revenues,
        },
        "weekly": {
            "year1_revenue": weekly_result.year1_total,
            "year2_revenue": weekly_result.annual_revenues.get(2, 0),
            "total_revenue": sum(weekly_result.annual_revenues.values()),
            "total_pv": weekly_pv,
            "revenues": weekly_result.annual_revenues,
        },
        "validation": validate_weekly_curve(weekly_result),
    }
