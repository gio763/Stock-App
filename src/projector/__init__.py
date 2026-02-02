"""
Projector module for deal cash flow projections.

Provides NPV calculations, recoupment models, and revenue projections.
"""

from .npv_calculator import (
    NPVCalculator,
    create_npv_calculator,
    calculate_npv,
)
from .recoupment_model import (
    DealType,
    RoyaltyDealModel,
    DistributionDealModel,
    create_royalty_deal,
    create_distribution_deal,
    calculate_deal_cash_flow,
)
from .revenue_model import (
    RevenueModel,
    create_revenue_model,
)

__version__ = "1.0.0"

__all__ = [
    # npv_calculator.py
    "NPVCalculator",
    "create_npv_calculator",
    "calculate_npv",
    # recoupment_model.py
    "DealType",
    "RoyaltyDealModel",
    "DistributionDealModel",
    "create_royalty_deal",
    "create_distribution_deal",
    "calculate_deal_cash_flow",
    # revenue_model.py
    "RevenueModel",
    "create_revenue_model",
]
