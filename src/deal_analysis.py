"""
Unified facade for deal analysis - combines pricer and projector functionality.

This module provides a simplified interface for running deal analysis,
bringing together Deal Calc 2 pricing recommendations and Deal Simulator projections.

Supports two analysis modes:
1. Aggregate mode (legacy): All tracks decay uniformly from a single weeks_post_peak
2. Track-level mode (new): Each track decays individually based on its release date
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from .pricer import (
    DecayLoader,
    PPULoader,
    DealType as PricerDealType,
    DealInputs,
    RateInputs,
    AnalysisResult,
    analyze_deal,
)
from .pricer.decay_curve import build_unshifted_level_curve, extend_curve_beyond_520
from .projector import (
    NPVCalculator,
    create_distribution_deal,
    create_royalty_deal,
)
from .models import TrackData

logger = logging.getLogger(__name__)

# Default paths to data files
DATA_DIR = Path(__file__).parent.parent / "data" / "deal_calc"
DEFAULT_DECAY_PATH = DATA_DIR / "decay_model.xlsx"
DEFAULT_PPU_PATH = DATA_DIR / "ppu_rates.xlsx"

# Default discount rate for NPV calculations
DEFAULT_DISCOUNT_RATE = 0.10

# Available genres
AVAILABLE_GENRES = [
    "Pop",
    "Urban",
    "Rock",
    "Dance, Electronic, Electronica",
    "Singer/Songwriter",
    "J-Pop & K-Pop",
]

# Deal type mappings
DEAL_TYPE_MAP = {
    "distribution": PricerDealType.DISTRIBUTION,
    "profit_split": PricerDealType.PROFIT_SPLIT,
    "royalty": PricerDealType.ROYALTY,
}


@dataclass
class DealAnalysisRequest:
    """Request parameters for deal analysis."""

    # Artist identification
    artist_id: str
    artist_name: str

    # Streaming data (used in aggregate mode or as fallback)
    weekly_audio_streams: float
    weekly_video_streams: float

    # Catalog info
    catalog_track_count: int
    genre: str

    # Deal structure
    deal_type: str  # "distribution", "profit_split", "royalty"
    deal_percent: float  # Label's share (e.g., 0.25 for 25%)

    # Fields with defaults must come last
    extra_tracks: int = 0  # New songs owed in the deal
    market_shares: Dict[str, float] = field(default_factory=lambda: {"US": 0.50, "UK": 0.10})
    advance_share: float = 0.70  # Portion of total cost as advance
    marketing_recoupable: bool = False
    weeks_post_peak: int = 0  # For shifted decay curve (aggregate mode only)

    # Track-level decay mode
    use_track_level_decay: bool = True  # Enable individual track decay
    track_data: Optional[List[TrackData]] = None  # Track catalog data (auto-fetched if None)


@dataclass
class PricingRecommendation:
    """Pricing recommendation from Deal Calc."""

    # 18-month payback recommendation
    payback_max_cost: float
    payback_advance: float
    payback_marketing: float
    payback_implied_irr: Optional[float]
    payback_recoup_week: Optional[int]

    # IRR-based recommendations
    irr_10_max_cost: float
    irr_10_advance: float
    irr_15_max_cost: float
    irr_15_advance: float


@dataclass
class CashFlowProjection:
    """10-year cash flow projection."""

    years: List[int]
    gross_revenue: List[float]
    label_share: List[float]
    artist_pay: List[float]
    multipliers: List[float]


@dataclass
class LabelMetrics:
    """Label financial metrics."""

    label_npv: float
    label_irr: Optional[float]
    label_moic: Optional[float]
    label_payback_year: Optional[int]
    total_label_share: float


@dataclass
class DealAnalysisResult:
    """Complete deal analysis result."""

    # Request echo
    request: DealAnalysisRequest
    analysis_timestamp: str

    # Year 1 metrics
    year1_audio_revenue: float
    year1_video_revenue: float
    year1_total_revenue: float
    blended_audio_rate: float
    video_rate: float

    # Pricing recommendations
    pricing: PricingRecommendation

    # Cash flow projections
    cash_flow: CashFlowProjection

    # Label metrics (at 15% IRR cost)
    label_metrics: LabelMetrics

    # Serialization support
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request": {
                "artist_id": self.request.artist_id,
                "artist_name": self.request.artist_name,
                "weekly_audio_streams": self.request.weekly_audio_streams,
                "weekly_video_streams": self.request.weekly_video_streams,
                "catalog_track_count": self.request.catalog_track_count,
                "extra_tracks": self.request.extra_tracks,
                "genre": self.request.genre,
                "deal_type": self.request.deal_type,
                "deal_percent": self.request.deal_percent,
                "market_shares": self.request.market_shares,
                "advance_share": self.request.advance_share,
                "marketing_recoupable": self.request.marketing_recoupable,
                "weeks_post_peak": self.request.weeks_post_peak,
                "use_track_level_decay": self.request.use_track_level_decay,
            },
            "analysis_timestamp": self.analysis_timestamp,
            "year1_audio_revenue": self.year1_audio_revenue,
            "year1_video_revenue": self.year1_video_revenue,
            "year1_total_revenue": self.year1_total_revenue,
            "blended_audio_rate": self.blended_audio_rate,
            "video_rate": self.video_rate,
            "pricing": {
                "payback_max_cost": self.pricing.payback_max_cost,
                "payback_advance": self.pricing.payback_advance,
                "payback_marketing": self.pricing.payback_marketing,
                "payback_implied_irr": self.pricing.payback_implied_irr,
                "payback_recoup_week": self.pricing.payback_recoup_week,
                "irr_10_max_cost": self.pricing.irr_10_max_cost,
                "irr_10_advance": self.pricing.irr_10_advance,
                "irr_15_max_cost": self.pricing.irr_15_max_cost,
                "irr_15_advance": self.pricing.irr_15_advance,
            },
            "cash_flow": {
                "years": self.cash_flow.years,
                "gross_revenue": self.cash_flow.gross_revenue,
                "label_share": self.cash_flow.label_share,
                "artist_pay": self.cash_flow.artist_pay,
                "multipliers": self.cash_flow.multipliers,
            },
            "label_metrics": {
                "label_npv": self.label_metrics.label_npv,
                "label_irr": self.label_metrics.label_irr,
                "label_moic": self.label_metrics.label_moic,
                "label_payback_year": self.label_metrics.label_payback_year,
                "total_label_share": self.label_metrics.total_label_share,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DealAnalysisResult":
        """Create from dictionary."""
        req_data = data["request"]
        request = DealAnalysisRequest(
            artist_id=req_data["artist_id"],
            artist_name=req_data["artist_name"],
            weekly_audio_streams=req_data["weekly_audio_streams"],
            weekly_video_streams=req_data["weekly_video_streams"],
            catalog_track_count=req_data["catalog_track_count"],
            extra_tracks=req_data.get("extra_tracks", 0),
            genre=req_data["genre"],
            deal_type=req_data["deal_type"],
            deal_percent=req_data["deal_percent"],
            market_shares=req_data.get("market_shares", {"US": 0.50, "UK": 0.10}),
            advance_share=req_data.get("advance_share", 0.70),
            marketing_recoupable=req_data.get("marketing_recoupable", False),
            weeks_post_peak=req_data.get("weeks_post_peak", 0),
            use_track_level_decay=req_data.get("use_track_level_decay", True),
        )

        pricing_data = data["pricing"]
        pricing = PricingRecommendation(
            payback_max_cost=pricing_data["payback_max_cost"],
            payback_advance=pricing_data["payback_advance"],
            payback_marketing=pricing_data["payback_marketing"],
            payback_implied_irr=pricing_data.get("payback_implied_irr"),
            payback_recoup_week=pricing_data.get("payback_recoup_week"),
            irr_10_max_cost=pricing_data["irr_10_max_cost"],
            irr_10_advance=pricing_data["irr_10_advance"],
            irr_15_max_cost=pricing_data["irr_15_max_cost"],
            irr_15_advance=pricing_data["irr_15_advance"],
        )

        cf_data = data["cash_flow"]
        cash_flow = CashFlowProjection(
            years=cf_data["years"],
            gross_revenue=cf_data["gross_revenue"],
            label_share=cf_data["label_share"],
            artist_pay=cf_data["artist_pay"],
            multipliers=cf_data["multipliers"],
        )

        lm_data = data["label_metrics"]
        label_metrics = LabelMetrics(
            label_npv=lm_data["label_npv"],
            label_irr=lm_data.get("label_irr"),
            label_moic=lm_data.get("label_moic"),
            label_payback_year=lm_data.get("label_payback_year"),
            total_label_share=lm_data["total_label_share"],
        )

        return cls(
            request=request,
            analysis_timestamp=data["analysis_timestamp"],
            year1_audio_revenue=data["year1_audio_revenue"],
            year1_video_revenue=data["year1_video_revenue"],
            year1_total_revenue=data["year1_total_revenue"],
            blended_audio_rate=data["blended_audio_rate"],
            video_rate=data["video_rate"],
            pricing=pricing,
            cash_flow=cash_flow,
            label_metrics=label_metrics,
        )


def compute_track_level_revenues(
    tracks: List[TrackData],
    wow_rates: List[float],
    excel_multipliers: Dict[int, float],
    blended_audio_rate: float,
    video_rate: float,
    extra_tracks: int = 0,
    num_years: int = 10,
) -> Tuple[Dict[int, float], Dict[int, float], Dict[int, float], float, float]:
    """
    Compute aggregate 10-year revenues by decaying each track individually.

    Each track is decayed based on its weeks_since_release, then all tracks
    are summed to produce aggregate annual revenues.

    Args:
        tracks: List of TrackData with per-track streams and weeks_since_release
        wow_rates: 52 week-over-week rates for Year 1 from Excel
        excel_multipliers: Annual multipliers for years 1-10 from Excel
        blended_audio_rate: $/stream for audio
        video_rate: $/stream for video
        extra_tracks: Number of extra/new tracks (assumed at week 0)
        num_years: Number of years to project (10)

    Returns:
        Tuple of:
        - annual_revenues_audio: Dict[year, revenue] for audio
        - annual_revenues_video: Dict[year, revenue] for video
        - annual_totals: Dict[year, total_revenue]
        - total_weekly_audio: Total weekly audio streams (for reference)
        - total_weekly_video: Total weekly video streams (for reference)
    """
    if not tracks:
        # Return zeros if no tracks
        zeros = {y: 0.0 for y in range(1, num_years + 1)}
        return zeros, zeros, zeros, 0.0, 0.0

    # Build the base level curve (unshifted)
    level_curve, _, yearly_decay_factors, s1 = build_unshifted_level_curve(
        wow_rates=wow_rates,
        excel_multipliers=excel_multipliers,
        num_years=num_years,
    )

    # Get Year 10's decay factor for extension
    d_10 = yearly_decay_factors[10]
    if d_10 is None:
        d_10 = 0.98  # Fallback decay factor

    # Find max weeks_since_release to determine how far to extend the curve
    max_weeks = max(t.weeks_since_release for t in tracks)
    max_week_needed = 520 + max_weeks

    if max_week_needed > len(level_curve):
        extra_weeks = max_week_needed - len(level_curve)
        level_curve = extend_curve_beyond_520(level_curve, d_10, extra_weeks)

    # Initialize annual revenue accumulators
    annual_audio = {y: 0.0 for y in range(1, num_years + 1)}
    annual_video = {y: 0.0 for y in range(1, num_years + 1)}
    annual_totals = {y: 0.0 for y in range(1, num_years + 1)}

    total_weekly_audio = 0.0
    total_weekly_video = 0.0

    # Process each track
    for track in tracks:
        k = max(0, track.weeks_since_release)  # Weeks post-peak for this track

        # Track's current weekly streams
        audio_streams = track.weekly_us_audio_streams
        video_streams = track.weekly_us_video_streams

        total_weekly_audio += audio_streams
        total_weekly_video += video_streams

        if audio_streams <= 0 and video_streams <= 0:
            continue

        # Anchor point for this track
        anchor_week = 1 + k
        anchor_idx = min(k, len(level_curve) - 1)  # 0-indexed
        anchor_level = level_curve[anchor_idx]

        if anchor_level <= 0:
            continue

        # Scale factors for this track
        scale_audio = audio_streams / anchor_level if audio_streams > 0 else 0
        scale_video = video_streams / anchor_level if video_streams > 0 else 0

        # Compute this track's contribution to each year
        for year in range(1, num_years + 1):
            # Shifted year boundaries for this track
            start_week = 1 + (year - 1) * 52 + k  # 1-indexed
            end_week = 52 + (year - 1) * 52 + k

            # Convert to 0-indexed
            start_idx = max(0, start_week - 1)
            end_idx = min(end_week - 1, len(level_curve) - 1)

            # Sum levels for this track's year
            if start_idx <= end_idx:
                year_level_sum = sum(level_curve[start_idx:end_idx + 1])
            else:
                year_level_sum = 0

            # Convert to revenue
            audio_rev = scale_audio * year_level_sum * blended_audio_rate
            video_rev = scale_video * year_level_sum * video_rate

            annual_audio[year] += audio_rev
            annual_video[year] += video_rev
            annual_totals[year] += audio_rev + video_rev

    # Handle extra tracks (new songs owed - assumed at week 0/peak)
    if extra_tracks > 0 and tracks:
        # Use average per-track streams for extra tracks
        avg_audio_per_track = total_weekly_audio / len(tracks)
        avg_video_per_track = total_weekly_video / len(tracks)

        for _ in range(extra_tracks):
            # Extra tracks start at peak (k=0)
            anchor_level = level_curve[0]  # L[1]

            if anchor_level <= 0:
                continue

            scale_audio = avg_audio_per_track / anchor_level
            scale_video = avg_video_per_track / anchor_level

            for year in range(1, num_years + 1):
                start_week = 1 + (year - 1) * 52
                end_week = 52 + (year - 1) * 52

                start_idx = start_week - 1
                end_idx = end_week - 1

                year_level_sum = sum(level_curve[start_idx:end_idx + 1])

                audio_rev = scale_audio * year_level_sum * blended_audio_rate
                video_rev = scale_video * year_level_sum * video_rate

                annual_audio[year] += audio_rev
                annual_video[year] += video_rev
                annual_totals[year] += audio_rev + video_rev

            total_weekly_audio += avg_audio_per_track
            total_weekly_video += avg_video_per_track

    return annual_audio, annual_video, annual_totals, total_weekly_audio, total_weekly_video


class DealAnalyzer:
    """Unified deal analyzer combining pricer and projector."""

    def __init__(
        self,
        decay_path: Optional[Path] = None,
        ppu_path: Optional[Path] = None,
        discount_rate: float = DEFAULT_DISCOUNT_RATE,
    ):
        """
        Initialize the deal analyzer.

        Args:
            decay_path: Path to decay model Excel file
            ppu_path: Path to PPU rates Excel file
            discount_rate: Discount rate for NPV calculations
        """
        self.decay_path = decay_path or DEFAULT_DECAY_PATH
        self.ppu_path = ppu_path or DEFAULT_PPU_PATH
        self.discount_rate = discount_rate

        self._decay_loader: Optional[DecayLoader] = None
        self._ppu_loader: Optional[PPULoader] = None

    def _ensure_loaders(self) -> Tuple[DecayLoader, PPULoader]:
        """Lazily load the decay and PPU data."""
        if self._decay_loader is None:
            if not self.decay_path.exists():
                raise FileNotFoundError(f"Decay model file not found: {self.decay_path}")
            self._decay_loader = DecayLoader(self.decay_path)

        if self._ppu_loader is None:
            if not self.ppu_path.exists():
                raise FileNotFoundError(f"PPU rates file not found: {self.ppu_path}")
            self._ppu_loader = PPULoader(self.ppu_path)

        return self._decay_loader, self._ppu_loader

    def get_available_genres(self) -> List[str]:
        """Get list of available genres."""
        try:
            decay_loader, _ = self._ensure_loaders()
            return decay_loader.list_genres()
        except Exception:
            return AVAILABLE_GENRES

    def _fetch_track_data(self, artist_id: str) -> List[TrackData]:
        """Fetch track catalog data from Snowflake."""
        try:
            from .snowflake_client import snowflake_client
            return snowflake_client.get_track_catalog(artist_id)
        except Exception as e:
            logger.warning(f"Failed to fetch track data: {e}")
            return []

    def analyze(self, request: DealAnalysisRequest) -> DealAnalysisResult:
        """
        Perform complete deal analysis.

        Supports two modes:
        1. Track-level decay (default): Each track decays individually based on release date
        2. Aggregate decay: All tracks decay uniformly from weeks_post_peak

        Args:
            request: Deal analysis request parameters

        Returns:
            Complete deal analysis result
        """
        # Load data files
        decay_loader, ppu_loader = self._ensure_loaders()

        # Get decay multipliers for genre
        decay_multipliers = decay_loader.get_multipliers(request.genre)

        # Try to get weekly rates (may not be available for all genres)
        weekly_rates = None
        try:
            rates_data = decay_loader.get_weekly_rates(request.genre)
            weekly_rates = rates_data.get("weekly_rates")
        except Exception:
            pass

        # Compute blended audio rate
        blended_audio_rate = ppu_loader.compute_blended_audio_rate(
            request.market_shares,
            rest_mode="avg",
        )

        # Get video rate (use average)
        video_rate = ppu_loader.get_average_video_rate()

        # Determine analysis mode and compute revenues
        use_track_level = request.use_track_level_decay and weekly_rates is not None

        if use_track_level:
            # Fetch track data if not provided
            track_data = request.track_data
            if track_data is None:
                track_data = self._fetch_track_data(request.artist_id)

            if track_data:
                # Compute track-level revenues
                annual_audio, annual_video, annual_totals, total_audio, total_video = compute_track_level_revenues(
                    tracks=track_data,
                    wow_rates=weekly_rates,
                    excel_multipliers=decay_multipliers,
                    blended_audio_rate=blended_audio_rate,
                    video_rate=video_rate,
                    extra_tracks=request.extra_tracks,
                )

                # Derive effective multipliers from track-level revenues
                year1_total = annual_totals.get(1, 0)
                if year1_total > 0:
                    effective_multipliers = {y: total / year1_total for y, total in annual_totals.items()}
                else:
                    effective_multipliers = decay_multipliers

                # Update request with actual totals from track data
                effective_weekly_audio = total_audio
                effective_weekly_video = total_video
                effective_catalog_count = len(track_data)

                logger.info(
                    f"Track-level decay: {len(track_data)} tracks, "
                    f"Year 1 revenue: ${year1_total:,.0f}, "
                    f"Weekly audio: {effective_weekly_audio:,.0f}"
                )
            else:
                # Fall back to aggregate mode if no track data
                use_track_level = False
                effective_multipliers = decay_multipliers
                effective_weekly_audio = request.weekly_audio_streams
                effective_weekly_video = request.weekly_video_streams
                effective_catalog_count = request.catalog_track_count
        else:
            effective_multipliers = decay_multipliers
            effective_weekly_audio = request.weekly_audio_streams
            effective_weekly_video = request.weekly_video_streams
            effective_catalog_count = request.catalog_track_count

        # Build rate inputs with effective multipliers
        rate_inputs = RateInputs(
            blended_audio_rate=blended_audio_rate,
            video_rate=video_rate,
            decay_multipliers=effective_multipliers,
            weekly_rates=weekly_rates if not use_track_level else None,  # Don't use weekly rates if already applied
        )

        # Build deal inputs
        deal_inputs = DealInputs(
            genre=request.genre,
            weekly_audio=effective_weekly_audio,
            weekly_video=effective_weekly_video,
            catalog_tracks=effective_catalog_count,
            extra_tracks=0 if use_track_level else request.extra_tracks,  # Already handled in track-level
            market_shares=request.market_shares,
            deal_type=DEAL_TYPE_MAP.get(request.deal_type, PricerDealType.DISTRIBUTION),
            deal_percent=request.deal_percent,
            marketing_recoupable=request.marketing_recoupable,
            advance_share=request.advance_share,
            decay_mode="annual",  # Use annual mode since we've already computed the multipliers
            weeks_post_peak=0 if use_track_level else request.weeks_post_peak,  # Already handled in track-level
        )

        # Run pricer analysis
        pricer_result = analyze_deal(deal_inputs, rate_inputs, ppu_loader)

        # Extract pricing recommendations
        payback = pricer_result.payback_recommendation
        irr_10 = pricer_result.irr_recommendations[0] if len(pricer_result.irr_recommendations) > 0 else None
        irr_15 = pricer_result.irr_recommendations[1] if len(pricer_result.irr_recommendations) > 1 else None

        pricing = PricingRecommendation(
            payback_max_cost=payback.max_total_cost,
            payback_advance=payback.suggested_advance,
            payback_marketing=payback.suggested_marketing,
            payback_implied_irr=payback.implied_irr,
            payback_recoup_week=payback.recoup_week,
            irr_10_max_cost=irr_10.max_total_cost if irr_10 else 0,
            irr_10_advance=irr_10.suggested_advance if irr_10 else 0,
            irr_15_max_cost=irr_15.max_total_cost if irr_15 else 0,
            irr_15_advance=irr_15.suggested_advance if irr_15 else 0,
        )

        # Extract cash flow projections
        projections = pricer_result.projections
        cash_flow = CashFlowProjection(
            years=[p.year for p in projections],
            gross_revenue=[p.gross_revenue for p in projections],
            label_share=[p.label_cash_in for p in projections],
            artist_pay=[p.artist_pay for p in projections],
            multipliers=[p.multiplier for p in projections],
        )

        # Calculate label metrics using NPV calculator
        npv_calc = NPVCalculator(self.discount_rate)

        # Build DataFrame for label metrics calculation
        label_investment = irr_15.max_total_cost if irr_15 else 0
        cf_df = pd.DataFrame({
            "year_number": cash_flow.years,
            "gross_revenue": cash_flow.gross_revenue,
            "label_share": cash_flow.label_share,
            "net_artist_cash_flow": cash_flow.artist_pay,
        })

        label_metrics_dict = npv_calc.calculate_label_metrics(cf_df, label_investment)

        label_metrics = LabelMetrics(
            label_npv=label_metrics_dict["label_npv"],
            label_irr=label_metrics_dict.get("label_irr"),
            label_moic=label_metrics_dict.get("label_moic"),
            label_payback_year=label_metrics_dict.get("label_payback_year"),
            total_label_share=sum(cash_flow.label_share),
        )

        return DealAnalysisResult(
            request=request,
            analysis_timestamp=datetime.now().isoformat(),
            year1_audio_revenue=pricer_result.year1_audio_rev,
            year1_video_revenue=pricer_result.year1_video_rev,
            year1_total_revenue=pricer_result.year1_total_rev,
            blended_audio_rate=blended_audio_rate,
            video_rate=video_rate,
            pricing=pricing,
            cash_flow=cash_flow,
            label_metrics=label_metrics,
        )

    def analyze_viability(
        self,
        request: DealAnalysisRequest,
        advance: float,
        marketing: float,
        discount_rate: float = 0.10,
    ) -> Dict[str, Any]:
        """
        Analyze the viability of a specific deal with user-provided terms.

        Instead of recommending deal costs, this method takes the actual deal
        terms (advance, marketing) and calculates profitability metrics.

        Args:
            request: Deal analysis request parameters
            advance: Advance amount to pay artist
            marketing: Marketing/recording costs
            discount_rate: Discount rate for NPV calculations

        Returns:
            Dictionary with viability analysis including label and artist metrics
        """
        # Load data files
        decay_loader, ppu_loader = self._ensure_loaders()

        # Get decay multipliers for genre
        decay_multipliers = decay_loader.get_multipliers(request.genre)

        # Try to get weekly rates
        weekly_rates = None
        try:
            rates_data = decay_loader.get_weekly_rates(request.genre)
            weekly_rates = rates_data.get("weekly_rates")
        except Exception:
            pass

        # Compute blended audio rate
        blended_audio_rate = ppu_loader.compute_blended_audio_rate(
            request.market_shares,
            rest_mode="avg",
        )

        # Get video rate
        video_rate = ppu_loader.get_average_video_rate()

        # Determine analysis mode (track-level vs aggregate)
        use_track_level = request.use_track_level_decay and weekly_rates is not None

        if use_track_level:
            track_data = request.track_data
            if track_data is None:
                track_data = self._fetch_track_data(request.artist_id)

            if track_data:
                annual_audio, annual_video, annual_totals, total_audio, total_video = compute_track_level_revenues(
                    tracks=track_data,
                    wow_rates=weekly_rates,
                    excel_multipliers=decay_multipliers,
                    blended_audio_rate=blended_audio_rate,
                    video_rate=video_rate,
                    extra_tracks=request.extra_tracks,
                )

                year1_total = annual_totals.get(1, 0)
                if year1_total > 0:
                    effective_multipliers = {y: total / year1_total for y, total in annual_totals.items()}
                else:
                    effective_multipliers = decay_multipliers
                    year1_total = request.weekly_audio_streams * 52 * blended_audio_rate + request.weekly_video_streams * 52 * video_rate

                effective_weekly_audio = total_audio
                effective_weekly_video = total_video
            else:
                use_track_level = False
                effective_multipliers = decay_multipliers
                effective_weekly_audio = request.weekly_audio_streams
                effective_weekly_video = request.weekly_video_streams
                year1_total = effective_weekly_audio * 52 * blended_audio_rate + effective_weekly_video * 52 * video_rate
        else:
            effective_multipliers = decay_multipliers
            effective_weekly_audio = request.weekly_audio_streams
            effective_weekly_video = request.weekly_video_streams
            year1_total = effective_weekly_audio * 52 * blended_audio_rate + effective_weekly_video * 52 * video_rate

        # Calculate label share based on deal type
        from .pricer.model import compute_label_share, CashFlowEngine
        deal_type_enum = DEAL_TYPE_MAP.get(request.deal_type, PricerDealType.DISTRIBUTION)
        label_share_pct = compute_label_share(deal_type_enum, request.deal_percent)

        # Build cash flow engine with the user's deal cost
        total_investment = advance + marketing

        # Determine recoupable amount based on marketing_recoupable setting
        if request.marketing_recoupable:
            recoup_amount = total_investment
        else:
            recoup_amount = advance

        engine = CashFlowEngine(
            year1_total_rev=year1_total,
            decay_multipliers=effective_multipliers,
            label_share=label_share_pct,
            marketing_recoupable=request.marketing_recoupable,
            total_deal_cost=total_investment,
            deal_type=deal_type_enum,
        )

        # Compute cash flows with the user's recoupment amount
        cash_flows = engine.compute_cash_flows_with_recoup(recoup_amount)

        # Extract cash flow data
        years = [cf[0] for cf in cash_flows]
        gross_revenue = [cf[2] for cf in cash_flows]
        label_share_vals = [cf[3] for cf in cash_flows]
        artist_pay = [cf[4] for cf in cash_flows]
        multipliers = [cf[1] for cf in cash_flows]

        # Build DataFrame for NPV calculations
        cf_df = pd.DataFrame({
            "year_number": years,
            "gross_revenue": gross_revenue,
            "label_share": label_share_vals,
            "net_artist_cash_flow": artist_pay,
        })

        # Calculate label metrics
        npv_calc = NPVCalculator(discount_rate)
        label_metrics = npv_calc.calculate_label_metrics(cf_df, total_investment)

        # Calculate artist metrics
        artist_metrics = npv_calc.calculate_deal_npv(cf_df, advance)

        return {
            "analysis_timestamp": datetime.now().isoformat(),
            "artist_id": request.artist_id,
            "artist_name": request.artist_name,
            "total_investment": total_investment,
            "advance": advance,
            "marketing": marketing,
            "year1_revenue": year1_total,
            "deal_type": request.deal_type,
            "deal_percent": request.deal_percent,
            "label_share_pct": label_share_pct,
            "discount_rate": discount_rate,
            "cash_flow": {
                "years": years,
                "gross_revenue": gross_revenue,
                "label_share": label_share_vals,
                "artist_pay": artist_pay,
                "multipliers": multipliers,
            },
            "label_metrics": label_metrics,
            "artist_metrics": artist_metrics,
        }


# Global analyzer instance
_analyzer: Optional[DealAnalyzer] = None


def get_analyzer() -> DealAnalyzer:
    """Get or create the global deal analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = DealAnalyzer()
    return _analyzer


