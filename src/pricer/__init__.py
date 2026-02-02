"""
Pricer module for music catalog deal pricing.

Provides decay curves, PPU rates, and deal analysis tools.
"""

from .decay import DecayLoader, load_decay_multipliers, GENRE_ALIASES
from .ppu import PPULoader, CountryRate, load_country_rates, parse_currency
from .model import (
    DealType,
    DealInputs,
    RateInputs,
    YearlyProjection,
    PaybackRecommendation,
    IRRRecommendation,
    AnalysisResult,
    CashFlowEngine,
    analyze_deal,
    compute_label_share,
    compute_pv,
    compute_npv,
    compute_max_cost_for_irr,
)
from .payback import (
    WeeklyCashFlowResult,
    compute_weekly_cashflows,
    compute_recoup_week,
    compute_payback_max_cost,
    compute_weekly_irr,
    compute_annual_irr,
    solve_max_cost_for_irr,
    generate_weekly_gross_series,
    compute_payback_recommendation,
    compute_irr_recommendation,
)
from .decay_weekly import (
    WeeklyDecayResult,
    build_weekly_curve,
    build_weekly_curve_with_rates,
    validate_weekly_curve,
)
from .decay_curve import (
    ShiftedCurveResult,
    build_shifted_curve,
    build_unshifted_level_curve,
)

__version__ = "1.0.0"

__all__ = [
    # decay.py
    "DecayLoader",
    "load_decay_multipliers",
    "GENRE_ALIASES",
    # ppu.py
    "PPULoader",
    "CountryRate",
    "load_country_rates",
    "parse_currency",
    # model.py
    "DealType",
    "DealInputs",
    "RateInputs",
    "YearlyProjection",
    "PaybackRecommendation",
    "IRRRecommendation",
    "AnalysisResult",
    "CashFlowEngine",
    "analyze_deal",
    "compute_label_share",
    "compute_pv",
    "compute_npv",
    "compute_max_cost_for_irr",
    # payback.py
    "WeeklyCashFlowResult",
    "compute_weekly_cashflows",
    "compute_recoup_week",
    "compute_payback_max_cost",
    "compute_weekly_irr",
    "compute_annual_irr",
    "solve_max_cost_for_irr",
    "generate_weekly_gross_series",
    "compute_payback_recommendation",
    "compute_irr_recommendation",
    # decay_weekly.py
    "WeeklyDecayResult",
    "build_weekly_curve",
    "build_weekly_curve_with_rates",
    "validate_weekly_curve",
    # decay_curve.py
    "ShiftedCurveResult",
    "build_shifted_curve",
    "build_unshifted_level_curve",
]
