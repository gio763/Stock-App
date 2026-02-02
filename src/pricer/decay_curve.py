"""
Shifted Weekly Decay Curve Engine for Music Catalog Pricing.

PROBLEM SOLVED:
---------------
Our decay curves assume Week 1 is PEAK (very aggressive early decay). But in real deals,
the artist/catalog is often already post-peak. The user inputs CURRENT weekly streams
(already decayed). If we start them at Week 1, we double-decay and underprice.

SOLUTION (Option 1):
--------------------
1. Build a single 10-year WEEKLY curve (Week 1..520) from Excel data:
   - Year 1: Use explicit WoW rates to build normalized level index L[t]
   - Years 2-10: Solve weekly decay factor d_y per year to match annual targets

2. SHIFT/WINDOW the curve forward by "weeks_post_peak" to skip early weeks.

3. ANCHOR at the shifted week to prevent double-decay:
   - If weeks_post_peak = k, user's current weekly streams correspond to model week (1+k)
   - Scale factor = current_streams / L[1+k]
   - This guarantees: projected_streams[1+k] == current_streams (near-zero error)

4. Output "Year 1..Year 10" as the NEXT 10 years FROM TODAY (shifted windows):
   - Year 1 = weeks (1+k .. 52+k)
   - Year 2 = weeks (53+k .. 104+k)
   - ...
   - Year 10 = weeks (469+k .. 520+k)

WHY THIS PREVENTS DOUBLE-DECAY:
-------------------------------
- Without offset: We assume user's input is Week 1 (peak). We apply full decay from peak.
  If catalog is actually 26 weeks post-peak, we decay from an artificially high point.

- With offset: We anchor at week (1+k). The user's current streams ARE the level at that
  point in the decay curve. We scale the curve to match, then project forward from there.
  No decay is applied to weeks we've already passed.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ShiftedCurveResult:
    """Results from shifted weekly decay curve calculation."""

    # The full normalized level curve L[t] for t=1..max_weeks (unscaled, L[1]=1.0)
    level_curve: List[float]

    # Scaling factors
    weeks_post_peak: int
    anchor_week: int  # = 1 + weeks_post_peak
    anchor_level: float  # = L[anchor_week]
    scale_factor_audio: float  # = current_audio / L[anchor_week]
    scale_factor_video: float  # = current_video / L[anchor_week]

    # Shifted annual totals (Year 1 = weeks 1+k to 52+k, etc.)
    shifted_annual_revenues_audio: Dict[int, float]
    shifted_annual_revenues_video: Dict[int, float]
    shifted_annual_totals: Dict[int, float]

    # Shifted annual multipliers (relative to shifted Year 1)
    shifted_annual_multipliers: Dict[int, float]

    # Per-year decay factors from curve building (Year 1 = None, Years 2-10 = d_y)
    yearly_decay_factors: Dict[int, Optional[float]]

    # Year 10's decay factor (for extending beyond 520 weeks)
    d_10: float

    # Unshifted annual sums in level units (for validation)
    unshifted_annual_sums: Dict[int, float]

    # Excel targets (for validation)
    excel_multipliers: Dict[int, float]

    # Year 1 weekly WoW rates from Excel
    year1_wow_rates: List[float]

    # S1 = sum of L[1..52] (Year 1 total in level units)
    s1_level_units: float


def geometric_sum(start: float, factor: float, n: int) -> float:
    """
    Compute sum: start * (1 + d + d^2 + ... + d^(n-1)) = start * sum_{j=0..n-1} d^j

    For our use: sum_{j=1..n} start * d^j = start * d * (1 - d^n) / (1 - d)
    """
    if abs(factor - 1.0) < 1e-12:
        return start * n
    return start * (1 - factor**n) / (1 - factor)


def solve_decay_factor_for_target(
    start_level: float,
    target_sum: float,
    num_weeks: int = 52,
    tolerance: float = 1e-12,
    max_iterations: int = 300,
) -> float:
    """
    Solve for weekly decay factor d such that:
        sum_{j=1..num_weeks} (start_level * d^j) = target_sum

    This is the sum STARTING from week 1 after start_level (which is week 0 of the year).
    So we need: start_level * d * (1 - d^52) / (1 - d) = target_sum

    Uses binary search (monotonic: higher d -> higher sum).

    Args:
        start_level: Level at the END of the previous year (week 0 of this year)
        target_sum: Target sum for this year's 52 weeks
        num_weeks: Number of weeks (52)
        tolerance: Convergence tolerance
        max_iterations: Max binary search iterations

    Returns:
        Decay factor d

    Raises:
        ValueError: If cannot converge or invalid inputs
    """
    if start_level <= 0:
        raise ValueError(f"start_level must be positive, got {start_level}")
    if target_sum <= 0:
        raise ValueError(f"target_sum must be positive, got {target_sum}")

    def compute_year_sum(d: float) -> float:
        """Sum of 52 weeks: start_level * d^1 + start_level * d^2 + ... + start_level * d^52"""
        if abs(d - 1.0) < 1e-12:
            return start_level * num_weeks
        return start_level * d * (1 - d**num_weeks) / (1 - d)

    # Binary search in range [0.0001, 10.0]
    d_low, d_high = 0.0001, 10.0

    for iteration in range(max_iterations):
        d_mid = (d_low + d_high) / 2
        current_sum = compute_year_sum(d_mid)

        error = abs(current_sum - target_sum)
        if error < tolerance:
            return d_mid

        # Higher d -> higher sum (monotonic for d > 0)
        if current_sum < target_sum:
            d_low = d_mid
        else:
            d_high = d_mid

    # Return best approximation
    return (d_low + d_high) / 2


def build_unshifted_level_curve(
    wow_rates: List[float],
    excel_multipliers: Dict[int, float],
    num_years: int = 10,
) -> Tuple[List[float], Dict[int, float], Dict[int, Optional[float]], float]:
    """
    Build the base 10-year weekly level curve L[t] for t=1..520 (unshifted).

    Args:
        wow_rates: 52 week-over-week rates for Year 1 (rate[w] = L[w] / L[w-1])
        excel_multipliers: Annual multipliers M_y = YearTotal_y / YearTotal_1 for years 1-10
        num_years: Number of years (10)

    Returns:
        Tuple of:
        - level_curve: L[t] for t=1..520 (index 0 = week 1)
        - unshifted_annual_sums: Sum of L over each year in level units
        - yearly_decay_factors: d_y for each year (Year 1 = None)
        - s1: Year 1 total in level units

    Raises:
        ValueError: If wow_rates count != 52 or missing multipliers
    """
    if len(wow_rates) != 52:
        raise ValueError(f"Expected 52 WoW rates, got {len(wow_rates)}")

    for year in range(1, num_years + 1):
        if year not in excel_multipliers:
            raise ValueError(f"Missing excel_multiplier for Year {year}")
        if excel_multipliers[year] <= 0:
            raise ValueError(f"Invalid excel_multiplier for Year {year}: {excel_multipliers[year]}")

    # Normalize multipliers so M_1 = 1.0
    m1 = excel_multipliers[1]
    normalized_multipliers = {y: m / m1 for y, m in excel_multipliers.items()}

    level_curve: List[float] = []
    yearly_decay_factors: Dict[int, Optional[float]] = {}
    unshifted_annual_sums: Dict[int, float] = {}

    # === YEAR 1: Build from WoW rates ===
    # L[1] = 1.0 (normalized baseline at week 1)
    # L[t] = L[t-1] * rate[t-1] for t=2..52

    # Build it based on applying rates sequentially:
    level_curve = [1.0]  # L[1] = 1.0 at index 0

    for t in range(2, 53):  # t = 2..52
        # wow_rates[t-1] is the rate for week t (0-indexed: t-1)
        rate = wow_rates[t - 1]  # t-1 because wow_rates is 0-indexed, t is 1-indexed
        level_curve.append(level_curve[-1] * rate)

    # Now level_curve has 52 entries: L[1]..L[52] at indices 0..51
    yearly_decay_factors[1] = None  # Year 1 uses explicit rates, not a single factor

    # Compute S1 = sum of L[1..52]
    s1 = sum(level_curve)
    unshifted_annual_sums[1] = s1

    # === YEARS 2-10: Solve d_y to match target annual sums ===
    # Target: Sy_target = S1 * M_y (where M_y is the normalized multiplier)
    #
    # For each year y >= 2:
    # - year_start_level = L[52*(y-1)] = last week of previous year
    # - Generate 52 weeks: L[52*(y-1)+j] = year_start_level * d_y^j for j=1..52
    # - Sum should equal Sy_target

    for year in range(2, num_years + 1):
        target_multiplier = normalized_multipliers[year]
        sy_target = s1 * target_multiplier

        # Start level = end of previous year
        year_start_level = level_curve[-1]  # L at week 52*(year-1)

        # Solve for d_y
        d_y = solve_decay_factor_for_target(
            start_level=year_start_level,
            target_sum=sy_target,
            num_weeks=52,
        )
        yearly_decay_factors[year] = d_y

        # Generate 52 weeks for this year
        year_levels = []
        for j in range(1, 53):  # j = 1..52
            level = year_start_level * (d_y ** j)
            year_levels.append(level)
            level_curve.append(level)

        unshifted_annual_sums[year] = sum(year_levels)

    # level_curve now has 52 + 9*52 = 520 entries: L[1]..L[520] at indices 0..519
    assert len(level_curve) == 520, f"Expected 520 weeks, got {len(level_curve)}"

    return level_curve, unshifted_annual_sums, yearly_decay_factors, s1


def extend_curve_beyond_520(
    level_curve: List[float],
    d_10: float,
    extra_weeks: int,
) -> List[float]:
    """
    Extend the level curve beyond week 520 using Year 10's decay factor.

    For t > 520: L[t] = L[t-1] * d_10

    Args:
        level_curve: Existing curve L[1..520] (indices 0..519)
        d_10: Year 10's weekly decay factor
        extra_weeks: Number of weeks to add beyond 520

    Returns:
        Extended curve
    """
    extended = level_curve.copy()
    for _ in range(extra_weeks):
        extended.append(extended[-1] * d_10)
    return extended


def build_shifted_curve(
    wow_rates: List[float],
    excel_multipliers: Dict[int, float],
    weeks_post_peak: int,
    current_weekly_audio_streams: float,
    current_weekly_video_streams: float,
    blended_audio_rate: float,
    video_rate: float,
    num_years: int = 10,
) -> ShiftedCurveResult:
    """
    Build a shifted 10-year weekly curve with offset anchoring.

    Args:
        wow_rates: 52 WoW rates for Year 1 from Excel
        excel_multipliers: Annual multipliers M_y for years 1-10 from Excel
        weeks_post_peak: How many weeks past peak the catalog currently is (>= 0)
        current_weekly_audio_streams: User's current weekly audio streams
        current_weekly_video_streams: User's current weekly video streams
        blended_audio_rate: $/stream for audio
        video_rate: $/stream for video
        num_years: Number of years to project (10)

    Returns:
        ShiftedCurveResult with all projection data

    Raises:
        ValueError: For invalid inputs
    """
    if weeks_post_peak < 0:
        raise ValueError(f"weeks_post_peak must be >= 0, got {weeks_post_peak}")
    if current_weekly_audio_streams < 0:
        raise ValueError(f"current_weekly_audio_streams must be >= 0")
    if current_weekly_video_streams < 0:
        raise ValueError(f"current_weekly_video_streams must be >= 0")

    # Build unshifted level curve
    level_curve, unshifted_annual_sums, yearly_decay_factors, s1 = build_unshifted_level_curve(
        wow_rates=wow_rates,
        excel_multipliers=excel_multipliers,
        num_years=num_years,
    )

    # Get Year 10's decay factor for extension
    d_10 = yearly_decay_factors[10]
    if d_10 is None:
        raise ValueError("Year 10 decay factor is None - should not happen")

    # Calculate how many extra weeks we need beyond 520
    # Year 10 shifted = weeks (469+k .. 520+k)
    # Max week needed = 520 + k
    k = weeks_post_peak
    max_week_needed = 520 + k

    if max_week_needed > 520:
        extra_weeks = max_week_needed - 520
        level_curve = extend_curve_beyond_520(level_curve, d_10, extra_weeks)

    # Anchor at week (1 + k)
    # level_curve is 0-indexed, so week (1+k) is at index k
    anchor_week = 1 + k
    anchor_idx = k  # 0-indexed

    if anchor_idx >= len(level_curve):
        raise ValueError(f"anchor_week {anchor_week} exceeds curve length {len(level_curve)}")

    anchor_level = level_curve[anchor_idx]

    if anchor_level <= 0:
        raise ValueError(f"anchor_level at week {anchor_week} is non-positive: {anchor_level}")

    # Scale factors to convert level units to actual streams
    # audio_streams[t] = scale_audio * L[t]
    # At anchor point: current_audio = scale_audio * L[anchor_week]
    # Therefore: scale_audio = current_audio / L[anchor_week]
    scale_audio = current_weekly_audio_streams / anchor_level if current_weekly_audio_streams > 0 else 0
    scale_video = current_weekly_video_streams / anchor_level if current_weekly_video_streams > 0 else 0

    # Compute shifted annual totals
    # Year 1 (shifted) = weeks (1+k .. 52+k) = indices (k .. 51+k)
    # Year 2 (shifted) = weeks (53+k .. 104+k) = indices (52+k .. 103+k)
    # ...
    shifted_annual_revenues_audio: Dict[int, float] = {}
    shifted_annual_revenues_video: Dict[int, float] = {}
    shifted_annual_totals: Dict[int, float] = {}

    for year in range(1, num_years + 1):
        # Shifted year boundaries
        start_week = 1 + (year - 1) * 52 + k  # 1-indexed week number
        end_week = 52 + (year - 1) * 52 + k

        # Convert to 0-indexed
        start_idx = start_week - 1
        end_idx = end_week - 1

        # Sum levels for this year
        year_level_sum = sum(level_curve[start_idx:end_idx + 1])

        # Convert to revenue
        audio_streams_annual = scale_audio * year_level_sum
        video_streams_annual = scale_video * year_level_sum

        audio_rev = audio_streams_annual * blended_audio_rate
        video_rev = video_streams_annual * video_rate

        shifted_annual_revenues_audio[year] = audio_rev
        shifted_annual_revenues_video[year] = video_rev
        shifted_annual_totals[year] = audio_rev + video_rev

    # Compute shifted multipliers relative to shifted Year 1
    year1_shifted_total = shifted_annual_totals[1]
    if year1_shifted_total > 0:
        shifted_annual_multipliers = {
            y: total / year1_shifted_total
            for y, total in shifted_annual_totals.items()
        }
    else:
        shifted_annual_multipliers = {y: 0.0 for y in range(1, num_years + 1)}

    return ShiftedCurveResult(
        level_curve=level_curve,
        weeks_post_peak=weeks_post_peak,
        anchor_week=anchor_week,
        anchor_level=anchor_level,
        scale_factor_audio=scale_audio,
        scale_factor_video=scale_video,
        shifted_annual_revenues_audio=shifted_annual_revenues_audio,
        shifted_annual_revenues_video=shifted_annual_revenues_video,
        shifted_annual_totals=shifted_annual_totals,
        shifted_annual_multipliers=shifted_annual_multipliers,
        yearly_decay_factors=yearly_decay_factors,
        d_10=d_10,
        unshifted_annual_sums=unshifted_annual_sums,
        excel_multipliers=excel_multipliers,
        year1_wow_rates=wow_rates,
        s1_level_units=s1,
    )


def validate_unshifted_curve(
    level_curve: List[float],
    unshifted_annual_sums: Dict[int, float],
    excel_multipliers: Dict[int, float],
    s1: float,
    tolerance: float = 0.0001,
) -> Dict[str, any]:
    """
    Validate that unshifted curve matches Excel calibration.

    Args:
        level_curve: L[1..520] (0-indexed)
        unshifted_annual_sums: Annual sums in level units
        excel_multipliers: Excel M_y values
        s1: Year 1 sum in level units
        tolerance: Max allowed relative error

    Returns:
        Validation result dict
    """
    # Normalize multipliers
    m1 = excel_multipliers[1]
    normalized = {y: m / m1 for y, m in excel_multipliers.items()}

    errors = []
    max_error = 0.0
    worst_year = None

    for year in range(1, 11):
        # Target sum = S1 * M_y
        target = s1 * normalized[year]
        actual = unshifted_annual_sums[year]

        if target > 0:
            rel_error = abs(actual - target) / target
            if rel_error > max_error:
                max_error = rel_error
                worst_year = year

            if rel_error > tolerance:
                errors.append({
                    "year": year,
                    "target": target,
                    "actual": actual,
                    "error": rel_error,
                })

    return {
        "valid": len(errors) == 0,
        "max_error": max_error,
        "worst_year": worst_year,
        "errors": errors,
    }


def validate_anchor_point(
    result: ShiftedCurveResult,
    current_weekly_audio_streams: float,
    tolerance: float = 1e-9,
) -> Dict[str, any]:
    """
    Validate that anchor point matches user's input exactly.

    At anchor_week, the projected audio streams should equal current_weekly_audio_streams.
    """
    # Compute projected audio at anchor week
    anchor_idx = result.anchor_week - 1  # 0-indexed
    projected_audio_at_anchor = result.scale_factor_audio * result.level_curve[anchor_idx]

    error = abs(projected_audio_at_anchor - current_weekly_audio_streams)

    return {
        "valid": error < tolerance,
        "anchor_week": result.anchor_week,
        "L_anchor": result.anchor_level,
        "scale_audio": result.scale_factor_audio,
        "projected_at_anchor": projected_audio_at_anchor,
        "expected": current_weekly_audio_streams,
        "error": error,
    }