def analyze_deal_for_artist(
    artist_id: str,
    artist_name: str,
    weekly_audio_streams: float,
    weekly_video_streams: float,
    catalog_track_count: int,
    genre: str,
    deal_type: str = "distribution",
    deal_percent: float = 0.25,
    market_shares: Optional[Dict[str, float]] = None,
    advance_share: float = 0.70,
    marketing_recoupable: bool = False,
) -> DealAnalysisResult:
    """
    Convenience function to analyze a deal for an artist.

    Args:
        artist_id: Sodatone artist ID
        artist_name: Artist name
        weekly_audio_streams: Current weekly audio streams
        weekly_video_streams: Current weekly video streams
        catalog_track_count: Number of tracks in catalog
        genre: Genre for decay curve
        deal_type: "distribution", "profit_split", or "royalty"
        deal_percent: Label's share percentage
        market_shares: Country market shares
        advance_share: Portion of cost as advance
        marketing_recoupable: Whether marketing is recoupable

    Returns:
        Complete deal analysis result
    """
    request = DealAnalysisRequest(
        artist_id=artist_id,
        artist_name=artist_name,
        weekly_audio_streams=weekly_audio_streams,
        weekly_video_streams=weekly_video_streams,
        catalog_track_count=catalog_track_count,
        genre=genre,
        deal_type=deal_type,
        deal_percent=deal_percent,
        market_shares=market_shares or {"US": 0.50, "UK": 0.10},
        advance_share=advance_share,
        marketing_recoupable=marketing_recoupable,
    )

    analyzer = get_analyzer()
    return analyzer.analyze(request)
