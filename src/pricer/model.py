"""
Financial model for music catalog deal pricing.

Implements cash flow projections, recoupment waterfall, and IRR/NPV calculations.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class DealType(Enum):
    """Types of deal structures."""

    DISTRIBUTION = "distribution"
    PROFIT_SPLIT = "profit_split"
    ROYALTY = "royalty"


@dataclass
class DealInputs:
    """User inputs for deal analysis."""

    # Core inputs
    genre: str
    weekly_audio: float
    weekly_video: float
    catalog_tracks: int
    extra_tracks: int = 0

    # Market shares for audio (country -> share)
    market_shares: Dict[str, float] = field(default_factory=dict)

    # Deal structure
    deal_type: DealType = DealType.DISTRIBUTION
    deal_percent: float = 0.25  # 25% default
    marketing_recoupable: bool = False
    advance_share: float = 0.70  # 70% of total cost as advance

    # Rate calculation mode
    rest_audio_mode: str = "avg"  # "avg" or "us"

    # Decay mode: "weekly" (default, more accurate) or "annual" (legacy)
    decay_mode: str = "weekly"

    # Weeks post-peak offset for shifted decay curve
    # If weeks_post_peak = k, user's current weekly streams correspond to model week (1+k).
    # This prevents double-decay by anchoring at the shifted week.
    # See pricer/decay_curve.py for full explanation.
    weeks_post_peak: int = 0


@dataclass
class RateInputs:
    """Calculated rate inputs."""

    blended_audio_rate: float
    video_rate: float
    decay_multipliers: Dict[int, float]
    weekly_rates: Optional[List[float]] = None  # 52 week-over-week rates for Year 1


@dataclass
class YearlyProjection:
    """Projection data for a single year."""

    year: int
    multiplier: float
    gross_revenue: float
    label_cash_in: float
    artist_pay: float
    discounted_cash_in_7_5: float  # Discounted at 7.5%


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
    """IRR-based recommendation (no payback constraint)."""

    target_irr: float
    max_total_cost: float
    suggested_advance: float
    suggested_marketing: float
    recoup_week: Optional[int]  # Informational - when payback occurs
    npv_at_10_percent: float


@dataclass
class AnalysisResult:
    """Complete analysis result."""

    # Inputs summary
    inputs: DealInputs

    # Computed values
    effective_weekly_audio: float
    effective_weekly_video: float
    year1_audio_rev: float
    year1_video_rev: float
    year1_total_rev: float
    blended_audio_rate: float
    video_rate: float

    # Market breakdown
    market_breakdown: Dict[str, Tuple[float, float]]  # country -> (share, rate)
    rest_of_world_share: float
    rest_of_world_rate: float

    # Yearly projections
    projections: List[YearlyProjection]

    # Recommendations - TWO separate sections
    payback_recommendation: PaybackRecommendation  # 18-month payback based
    irr_recommendations: List[IRRRecommendation]  # 10% and 15% IRR based


def compute_label_share(deal_type: DealType, deal_percent: float) -> float:
    """
    Compute the label's base share of gross revenue.

    Args:
        deal_type: Type of deal
        deal_percent: The deal percentage parameter

    Returns:
        Label's share of gross revenue (0-1)
    """
    if deal_type == DealType.DISTRIBUTION:
        # Distribution fee: label keeps deal_percent
        return deal_percent
    elif deal_type == DealType.PROFIT_SPLIT:
        # Profit split on revenue: label keeps deal_percent
        return deal_percent
    elif deal_type == DealType.ROYALTY:
        # Royalty deal: artist gets deal_percent, label keeps the rest
        return 1.0 - deal_percent
    else:
        raise ValueError(f"Unknown deal type: {deal_type}")


def compute_pv(cash_flows: List[float], discount_rate: float) -> float:
    """
    Compute present value of cash flows.

    Args:
        cash_flows: List of cash flows for years 1..N (no year 0)
        discount_rate: Discount rate (e.g., 0.10 for 10%)

    Returns:
        Present value
    """
    pv = 0.0
    for year, cf in enumerate(cash_flows, start=1):
        pv += cf / ((1 + discount_rate) ** year)
    return pv


def compute_npv(
    initial_cost: float, cash_flows: List[float], discount_rate: float
) -> float:
    """
    Compute net present value.

    Args:
        initial_cost: Time-0 cash outflow (positive number)
        cash_flows: List of cash flows for years 1..N
        discount_rate: Discount rate

    Returns:
        NPV
    """
    return -initial_cost + compute_pv(cash_flows, discount_rate)


def compute_max_cost_for_irr(cash_flows: List[float], target_irr: float) -> float:
    """
    Compute maximum total deal cost that achieves target IRR.

    For IRR = target, we need:
    -COST + PV(cash_flows, target) = 0
    Therefore: COST = PV(cash_flows, target)

    Args:
        cash_flows: Label cash inflows for years 1..10
        target_irr: Target IRR (e.g., 0.15 for 15%)

    Returns:
        Maximum deal cost
    """
    return compute_pv(cash_flows, target_irr)


class CashFlowEngine:
    """
    Computes cash flows for different deal types.

    DEAL TYPE MECHANICS (CORRECT):

    1. ROYALTY DEAL:
       - Label gets fixed % of gross revenue forever
       - NO recoupment waterfall
       - Advance is just Year 0 outflow, not recouped from revenue stream
       - Label CF = Gross × Royalty%

    2. FUNDED DISTRIBUTION DEAL:
       - Label gets 100% of gross UNTIL fully recouped
       - AFTER recoup: Label gets post-recoup share %
       - Expenses affect TIMING only, not lifetime value
       - Label CF = 100% while unrecouped, then Post_Recoup_Share%

    3. PROFIT SPLIT:
       - Expenses PERMANENTLY reduce value (deducted from gross)
       - Net Profit = Gross - Expenses
       - Label CF = Net × Split%
       - No 100% recoup period

    Expected IRR ranking (same revenue): Royalty ≥ Funded Distribution >> Profit Split
    """

    def __init__(
        self,
        year1_total_rev: float,
        decay_multipliers: Dict[int, float],
        label_share: float,
        marketing_recoupable: bool = False,
        total_deal_cost: Optional[float] = None,
        deal_type: Optional[DealType] = None,
    ):
        """
        Initialize cash flow engine.

        Args:
            year1_total_rev: Year 1 gross revenue
            decay_multipliers: {year: multiplier} for years 1-10
            label_share: Meaning depends on deal type:
                - ROYALTY: Label's royalty rate (e.g., 0.20 for 20%)
                - DISTRIBUTION: Label's POST-RECOUP share (e.g., 0.30 for 30%)
                - PROFIT_SPLIT: Label's share of net profits (e.g., 0.50 for 50%)
            marketing_recoupable: Whether marketing costs are recoupable (Distribution only)
            total_deal_cost: Total investment (advance + marketing + recording)
            deal_type: Type of deal structure
        """
        self.year1_total_rev = year1_total_rev
        self.decay_multipliers = decay_multipliers
        self.label_share = label_share
        self.artist_share = 1.0 - label_share
        self.marketing_recoupable = marketing_recoupable
        self.total_deal_cost = total_deal_cost or 0.0
        self.deal_type = deal_type or DealType.DISTRIBUTION

    def compute_yearly_revenues(self) -> List[Tuple[int, float, float]]:
        """
        Compute gross revenue and multiplier for each year.

        Returns:
            List of (year, multiplier, gross_revenue) tuples
        """
        results = []
        for year in range(1, 11):
            multiplier = self.decay_multipliers.get(year, 0.0)
            gross_rev = self.year1_total_rev * multiplier
            results.append((year, multiplier, gross_rev))
        return results

    def compute_cash_flows_no_recoup(
        self,
    ) -> List[Tuple[int, float, float, float, float]]:
        """
        Compute steady-state cash flows (no recoupment effects).

        For ROYALTY: This IS the correct cash flow (no recoupment ever)
        For DISTRIBUTION: This is post-recoup steady state
        For PROFIT_SPLIT: This is pre-expense steady state

        Returns:
            List of (year, multiplier, gross_rev, label_cash_in, artist_pay) tuples
        """
        results = []
        for year, multiplier, gross_rev in self.compute_yearly_revenues():
            label_cash_in = gross_rev * self.label_share
            artist_pay = gross_rev * self.artist_share
            results.append((year, multiplier, gross_rev, label_cash_in, artist_pay))
        return results

    def compute_cash_flows_with_recoup(
        self, total_cost: float
    ) -> List[Tuple[int, float, float, float, float]]:
        """
        Compute cash flows with deal-specific mechanics.

        Args:
            total_cost: Total deal cost (advance + marketing + recording)

        Returns:
            List of (year, multiplier, gross_rev, label_cash_in, artist_pay) tuples
        """
        if self.deal_type == DealType.ROYALTY:
            return self._compute_royalty_cash_flows()
        elif self.deal_type == DealType.PROFIT_SPLIT:
            return self._compute_profit_split_cash_flows(total_cost)
        else:  # DISTRIBUTION (Funded Distribution)
            return self._compute_funded_distribution_cash_flows(total_cost)

    def _compute_royalty_cash_flows(
        self,
    ) -> List[Tuple[int, float, float, float, float]]:
        """
        Compute cash flows for ROYALTY deal.

        Royalty Deal Logic:
        - Label receives fixed royalty % of gross revenue FOREVER
        - NO recoupment waterfall
        - Advance is Year 0 outflow, not recouped from this stream
        - Label CF_t = Gross_t × Royalty%

        This is the simplest deal type. Label participates at fixed rate forever.
        """
        results = []
        for year, multiplier, gross_rev in self.compute_yearly_revenues():
            # Label always gets their royalty percentage
            label_cash_in = gross_rev * self.label_share
            artist_pay = gross_rev * self.artist_share
            results.append((year, multiplier, gross_rev, label_cash_in, artist_pay))
        return results

    def _compute_funded_distribution_cash_flows(
        self, total_cost: float
    ) -> List[Tuple[int, float, float, float, float]]:
        """
        Compute cash flows for FUNDED DISTRIBUTION deal.

        Funded Distribution Logic:
        - Label funds advance + recording + marketing
        - Label gets 100% of gross UNTIL fully recouped
        - AFTER recoup: Label gets post-recoup share (e.g., 30%)
        - Artist gets 0% during recoup, then their share (e.g., 70%)
        - Expenses affect TIMING only, not lifetime value

        This is NOT a profit split! The label gets 100% during recoup,
        not "their share + withheld".
        """
        results = []
        unrecouped = total_cost

        for year, multiplier, gross_rev in self.compute_yearly_revenues():
            if unrecouped > 0:
                # Still recouping: Label gets 100% of gross
                amount_to_recoup = min(gross_rev, unrecouped)
                unrecouped -= amount_to_recoup

                # Label gets 100% until recouped
                label_cash_in = gross_rev
                artist_pay = 0.0
            else:
                # Fully recouped: Normal split applies
                label_cash_in = gross_rev * self.label_share
                artist_pay = gross_rev * self.artist_share

            results.append((year, multiplier, gross_rev, label_cash_in, artist_pay))

        return results

    def _compute_profit_split_cash_flows(
        self, total_cost: float
    ) -> List[Tuple[int, float, float, float, float]]:
        """
        Compute cash flows for TRUE PROFIT SPLIT deal.

        Profit Split Logic:
        - Gross revenue comes in
        - Expenses are PERMANENTLY deducted (destroy value)
        - Net Profit = Gross - Expenses
        - Net Profit is split according to deal percentage
        - NO 100% recoup period

        This is the weakest deal type for the label.
        Expenses spread proportionally across years based on revenue share.
        """
        results = []
        yearly_revenues = self.compute_yearly_revenues()
        total_revenue = sum(gross for _, _, gross in yearly_revenues)

        for year, multiplier, gross_rev in yearly_revenues:
            # Allocate expenses proportionally to this year's revenue
            if total_revenue > 0:
                year_expense = (gross_rev / total_revenue) * total_cost
            else:
                year_expense = total_cost / 10.0

            # Net profit after expense deduction
            net_profit = max(0, gross_rev - year_expense)

            # Split net profit
            label_cash_in = net_profit * self.label_share
            artist_pay = net_profit * self.artist_share

            results.append((year, multiplier, gross_rev, label_cash_in, artist_pay))

        return results

    def get_label_cash_flows(
        self, total_cost: Optional[float] = None, advance_amount: Optional[float] = None
    ) -> List[float]:
        """
        Get label cash inflows for years 1-10.

        Recoupment logic:
        - Advance is ALWAYS recouped from artist's share
        - Marketing is only recouped if marketing_recoupable=True

        Args:
            total_cost: Total deal cost (advance + marketing)
            advance_amount: Amount of advance (always recoupable)

        Returns:
            List of label cash inflows for years 1-10
        """
        cost = total_cost if total_cost is not None else self.total_deal_cost
        advance = advance_amount if advance_amount is not None else cost  # Default: all is advance

        if self.marketing_recoupable:
            # Recoup both advance AND marketing
            recoup_amount = cost
        else:
            # Only recoup the advance
            recoup_amount = advance

        if recoup_amount > 0:
            flows = self.compute_cash_flows_with_recoup(recoup_amount)
        else:
            flows = self.compute_cash_flows_no_recoup()

        return [f[3] for f in flows]  # label_cash_in


def analyze_deal(
    inputs: DealInputs, rate_inputs: RateInputs, ppu_loader=None
) -> AnalysisResult:
    """
    Perform complete deal analysis.

    IMPORTANT: The decay_multipliers are CUMULATIVE multipliers (relative to Year 1).
    They are NOT per-year decay rates to compound!

    Correct usage:
        gross_revenue[y] = year1_revenue * multiplier[y]

    WEEKS_POST_PEAK OFFSET:
    -----------------------
    If weeks_post_peak > 0, we use the shifted decay curve (pricer/decay_curve.py):
    - We anchor at week (1 + weeks_post_peak), not week 1
    - This prevents double-decay when the catalog is already post-peak
    - Year 1..10 represent the NEXT 10 years from TODAY, not "since peak"

    Args:
        inputs: User deal inputs
        rate_inputs: Calculated rate inputs (with cumulative multipliers from Excel)
        ppu_loader: Optional PPULoader for market breakdown (can be None)

    Returns:
        Complete analysis result
    """
    # Validate weeks_post_peak
    if inputs.weeks_post_peak < 0:
        raise ValueError(f"weeks_post_peak must be >= 0, got {inputs.weeks_post_peak}")

    # Compute mean streams per track
    mean_audio_per_track = inputs.weekly_audio / inputs.catalog_tracks
    mean_video_per_track = inputs.weekly_video / inputs.catalog_tracks

    # Effective weekly streams
    eff_weekly_audio = inputs.weekly_audio + inputs.extra_tracks * mean_audio_per_track
    eff_weekly_video = inputs.weekly_video + inputs.extra_tracks * mean_video_per_track

    # Compute label share
    label_share = compute_label_share(inputs.deal_type, inputs.deal_percent)

    # Choose decay mode
    if inputs.decay_mode == "weekly" and rate_inputs.weekly_rates and inputs.weeks_post_peak > 0:
        # =====================================================================
        # SHIFTED DECAY CURVE MODE (weeks_post_peak > 0)
        # =====================================================================
        # Use the new shifted curve engine to prevent double-decay.
        # This anchors at week (1 + k) where k = weeks_post_peak.
        # Year 1..10 are the NEXT 10 years from today (shifted windows).
        from .decay_curve import build_shifted_curve

        shifted_result = build_shifted_curve(
            wow_rates=rate_inputs.weekly_rates,
            excel_multipliers=rate_inputs.decay_multipliers,
            weeks_post_peak=inputs.weeks_post_peak,
            current_weekly_audio_streams=eff_weekly_audio,
            current_weekly_video_streams=eff_weekly_video,
            blended_audio_rate=rate_inputs.blended_audio_rate,
            video_rate=rate_inputs.video_rate,
        )

        # Year 1 revenue from shifted curve (already computed with proper anchoring)
        year1_total_rev = shifted_result.shifted_annual_totals[1]
        year1_audio_rev = shifted_result.shifted_annual_revenues_audio[1]
        year1_video_rev = shifted_result.shifted_annual_revenues_video[1]

        # Use shifted multipliers for the engine
        decay_multipliers_for_engine = shifted_result.shifted_annual_multipliers

        engine = CashFlowEngine(
            year1_total_rev=year1_total_rev,
            decay_multipliers=decay_multipliers_for_engine,
            label_share=label_share,
            marketing_recoupable=inputs.marketing_recoupable,
            deal_type=inputs.deal_type,
        )

    elif inputs.decay_mode == "weekly":
        # =====================================================================
        # STANDARD WEEKLY DECAY MODE (weeks_post_peak = 0 or no weekly rates)
        # =====================================================================
        # Weekly decay: Build a weekly curve that matches the Excel annual multipliers
        # This provides more accurate intra-year cash flow timing
        from .decay_weekly import build_weekly_curve, build_weekly_curve_with_rates

        # Week 0 revenue = user's WEEKLY revenue (streams x rate)
        # NOT the annualized total divided by weeks!
        week0_revenue = (eff_weekly_audio * rate_inputs.blended_audio_rate +
                         eff_weekly_video * rate_inputs.video_rate)

        if rate_inputs.weekly_rates:
            # Use explicit weekly rates from Excel for Year 1
            # Year 1 total = sum of weeks 0-52 with decay applied
            weekly_result = build_weekly_curve_with_rates(
                week0_revenue=week0_revenue,
                weekly_rates=rate_inputs.weekly_rates,
                excel_multipliers=rate_inputs.decay_multipliers,
            )
            # Update year1 values to reflect decay within Year 1
            year1_total_rev = weekly_result.year1_total
        else:
            # Fall back to flat Year 1 (no weekly rates available)
            weekly_result = build_weekly_curve(
                week1_revenue=week0_revenue,
                excel_multipliers=rate_inputs.decay_multipliers,
            )
            year1_total_rev = weekly_result.year1_total

        # Base annualized revenue (Year 1, before decay) - for audio/video split
        base_annual_audio_rev = eff_weekly_audio * 52 * rate_inputs.blended_audio_rate
        base_annual_video_rev = eff_weekly_video * 52 * rate_inputs.video_rate
        year1_audio_rev = base_annual_audio_rev
        year1_video_rev = base_annual_video_rev

        # The weekly curve produces annual revenues that match Excel multipliers
        # Use the annual_multipliers from the weekly result for the engine
        decay_multipliers_for_engine = weekly_result.annual_multipliers

        engine = CashFlowEngine(
            year1_total_rev=year1_total_rev,
            decay_multipliers=decay_multipliers_for_engine,
            label_share=label_share,
            marketing_recoupable=inputs.marketing_recoupable,
            deal_type=inputs.deal_type,
        )

    else:
        # =====================================================================
        # ANNUAL DECAY MODE (legacy)
        # =====================================================================
        # Annual decay: Apply Excel cumulative multipliers directly
        # gross_revenue[y] = year1_revenue * multiplier[y]
        # NO compounding! The multipliers are already cumulative.

        # Base annualized revenue (Year 1, before decay)
        base_annual_audio_rev = eff_weekly_audio * 52 * rate_inputs.blended_audio_rate
        base_annual_video_rev = eff_weekly_video * 52 * rate_inputs.video_rate
        year1_total_rev = base_annual_audio_rev + base_annual_video_rev
        year1_audio_rev = base_annual_audio_rev
        year1_video_rev = base_annual_video_rev

        engine = CashFlowEngine(
            year1_total_rev=year1_total_rev,
            decay_multipliers=rate_inputs.decay_multipliers,
            label_share=label_share,
            marketing_recoupable=inputs.marketing_recoupable,
            deal_type=inputs.deal_type,
        )

    # Get base cash flows (steady-state split, no recoupment)
    base_cash_flows = engine.compute_cash_flows_no_recoup()

    # Get label inflows for PV calculations (base split) - annual
    label_inflows_base = [f[3] for f in base_cash_flows]

    # Generate weekly gross series for payback calculations
    from .payback import (
        generate_weekly_gross_series,
        compute_payback_recommendation,
        compute_irr_recommendation,
        DealType as PaybackDealType,
    )

    weekly_gross_series = generate_weekly_gross_series(
        year1_total_rev=year1_total_rev,
        decay_multipliers=engine.decay_multipliers,
        num_years=10,
    )

    # Map model DealType to payback DealType
    payback_deal_type_map = {
        DealType.DISTRIBUTION: PaybackDealType.DISTRIBUTION,
        DealType.PROFIT_SPLIT: PaybackDealType.PROFIT_SPLIT,
        DealType.ROYALTY: PaybackDealType.ROYALTY,
    }
    payback_deal_type = payback_deal_type_map.get(inputs.deal_type, PaybackDealType.DISTRIBUTION)

    # =========================================================================
    # SECTION 1: PAYBACK-BASED RECOMMENDATION (18 months)
    # =========================================================================
    # Max cost that can be recouped by week 78 (varies by deal type)
    payback_rec = compute_payback_recommendation(
        weekly_gross_series=weekly_gross_series,
        annual_cash_flows_base=label_inflows_base,
        deal_pct=label_share,
        advance_share_pct=inputs.advance_share,
        marketing_recoupable=inputs.marketing_recoupable,
        payback_horizon_weeks=78,
        deal_type=payback_deal_type,
    )

    payback_recommendation = PaybackRecommendation(
        payback_horizon_weeks=payback_rec.payback_horizon_weeks,
        max_total_cost=payback_rec.max_total_cost,
        suggested_advance=payback_rec.suggested_advance,
        suggested_marketing=payback_rec.suggested_marketing,
        implied_irr=payback_rec.implied_irr,
        recoup_week=payback_rec.recoup_week,
    )

    # =========================================================================
    # SECTION 2: IRR-BASED RECOMMENDATIONS (10% and 15%)
    # =========================================================================
    # Max cost for target IRR (NO payback constraint)
    # For Profit Split, need annual gross to properly calculate expense impact
    annual_gross = [cf[2] for cf in base_cash_flows]  # gross_revenue per year

    target_irrs = [0.10, 0.15]
    irr_recommendations = []

    for target_irr in target_irrs:
        irr_rec = compute_irr_recommendation(
            target_irr=target_irr,
            weekly_gross_series=weekly_gross_series,
            annual_cash_flows_base=label_inflows_base,
            deal_pct=label_share,
            advance_share_pct=inputs.advance_share,
            marketing_recoupable=inputs.marketing_recoupable,
            deal_type=payback_deal_type,
            annual_gross=annual_gross,
        )

        irr_recommendations.append(
            IRRRecommendation(
                target_irr=irr_rec.target_irr,
                max_total_cost=irr_rec.max_total_cost,
                suggested_advance=irr_rec.suggested_advance,
                suggested_marketing=irr_rec.suggested_marketing,
                recoup_week=irr_rec.recoup_week,
                npv_at_10_percent=irr_rec.npv_at_10_percent,
            )
        )

    # For projections display, use the 15% IRR recommendation as reference
    # Show cash flows WITH recoupment waterfall
    rec_15 = irr_recommendations[1]  # 15% IRR recommendation
    if inputs.marketing_recoupable:
        display_recoup = rec_15.max_total_cost
    else:
        display_recoup = rec_15.suggested_advance

    display_cash_flows = engine.compute_cash_flows_with_recoup(display_recoup)

    # Create yearly projections (with recoupment)
    projections = []
    for year, multiplier, gross_rev, label_cash_in, artist_pay in display_cash_flows:
        discounted = label_cash_in / ((1 + 0.075) ** year)
        projections.append(
            YearlyProjection(
                year=year,
                multiplier=multiplier,
                gross_revenue=gross_rev,
                label_cash_in=label_cash_in,
                artist_pay=artist_pay,
                discounted_cash_in_7_5=discounted,
            )
        )

    # Build market breakdown
    market_breakdown = {}
    rest_share = 1.0 - sum(inputs.market_shares.values())
    rest_rate = 0.0

    if ppu_loader:
        for country, share in inputs.market_shares.items():
            try:
                rate = ppu_loader.get_audio_rate(country)
                market_breakdown[country] = (share, rate)
            except ValueError:
                market_breakdown[country] = (share, 0.0)

        if inputs.rest_audio_mode == "us":
            try:
                rest_rate = ppu_loader.get_audio_rate("USA")
            except ValueError:
                rest_rate = ppu_loader.get_average_audio_rate()
        else:
            rest_rate = ppu_loader.get_average_audio_rate()

    return AnalysisResult(
        inputs=inputs,
        effective_weekly_audio=eff_weekly_audio,
        effective_weekly_video=eff_weekly_video,
        year1_audio_rev=year1_audio_rev,
        year1_video_rev=year1_video_rev,
        year1_total_rev=year1_total_rev,
        blended_audio_rate=rate_inputs.blended_audio_rate,
        video_rate=rate_inputs.video_rate,
        market_breakdown=market_breakdown,
        rest_of_world_share=rest_share,
        rest_of_world_rate=rest_rate,
        projections=projections,
        payback_recommendation=payback_recommendation,
        irr_recommendations=irr_recommendations,
    )
