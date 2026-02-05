"""
Payback and IRR-based deal cost solvers for music catalog pricing.

This module provides:
1. Weekly cash flow simulation with recoup waterfall
2. Payback-based max cost: Maximum recoupable in payback horizon
3. IRR-based max cost: max cost for target IRR (no payback constraint)
4. Recoup week computation for any given cost

DEAL TYPE MECHANICS:
-------------------
- DISTRIBUTION: Artist's share (gross - distro fee) used for recoupment
- ROYALTY: Only artist's royalty % is available for recoupment
- PROFIT_SPLIT: Expenses deducted from gross, remainder split - no withholding

PAYBACK CALCULATION:
-------------------
The 18-month payback max is the amount that can be recouped within 78 weeks.
This varies by deal type based on what portion of revenue is available:
- Distribution: artist_share × 78-week gross
- Royalty: royalty_rate × 78-week gross
- Profit Split: 78-week gross (expenses come off top before split)
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


class DealType(Enum):
    """Types of deal structures for payback calculations."""
    DISTRIBUTION = "distribution"
    PROFIT_SPLIT = "profit_split"
    ROYALTY = "royalty"


@dataclass
class WeeklyCashFlowResult:
    """Results from weekly cash flow simulation."""

    # Weekly series
    weekly_label_cash_in: List[float]
    weekly_artist_pay: List[float]
    weekly_gross: List[float]

    # Cumulative label cash-in at milestones
    cum_label_cash_in_78: float  # C(78)
    cum_label_cash_in_104: float  # C(104) = 2 years
    cum_label_cash_in_total: float  # C(520) = 10 years

    # Recoup info
    recoup_week: Optional[int]  # Week when recoup completes, or None
    recoupable_amount: float


def compute_weekly_cashflows(
    weekly_gross_series: List[float],
    deal_pct: float,
    total_cost: float,
    advance_share_pct: float,
    marketing_recoupable: bool,
) -> WeeklyCashFlowResult:
    """
    Compute weekly cash flows with recoup waterfall.

    Args:
        weekly_gross_series: Weekly gross revenues (520 weeks for 10 years)
        deal_pct: Label's share of gross (e.g., 0.25)
        total_cost: Total deal cost (advance + marketing)
        advance_share_pct: Fraction of cost that is advance (0-1)
        marketing_recoupable: Whether marketing is recoupable

    Returns:
        WeeklyCashFlowResult with all cash flow data
    """
    # Calculate recoupable amount
    advance = total_cost * advance_share_pct
    marketing = total_cost - advance

    if marketing_recoupable:
        recoupable_amount = total_cost
    else:
        recoupable_amount = advance

    artist_share = 1.0 - deal_pct

    weekly_label_cash_in = []
    weekly_artist_pay = []
    weekly_gross = []

    remaining_recoup = recoupable_amount
    recoup_week = None
    cum_label_78 = 0.0
    cum_label_104 = 0.0
    cum_label_total = 0.0

    for week_idx, gross in enumerate(weekly_gross_series):
        week_num = week_idx + 1

        # Base split
        label_base = gross * deal_pct
        artist_due = gross * artist_share

        # Recoup waterfall: label withholds from artist pay
        if remaining_recoup > 0:
            withheld = min(artist_due, remaining_recoup)
            remaining_recoup -= withheld
            label_cash_in = label_base + withheld
            artist_pay = artist_due - withheld

            if remaining_recoup <= 0 and recoup_week is None:
                recoup_week = week_num
        else:
            label_cash_in = label_base
            artist_pay = artist_due

        weekly_label_cash_in.append(label_cash_in)
        weekly_artist_pay.append(artist_pay)
        weekly_gross.append(gross)
        cum_label_total += label_cash_in

        if week_num == 78:
            cum_label_78 = cum_label_total
        if week_num == 104:
            cum_label_104 = cum_label_total

    # Handle case where we have fewer than 78/104 weeks
    if len(weekly_gross_series) < 78:
        cum_label_78 = cum_label_total
    if len(weekly_gross_series) < 104:
        cum_label_104 = cum_label_total

    return WeeklyCashFlowResult(
        weekly_label_cash_in=weekly_label_cash_in,
        weekly_artist_pay=weekly_artist_pay,
        weekly_gross=weekly_gross,
        cum_label_cash_in_78=cum_label_78,
        cum_label_cash_in_104=cum_label_104,
        cum_label_cash_in_total=cum_label_total,
        recoup_week=recoup_week,
        recoupable_amount=recoupable_amount,
    )


def compute_recoup_week(
    weekly_gross_series: List[float],
    deal_pct: float,
    total_cost: float,
    advance_share_pct: float,
    marketing_recoupable: bool,
) -> Optional[int]:
    """
    Compute the week when cumulative label cash-in reaches total_cost.

    This is the payback week - when the label has recovered their investment.

    Returns:
        Week number (1-indexed) when payback occurs, or None if never
    """
    result = compute_weekly_cashflows(
        weekly_gross_series=weekly_gross_series,
        deal_pct=deal_pct,
        total_cost=total_cost,
        advance_share_pct=advance_share_pct,
        marketing_recoupable=marketing_recoupable,
    )

    # Find week when cumulative label cash-in >= total_cost
    cum_cash_in = 0.0
    for week_idx, cash_in in enumerate(result.weekly_label_cash_in):
        week_num = week_idx + 1
        cum_cash_in += cash_in
        if cum_cash_in >= total_cost:
            return week_num

    return None  # Never reaches payback


def compute_payback_max_cost(
    weekly_gross_series: List[float],
    deal_pct: float,
    advance_share_pct: float,
    marketing_recoupable: bool,
    payback_horizon_weeks: int = 78,
    deal_type: Optional[DealType] = None,
) -> float:
    """
    Compute maximum deal cost that can be recouped by the horizon.

    The calculation varies by deal type:
    - DISTRIBUTION: Recoup from artist's share (1 - deal_pct) × gross
    - ROYALTY: Recoup from artist's royalty only. For royalty deals,
               deal_pct is label's share (e.g., 0.80), so recoup capacity
               is (1 - deal_pct) × gross = royalty_rate × gross
    - PROFIT_SPLIT: Expenses deducted from gross before split, so full
                    gross is available for expense deduction

    Args:
        weekly_gross_series: Weekly gross revenues
        deal_pct: Label's share (e.g., 0.25 for distribution, 0.80 for royalty)
        advance_share_pct: Fraction that is advance
        marketing_recoupable: Whether marketing is recoupable
        payback_horizon_weeks: Target week (default 78 = 18 months)
        deal_type: Type of deal (affects recoupment mechanics)

    Returns:
        Maximum deal cost that can be recouped by horizon
    """
    horizon_weeks = min(payback_horizon_weeks, len(weekly_gross_series))
    total_gross_in_horizon = sum(weekly_gross_series[:horizon_weeks])

    # Calculate recoupment capacity based on deal type
    if deal_type == DealType.PROFIT_SPLIT:
        # Profit split: expenses come off gross before split
        # Max expense = total gross (though this would leave nothing to split)
        # More realistically, cap at gross to ensure SOME profit
        recoup_capacity = total_gross_in_horizon
    elif deal_type == DealType.ROYALTY:
        # Royalty: only artist's royalty portion available for recoup
        # deal_pct = label's share (e.g., 0.80), royalty = 1 - 0.80 = 0.20
        artist_royalty_rate = 1.0 - deal_pct
        recoup_capacity = total_gross_in_horizon * artist_royalty_rate
    else:
        # Distribution (default): recoup from artist's share
        artist_share = 1.0 - deal_pct
        recoup_capacity = total_gross_in_horizon * artist_share

    # For profit split, we can return recoup capacity directly
    # (expenses are deducted, not withheld)
    if deal_type == DealType.PROFIT_SPLIT:
        return recoup_capacity

    # For distribution and royalty, use binary search to find exact max
    # that pays back by the horizon (accounts for weekly timing)
    cost_low = 0.0
    cost_high = recoup_capacity
    tolerance = 1.0  # $1 tolerance
    best_cost = 0.0

    for _ in range(100):  # Max iterations
        cost_mid = (cost_low + cost_high) / 2

        payback_week = compute_recoup_week(
            weekly_gross_series=weekly_gross_series,
            deal_pct=deal_pct,
            total_cost=cost_mid,
            advance_share_pct=advance_share_pct,
            marketing_recoupable=marketing_recoupable,
        )

        if payback_week is not None and payback_week <= payback_horizon_weeks:
            # Feasible - can increase cost
            best_cost = cost_mid
            cost_low = cost_mid
        else:
            # Not feasible - decrease cost
            cost_high = cost_mid

        if cost_high - cost_low < tolerance:
            break

    return best_cost


def compute_weekly_irr(
    total_cost: float,
    weekly_cash_flows: List[float],
    tolerance: float = 1e-6,
    max_iterations: int = 100,
) -> Optional[float]:
    """
    Compute IRR on weekly cash flows.

    IRR is the rate r where: -cost + sum(cf_t / (1+r)^t) = 0

    Args:
        total_cost: Initial investment (positive number)
        weekly_cash_flows: List of weekly cash inflows
        tolerance: Convergence tolerance
        max_iterations: Max iterations for Newton-Raphson

    Returns:
        Weekly IRR (multiply by 52 for annual), or None if no solution
    """
    if total_cost <= 0:
        return None

    # Check if total cash flows exceed cost
    total_cf = sum(weekly_cash_flows)
    if total_cf <= total_cost:
        return None  # Negative or zero IRR

    # Binary search for weekly IRR
    # Weekly IRR typically in range [-0.01, 0.05]
    r_low = -0.01
    r_high = 0.10  # 10% weekly = very high

    def npv_at_rate(r: float) -> float:
        if r <= -1:
            return float('inf')
        pv = 0.0
        for t, cf in enumerate(weekly_cash_flows, start=1):
            pv += cf / ((1 + r) ** t)
        return pv - total_cost

    # Check bounds
    npv_low = npv_at_rate(r_low)
    npv_high = npv_at_rate(r_high)

    if npv_low < 0:
        return None  # Even at very low rate, NPV is negative
    if npv_high > 0:
        r_high = 0.5  # Expand search

    for _ in range(max_iterations):
        r_mid = (r_low + r_high) / 2
        npv_mid = npv_at_rate(r_mid)

        if abs(npv_mid) < tolerance:
            return r_mid

        if npv_mid > 0:
            r_low = r_mid
        else:
            r_high = r_mid

        if r_high - r_low < tolerance / 100:
            break

    return (r_low + r_high) / 2


def compute_annual_irr(
    total_cost: float,
    annual_cash_flows: List[float],
    tolerance: float = 1e-6,
    max_iterations: int = 100,
) -> Optional[float]:
    """
    Compute IRR on annual cash flows.

    Args:
        total_cost: Initial investment (positive number)
        annual_cash_flows: List of annual cash inflows (years 1-10)

    Returns:
        Annual IRR as decimal (e.g., 0.15 for 15%), or None if no solution
    """
    if total_cost <= 0:
        return None

    total_cf = sum(annual_cash_flows)
    if total_cf <= total_cost:
        return None

    # Binary search for annual IRR
    r_low = -0.50
    r_high = 2.0  # 200% = very high

    def npv_at_rate(r: float) -> float:
        if r <= -1:
            return float('inf')
        pv = 0.0
        for year, cf in enumerate(annual_cash_flows, start=1):
            pv += cf / ((1 + r) ** year)
        return pv - total_cost

    for _ in range(max_iterations):
        r_mid = (r_low + r_high) / 2
        npv_mid = npv_at_rate(r_mid)

        if abs(npv_mid) < tolerance:
            return r_mid

        if npv_mid > 0:
            r_low = r_mid
        else:
            r_high = r_mid

        if r_high - r_low < tolerance / 100:
            break

    return (r_low + r_high) / 2


def solve_max_cost_for_irr(
    target_irr: float,
    annual_cash_flows: List[float],
) -> float:
    """
    Find maximum cost that achieves target IRR.

    At IRR = target: NPV = 0
    cost = sum(cf_t / (1 + target)^t)

    Args:
        target_irr: Target annual IRR (e.g., 0.15)
        annual_cash_flows: Annual label cash inflows

    Returns:
        Maximum cost for target IRR
    """
    if target_irr <= -1:
        return 0.0

    pv = 0.0
    for year, cf in enumerate(annual_cash_flows, start=1):
        pv += cf / ((1 + target_irr) ** year)

    return max(0.0, pv)


def generate_weekly_gross_series(
    year1_total_rev: float,
    decay_multipliers: dict,
    num_years: int = 10,
) -> List[float]:
    """
    Generate weekly gross revenue series from annual totals.

    Distributes each year's revenue evenly across 52 weeks.

    Args:
        year1_total_rev: Year 1 total gross revenue
        decay_multipliers: {year: multiplier} dict
        num_years: Number of years

    Returns:
        List of 520 weekly gross revenues
    """
    weekly_series = []

    for year in range(1, num_years + 1):
        multiplier = decay_multipliers.get(year, 0.0)
        year_total = year1_total_rev * multiplier
        weekly_rev = year_total / 52.0

        for _ in range(52):
            weekly_series.append(weekly_rev)

    return weekly_series


@dataclass
class PaybackRecommendation:
    """Payback-based (18-month) recommendation."""

    payback_horizon_weeks: int
    max_total_cost: float
    suggested_advance: float
    suggested_marketing: float
    implied_irr: Optional[float]  # Annual IRR at this cost
    recoup_week: Optional[int]  # Should be <= horizon if achievable


@dataclass
class IRRRecommendation:
    """IRR-based recommendation."""

    target_irr: float
    max_total_cost: float
    suggested_advance: float
    suggested_marketing: float
    recoup_week: Optional[int]  # Informational
    npv_at_10_percent: float


def compute_payback_recommendation(
    weekly_gross_series: List[float],
    annual_cash_flows_base: List[float],  # Without recoup (for IRR calc)
    deal_pct: float,
    advance_share_pct: float,
    marketing_recoupable: bool,
    payback_horizon_weeks: int = 78,
    deal_type: Optional[DealType] = None,
) -> PaybackRecommendation:
    """
    Compute the payback-based recommendation.

    max_cost = maximum cost that can be recouped by week 78.
    implied_irr = IRR at that cost.

    The max_cost varies by deal type based on recoupment mechanics.
    """
    # Find max cost for payback (varies by deal type)
    max_cost = compute_payback_max_cost(
        weekly_gross_series=weekly_gross_series,
        deal_pct=deal_pct,
        advance_share_pct=advance_share_pct,
        marketing_recoupable=marketing_recoupable,
        payback_horizon_weeks=payback_horizon_weeks,
        deal_type=deal_type,
    )

    # Get recoup week at max cost
    recoup_week = compute_recoup_week(
        weekly_gross_series=weekly_gross_series,
        deal_pct=deal_pct,
        total_cost=max_cost,
        advance_share_pct=advance_share_pct,
        marketing_recoupable=marketing_recoupable,
    )

    # Compute implied IRR using annual cash flows with recoup
    # Need to generate cash flows AT this cost level
    cf_result = compute_weekly_cashflows(
        weekly_gross_series=weekly_gross_series,
        deal_pct=deal_pct,
        total_cost=max_cost,
        advance_share_pct=advance_share_pct,
        marketing_recoupable=marketing_recoupable,
    )

    # Convert to annual for IRR calculation
    annual_cash_flows = []
    for year in range(10):
        start_idx = year * 52
        end_idx = start_idx + 52
        year_total = sum(cf_result.weekly_label_cash_in[start_idx:end_idx])
        annual_cash_flows.append(year_total)

    implied_irr = compute_annual_irr(max_cost, annual_cash_flows) if max_cost > 0 else None

    return PaybackRecommendation(
        payback_horizon_weeks=payback_horizon_weeks,
        max_total_cost=max_cost,
        suggested_advance=max_cost * advance_share_pct,
        suggested_marketing=max_cost * (1 - advance_share_pct),
        implied_irr=implied_irr,
        recoup_week=recoup_week,
    )


def compute_irr_recommendation(
    target_irr: float,
    weekly_gross_series: List[float],
    annual_cash_flows_base: List[float],  # Base split (no recoup)
    deal_pct: float,
    advance_share_pct: float,
    marketing_recoupable: bool,
    deal_type: Optional[DealType] = None,
    annual_gross: Optional[List[float]] = None,  # Gross revenue by year (for profit split calc)
) -> IRRRecommendation:
    """
    Compute IRR-based recommendation (no payback constraint).

    For Distribution and Royalty deals:
        max_cost = PV of base cash flows at target IRR
        (Conservative estimate - actual IRR will be higher due to recoupment)

    For Profit Split deals:
        max_cost = Iteratively solved so that actual IRR = target
        (Accounts for expense deduction reducing net profit)

    recoup_week = informational payback timing.
    """
    # For ALL deal types, find the investment where actual IRR = target IRR
    # Each deal type has different cash flow mechanics

    if annual_gross is not None and deal_type is not None:
        total_gross = sum(annual_gross)

        # Binary search for the investment that gives exactly target IRR
        cost_low = 0.0
        cost_high = total_gross  # Safe upper limit
        tolerance = 100.0  # $100 tolerance
        max_cost = 0.0

        for _ in range(100):
            cost_mid = (cost_low + cost_high) / 2

            if deal_type == DealType.ROYALTY:
                # ROYALTY: Label gets fixed % of gross forever, NO recoupment
                # Label CF = Gross × Royalty% (deal_pct is the royalty rate)
                # Advance is just Year 0 outflow
                actual_cf = [gross_y * deal_pct for gross_y in annual_gross]

            elif deal_type == DealType.PROFIT_SPLIT:
                # PROFIT SPLIT: Expenses PERMANENTLY reduce value
                # Net = Gross - Expenses, Label CF = Net × Split%
                actual_cf = []
                for gross_y in annual_gross:
                    expense_y = cost_mid * (gross_y / total_gross) if total_gross > 0 else 0
                    net_profit_y = max(0, gross_y - expense_y)
                    label_cf_y = net_profit_y * deal_pct
                    actual_cf.append(label_cf_y)

            else:  # DISTRIBUTION (Funded Distribution)
                # FUNDED DISTRIBUTION: 100% during recoup, then split%
                # Label gets ALL gross until recouped, then post-recoup share
                actual_cf = []
                unrecouped = cost_mid
                for gross_y in annual_gross:
                    if unrecouped > 0:
                        # Still recouping: Label gets 100%
                        unrecouped -= gross_y
                        label_cf_y = gross_y
                    else:
                        # Post-recoup: Label gets their share
                        label_cf_y = gross_y * deal_pct
                    actual_cf.append(label_cf_y)

            # Calculate IRR at this cost
            test_irr = compute_annual_irr(cost_mid, actual_cf) if cost_mid > 0 else None

            if test_irr is None:
                # Can't achieve positive IRR, reduce cost
                cost_high = cost_mid
            elif test_irr > target_irr:
                # IRR too high, can increase cost
                cost_low = cost_mid
                max_cost = cost_mid
            else:
                # IRR too low, reduce cost
                cost_high = cost_mid

            if cost_high - cost_low < tolerance:
                break

        # Use the found max_cost
        max_cost = max_cost if max_cost > 0 else cost_low
    else:
        # Fallback: use base cash flows (if no deal type info provided)
        max_cost = solve_max_cost_for_irr(target_irr, annual_cash_flows_base)

    # Recoup week at this cost (informational)
    recoup_week = compute_recoup_week(
        weekly_gross_series=weekly_gross_series,
        deal_pct=deal_pct,
        total_cost=max_cost,
        advance_share_pct=advance_share_pct,
        marketing_recoupable=marketing_recoupable,
    )

    # NPV at 10% discount rate
    npv_10 = 0.0
    for year, cf in enumerate(annual_cash_flows_base, start=1):
        npv_10 += cf / ((1 + 0.10) ** year)
    npv_10 -= max_cost

    return IRRRecommendation(
        target_irr=target_irr,
        max_total_cost=max_cost,
        suggested_advance=max_cost * advance_share_pct,
        suggested_marketing=max_cost * (1 - advance_share_pct),
        recoup_week=recoup_week,
        npv_at_10_percent=npv_10,
    )
