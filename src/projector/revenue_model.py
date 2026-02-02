"""
Revenue calculation model for converting streams to revenue.

This module handles conversion of streaming counts to gross revenue
using PPU (price per unit) rates.
"""

from typing import Dict, Any, Optional

import pandas as pd
import numpy as np


class RevenueModel:
    """Model for calculating revenue from streaming data."""

    def __init__(self, ppu_rate: float, us_ppu_rate: Optional[float] = None, row_ppu_rate: Optional[float] = None) -> None:
        """
        Initialize the revenue model.

        Args:
            ppu_rate: Blended global price-per-unit rate (dollars per stream) - fallback
            us_ppu_rate: US-specific PPU rate (optional, for market-specific calculations)
            row_ppu_rate: Rest of World PPU rate (optional, for market-specific calculations)
        """
        self.ppu_rate = ppu_rate
        self.us_ppu_rate = us_ppu_rate if us_ppu_rate is not None else ppu_rate
        self.row_ppu_rate = row_ppu_rate if row_ppu_rate is not None else ppu_rate

    def calculate_revenue_from_streams(self, streams: float) -> float:
        """
        Calculate gross revenue from stream count.

        Args:
            streams: Number of streams

        Returns:
            Gross revenue in dollars
        """
        return streams * self.ppu_rate

    def calculate_weekly_revenue(self, weekly_streams_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate revenue for weekly streaming data.

        Args:
            weekly_streams_df: DataFrame with 'projected_streams' column, optionally 'region'

        Returns:
            DataFrame with added 'gross_revenue' column
        """
        df = weekly_streams_df.copy()

        # Apply market-specific rates if region column exists
        if 'region' in df.columns:
            df["gross_revenue"] = df.apply(
                lambda row: (
                    row["projected_streams"] * self.us_ppu_rate if row["region"] == "US"
                    else row["projected_streams"] * self.row_ppu_rate
                ),
                axis=1
            )
        else:
            # Fallback to blended rate
            df["gross_revenue"] = df["projected_streams"] * self.ppu_rate

        return df

    def calculate_annual_revenue(self, annual_streams_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate revenue for annual streaming data.

        Args:
            annual_streams_df: DataFrame with 'annual_streams' column

        Returns:
            DataFrame with added 'gross_revenue' column
        """
        df = annual_streams_df.copy()
        df["gross_revenue"] = df["annual_streams"] * self.ppu_rate
        return df

    def aggregate_catalog_revenue(
        self, track_projections: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Aggregate revenue projections across multiple tracks.

        Args:
            track_projections: Dictionary mapping ISRC to DataFrame with projections

        Returns:
            DataFrame with aggregated annual revenue by year
        """
        all_annual = []

        for isrc, proj_df in track_projections.items():
            if "date" in proj_df.columns:
                # Weekly data - aggregate to annual
                df = proj_df.copy()
                df["year"] = df["date"].dt.year

                # Handle region-specific aggregation
                if 'region' in df.columns:
                    annual = (
                        df.groupby(["year", "region"])
                        .agg({"projected_streams": "sum"})
                        .reset_index()
                    )
                else:
                    annual = (
                        df.groupby("year")
                        .agg({"projected_streams": "sum"})
                        .reset_index()
                    )
                annual["isrc"] = isrc
                all_annual.append(annual)
            elif "year" in proj_df.columns:
                # Already annual data
                proj_df["isrc"] = isrc
                all_annual.append(proj_df)

        if not all_annual:
            return pd.DataFrame(columns=["year", "total_streams", "gross_revenue"])

        # Combine all tracks
        combined = pd.concat(all_annual, ignore_index=True)

        # Aggregate across all tracks by year (and region if present)
        if 'region' in combined.columns:
            aggregated = (
                combined.groupby(["year", "region"])["projected_streams"]
                .sum()
                .reset_index()
                .rename(columns={"projected_streams": "total_streams"})
            )
            # Calculate revenue with market-specific rates
            aggregated["gross_revenue"] = aggregated.apply(
                lambda row: (
                    row["total_streams"] * self.us_ppu_rate if row["region"] == "US"
                    else row["total_streams"] * self.row_ppu_rate
                ),
                axis=1
            )
            # Sum across regions for final aggregation
            final_aggregated = (
                aggregated.groupby("year")
                .agg({"total_streams": "sum", "gross_revenue": "sum"})
                .reset_index()
            )
        else:
            aggregated = (
                combined.groupby("year")["projected_streams"]
                .sum()
                .reset_index()
                .rename(columns={"projected_streams": "total_streams"})
            )
            aggregated["gross_revenue"] = aggregated["total_streams"] * self.ppu_rate
            final_aggregated = aggregated

        # Add year number
        final_aggregated = final_aggregated.sort_values("year").reset_index(drop=True)
        final_aggregated["year_number"] = range(1, len(final_aggregated) + 1)

        return final_aggregated

    def create_revenue_breakdown(
        self, catalog_revenue: pd.DataFrame, new_release_revenue: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Create breakdown of revenue by source (catalog vs new releases).

        Args:
            catalog_revenue: DataFrame with catalog revenue projections
            new_release_revenue: DataFrame with new release revenue projections

        Returns:
            DataFrame with revenue broken down by source
        """
        # Align years
        all_years = sorted(
            set(catalog_revenue["year_number"].tolist())
            | set(new_release_revenue["year_number"].tolist())
        )

        breakdown = []
        for year_num in all_years:
            catalog_rev = 0
            new_release_rev = 0

            # Get catalog revenue for this year
            catalog_row = catalog_revenue[catalog_revenue["year_number"] == year_num]
            if not catalog_row.empty:
                catalog_rev = catalog_row.iloc[0]["gross_revenue"]

            # Get new release revenue for this year
            new_release_row = new_release_revenue[new_release_revenue["year_number"] == year_num]
            if not new_release_row.empty:
                new_release_rev = new_release_row.iloc[0]["gross_revenue"]

            breakdown.append(
                {
                    "year_number": year_num,
                    "catalog_revenue": catalog_rev,
                    "new_release_revenue": new_release_rev,
                    "total_revenue": catalog_rev + new_release_rev,
                }
            )

        return pd.DataFrame(breakdown)

    def calculate_revenue_time_series(
        self, streams_time_series: pd.Series, annual: bool = True
    ) -> pd.Series:
        """
        Calculate revenue from a time series of streams.

        Args:
            streams_time_series: Series with stream counts
            annual: If True, assumes annual data. If False, assumes weekly.

        Returns:
            Series with revenue values
        """
        return streams_time_series * self.ppu_rate

    def get_revenue_summary(self, annual_revenue_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate summary statistics for revenue projections.

        Args:
            annual_revenue_df: DataFrame with annual revenue projections

        Returns:
            Dictionary with summary metrics
        """
        if annual_revenue_df.empty:
            return {
                "total_revenue": 0,
                "average_annual_revenue": 0,
                "year_1_revenue": 0,
                "year_10_revenue": 0,
                "peak_year": None,
                "peak_revenue": 0,
            }

        total_revenue = annual_revenue_df["gross_revenue"].sum()
        avg_annual = annual_revenue_df["gross_revenue"].mean()

        # Get specific years
        year_1 = (
            annual_revenue_df[annual_revenue_df["year_number"] == 1]["gross_revenue"].iloc[0]
            if len(annual_revenue_df) >= 1
            else 0
        )

        year_10 = (
            annual_revenue_df[annual_revenue_df["year_number"] == 10]["gross_revenue"].iloc[0]
            if len(annual_revenue_df) >= 10
            else 0
        )

        # Find peak
        peak_idx = annual_revenue_df["gross_revenue"].idxmax()
        peak_year = annual_revenue_df.loc[peak_idx, "year_number"]
        peak_revenue = annual_revenue_df.loc[peak_idx, "gross_revenue"]

        return {
            "total_revenue": total_revenue,
            "average_annual_revenue": avg_annual,
            "year_1_revenue": year_1,
            "year_10_revenue": year_10,
            "peak_year": int(peak_year),
            "peak_revenue": peak_revenue,
        }


def create_revenue_model(ppu_rate: float, us_ppu_rate: Optional[float] = None, row_ppu_rate: Optional[float] = None) -> RevenueModel:
    """
    Create a RevenueModel instance.

    Args:
        ppu_rate: Price per unit (per stream) rate - fallback/blended
        us_ppu_rate: US-specific PPU rate (optional)
        row_ppu_rate: ROW-specific PPU rate (optional)

    Returns:
        RevenueModel instance
    """
    return RevenueModel(ppu_rate, us_ppu_rate, row_ppu_rate)
