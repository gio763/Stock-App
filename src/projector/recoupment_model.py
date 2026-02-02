"""
Recoupment models for royalty and distribution deals.

This module implements the financial mechanics and recoupment waterfalls
for both traditional royalty deals and distribution deals.
"""

from typing import Dict, Any, List
from enum import Enum

import pandas as pd
import numpy as np


class DealType(Enum):
    """Deal type enumeration."""

    ROYALTY = "royalty"
    DISTRIBUTION = "distribution"


class RoyaltyDealModel:
    """
    Model for traditional royalty deal economics.

    In a royalty deal:
    - Label takes 100% of gross revenue
    - Artist earns royalty_rate % (e.g., 15-25%)
    - Artist royalty is credited to their account
    - Recoupable costs (advance, recording, marketing) are deducted from royalty account
    - Artist receives $0 until fully recouped
    - Post-recoupment: artist receives royalty payments
    """

    def __init__(
        self,
        royalty_rate: float,
        advance: float,
        recording_costs: float,
        marketing_costs: float,
    ) -> None:
        """
        Initialize royalty deal model.

        Args:
            royalty_rate: Artist royalty percentage (e.g., 0.20 for 20%)
            advance: Artist advance amount
            recording_costs: Recording costs to recoup
            marketing_costs: Marketing costs to recoup
        """
        self.royalty_rate = royalty_rate
        self.advance = advance
        self.recording_costs = recording_costs
        self.marketing_costs = marketing_costs
        self.total_recoupable = advance + recording_costs + marketing_costs

    def calculate_cash_flow(self, annual_revenue_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate year-by-year cash flow waterfall.

        Args:
            annual_revenue_df: DataFrame with 'year_number' and 'gross_revenue' columns

        Returns:
            DataFrame with complete cash flow waterfall including label metrics
        """
        df = annual_revenue_df.copy()

        # Artist's royalty share
        df["artist_royalty"] = df["gross_revenue"] * self.royalty_rate

        # Label's share (revenue side)
        df["label_share"] = df["gross_revenue"] - df["artist_royalty"]

        # Label costs: paid at Year 0 (deal signing), so Years 1-10 have zero costs
        # The Year 0 row with the investment is added in the display layer
        df["label_costs"] = 0.0

        # Label net cash flow for Years 1-10 = label_share (pure inflows)
        df["label_net_cash_flow"] = df["label_share"]

        # Calculate recoupment waterfall
        recoupment_balance = self.total_recoupable
        recoupment_balances = []
        artist_cash_flows = []

        for _, row in df.iterrows():
            artist_royalty = row["artist_royalty"]

            # Apply royalty to recoupment
            if recoupment_balance > 0:
                # Still recouping - pay any over-recoup in the same year
                recoupment_payment = min(artist_royalty, recoupment_balance)
                recoupment_balance -= recoupment_payment
                artist_cash_flow = artist_royalty - recoupment_payment
            else:
                # Fully recouped - artist receives royalty
                artist_cash_flow = artist_royalty

            recoupment_balances.append(recoupment_balance)
            artist_cash_flows.append(artist_cash_flow)

        df["recoupment_balance"] = recoupment_balances
        df["net_artist_cash_flow"] = artist_cash_flows

        return df

    def get_summary(self, cash_flow_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate summary statistics for the deal.

        Args:
            cash_flow_df: Cash flow DataFrame from calculate_cash_flow

        Returns:
            Dictionary with summary metrics
        """
        total_artist_cash = cash_flow_df["net_artist_cash_flow"].sum()
        total_label_cash = cash_flow_df["label_share"].sum()

        # Find recoupment year
        recouped_years = cash_flow_df[cash_flow_df["recoupment_balance"] == 0]
        recoupment_year = recouped_years["year_number"].min() if not recouped_years.empty else None

        return {
            "deal_type": "Royalty Deal",
            "total_gross_revenue": cash_flow_df["gross_revenue"].sum(),
            "total_artist_cash_flow": total_artist_cash,
            "total_label_share": total_label_cash,
            "recoupable_amount": self.total_recoupable,
            "recoupment_year": int(recoupment_year) if recoupment_year else None,
            "fully_recouped": recoupment_year is not None,
            "final_recoupment_balance": cash_flow_df["recoupment_balance"].iloc[-1],
        }


class DistributionDealModel:
    """
    Model for distribution deal economics.

    In a distribution deal:
    - Distributor takes distro_fee_pct off the top (10-25%)
    - Remaining revenue goes to artist
    - Recoupable costs (advance, marketing funded) are deducted from artist's share
    - Once recouped: artist receives full net revenue (gross - distro fee)
    """

    def __init__(
        self,
        distribution_fee: float,
        advance: float,
        marketing_funded: float,
    ) -> None:
        """
        Initialize distribution deal model.

        Args:
            distribution_fee: Distributor fee percentage (e.g., 0.15 for 15%)
            advance: Distribution advance amount
            marketing_funded: Marketing costs funded by distributor
        """
        self.distribution_fee = distribution_fee
        self.advance = advance
        self.marketing_funded = marketing_funded
        self.total_recoupable = advance + marketing_funded

    def calculate_cash_flow(self, annual_revenue_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate year-by-year cash flow waterfall.

        Args:
            annual_revenue_df: DataFrame with 'year_number' and 'gross_revenue' columns

        Returns:
            DataFrame with complete cash flow waterfall including label/distributor metrics
        """
        df = annual_revenue_df.copy()

        # Distributor takes fee off the top
        df["distributor_share"] = df["gross_revenue"] * self.distribution_fee

        # Artist's gross share (before recoupment)
        df["artist_gross_share"] = df["gross_revenue"] - df["distributor_share"]

        # For distribution deals, use distributor_share as the "label_share" equivalent
        df["label_share"] = df["distributor_share"]

        # Label/Distributor costs: paid at Year 0 (deal signing), so Years 1-10 have zero costs
        # The Year 0 row with the investment is added in the display layer
        df["label_costs"] = 0.0

        # Label net cash flow for Years 1-10 = distributor_share (pure inflows)
        df["label_net_cash_flow"] = df["label_share"]

        # Calculate recoupment waterfall
        recoupment_balance = self.total_recoupable
        recoupment_balances = []
        artist_cash_flows = []

        for _, row in df.iterrows():
            artist_gross = row["artist_gross_share"]

            # Apply to recoupment
            if recoupment_balance > 0:
                # Still recouping
                recoupment_payment = min(artist_gross, recoupment_balance)
                recoupment_balance -= recoupment_payment
                artist_cash_flow = artist_gross - recoupment_payment
            else:
                # Fully recouped - artist receives full net share
                artist_cash_flow = artist_gross

            recoupment_balances.append(recoupment_balance)
            artist_cash_flows.append(artist_cash_flow)

        df["recoupment_balance"] = recoupment_balances
        df["net_artist_cash_flow"] = artist_cash_flows

        return df

    def get_summary(self, cash_flow_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate summary statistics for the deal.

        Args:
            cash_flow_df: Cash flow DataFrame from calculate_cash_flow

        Returns:
            Dictionary with summary metrics
        """
        total_artist_cash = cash_flow_df["net_artist_cash_flow"].sum()
        total_distributor_cash = cash_flow_df["distributor_share"].sum()

        # Find recoupment year
        recouped_years = cash_flow_df[cash_flow_df["recoupment_balance"] == 0]
        recoupment_year = recouped_years["year_number"].min() if not recouped_years.empty else None

        return {
            "deal_type": "Distribution Deal",
            "total_gross_revenue": cash_flow_df["gross_revenue"].sum(),
            "total_artist_cash_flow": total_artist_cash,
            "total_distributor_share": total_distributor_cash,
            "recoupable_amount": self.total_recoupable,
            "recoupment_year": int(recoupment_year) if recoupment_year else None,
            "fully_recouped": recoupment_year is not None,
            "final_recoupment_balance": cash_flow_df["recoupment_balance"].iloc[-1],
        }


def create_royalty_deal(
    royalty_rate: float,
    advance: float,
    recording_costs: float,
    marketing_costs: float,
) -> RoyaltyDealModel:
    """
    Create a royalty deal model.

    Args:
        royalty_rate: Artist royalty percentage (0.0-1.0)
        advance: Artist advance
        recording_costs: Recording costs
        marketing_costs: Marketing costs

    Returns:
        RoyaltyDealModel instance
    """
    return RoyaltyDealModel(royalty_rate, advance, recording_costs, marketing_costs)


def create_distribution_deal(
    distribution_fee: float,
    advance: float,
    marketing_funded: float,
) -> DistributionDealModel:
    """
    Create a distribution deal model.

    Args:
        distribution_fee: Distribution fee percentage (0.0-1.0)
        advance: Distribution advance
        marketing_funded: Marketing costs funded by distributor

    Returns:
        DistributionDealModel instance
    """
    return DistributionDealModel(distribution_fee, advance, marketing_funded)


def calculate_deal_cash_flow(
    deal_type: DealType,
    annual_revenue_df: pd.DataFrame,
    **deal_params: Any,
) -> pd.DataFrame:
    """
    Calculate cash flow for a deal (convenience function).

    Args:
        deal_type: Type of deal (ROYALTY or DISTRIBUTION)
        annual_revenue_df: Annual revenue projections
        **deal_params: Deal-specific parameters

    Returns:
        Cash flow DataFrame
    """
    if deal_type == DealType.ROYALTY:
        model = create_royalty_deal(
            royalty_rate=deal_params["royalty_rate"],
            advance=deal_params.get("advance", 0),
            recording_costs=deal_params.get("recording_costs", 0),
            marketing_costs=deal_params.get("marketing_costs", 0),
        )
    else:  # DISTRIBUTION
        model = create_distribution_deal(
            distribution_fee=deal_params["distribution_fee"],
            advance=deal_params.get("advance", 0),
            marketing_funded=deal_params.get("marketing_funded", 0),
        )

    return model.calculate_cash_flow(annual_revenue_df)
