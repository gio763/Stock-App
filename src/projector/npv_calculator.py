"""
Net Present Value (NPV) calculator for deal valuations.

This module calculates the present value of projected cash flows
using time value of money principles.
"""

from typing import Dict, Any, List, Optional, Union

import pandas as pd
import numpy as np

try:
    import numpy_financial as npf
except ImportError:
    npf = None


class NPVCalculator:
    """Calculator for Net Present Value of cash flows."""

    def __init__(self, discount_rate: float) -> None:
        """
        Initialize NPV calculator.

        Args:
            discount_rate: Annual discount rate (e.g., 0.10 for 10%)
        """
        self.discount_rate = discount_rate

    def calculate_npv(self, cash_flows: Union[List[float], pd.Series]) -> float:
        """
        Calculate NPV of a series of cash flows.

        Args:
            cash_flows: List or Series of annual cash flows (year 0 is immediate)

        Returns:
            Net present value
        """
        if isinstance(cash_flows, pd.Series):
            cash_flows = cash_flows.tolist()

        npv = 0.0
        for year, cash_flow in enumerate(cash_flows):
            # Year 0 is not discounted, year 1 is discounted once, etc.
            discount_factor = 1 / ((1 + self.discount_rate) ** year)
            npv += cash_flow * discount_factor

        return npv

    def calculate_discounted_cash_flows(
        self, cash_flow_df: pd.DataFrame, cash_flow_column: str = "net_artist_cash_flow"
    ) -> pd.DataFrame:
        """
        Calculate discounted cash flows for each year.

        Args:
            cash_flow_df: DataFrame with annual cash flows
            cash_flow_column: Name of column containing cash flows

        Returns:
            DataFrame with added discounted_cash_flow column
        """
        df = cash_flow_df.copy()

        # Calculate discount factor for each year (end-of-year convention)
        # Year 1 cash flow is discounted by (1+r)^1, Year 2 by (1+r)^2, etc.
        df["discount_factor"] = 1 / ((1 + self.discount_rate) ** df["year_number"])

        # Calculate discounted cash flow
        df["discounted_cash_flow"] = df[cash_flow_column] * df["discount_factor"]

        return df

    def calculate_deal_npv(
        self, cash_flow_df: pd.DataFrame, artist_advance: float = 0.0
    ) -> Dict[str, Any]:
        """
        Calculate NPV and related metrics for a deal.

        Args:
            cash_flow_df: DataFrame with year_number and net_artist_cash_flow columns
            artist_advance: Artist advance amount (cash paid at Year 0)

        Returns:
            Dictionary with NPV metrics including both royalties-only and incl-advance views
        """
        # Add discounted cash flows
        df = self.calculate_discounted_cash_flows(cash_flow_df)

        # ---- ROYALTIES ONLY (post-recoupment cash flow) ----
        # This is the existing logic: net_artist_cash_flow is $0 until recouped
        total_undiscounted_royalties = df["net_artist_cash_flow"].sum()
        total_npv_royalties = df["discounted_cash_flow"].sum()

        # Calculate cumulative values for royalties
        df["cumulative_undiscounted"] = df["net_artist_cash_flow"].cumsum()
        df["cumulative_npv"] = df["discounted_cash_flow"].cumsum()

        # Find break-even year (first year with positive cumulative cash flow)
        breakeven_years = df[df["cumulative_undiscounted"] > 0]
        breakeven_year = breakeven_years["year_number"].min() if not breakeven_years.empty else None

        # ---- INCLUDING ADVANCE (actual cash to artist) ----
        # Artist cash flow series: Year 0 = +advance, Years 1-10 = net_artist_cash_flow
        # Note: recording + marketing costs are NOT paid to artist, only advance
        artist_royalty_values = df["net_artist_cash_flow"].tolist()
        artist_cashflows_incl_advance = [artist_advance] + artist_royalty_values

        # Calculate NPV including advance
        # Year 0 is not discounted, Year 1 discounted by (1+r)^1, etc.
        artist_npv_incl_advance = 0.0
        for t, cf in enumerate(artist_cashflows_incl_advance):
            discount_factor = 1 / ((1 + self.discount_rate) ** t)
            artist_npv_incl_advance += cf * discount_factor

        # Total undiscounted cash to artist including advance
        artist_total_incl_advance = sum(artist_cashflows_incl_advance)

        return {
            # Royalties only (post-recoupment)
            "npv": total_npv_royalties,
            "total_undiscounted_cash_flow": total_undiscounted_royalties,
            # Including advance
            "npv_incl_advance": artist_npv_incl_advance,
            "total_cash_incl_advance": artist_total_incl_advance,
            "artist_advance": artist_advance,
            # Common metrics
            "discount_rate": self.discount_rate,
            "breakeven_year": int(breakeven_year) if breakeven_year else None,
            "year_1_npv": df[df["year_number"] == 1]["discounted_cash_flow"].iloc[0]
            if len(df) >= 1
            else 0,
            "years_projected": len(df),
        }

    def calculate_irr(self, cash_flows: List[float]) -> Optional[float]:
        """
        Calculate Internal Rate of Return (IRR).

        Args:
            cash_flows: List of cash flows (year 0 is typically negative for investment)

        Returns:
            IRR as a decimal (e.g., 0.15 for 15%), or None if cannot be calculated
        """
        try:
            if npf is not None:
                # Use numpy_financial's IRR function
                irr = npf.irr(cash_flows)
            else:
                # Fallback: use binary search for IRR
                irr = self._irr_binary_search(cash_flows)

            # Check if IRR is valid
            if irr is None or np.isnan(irr) or np.isinf(irr):
                return None
            return float(irr)
        except Exception:
            return None

    def _irr_binary_search(self, cash_flows: List[float], tolerance: float = 1e-6, max_iter: int = 100) -> Optional[float]:
        """Binary search IRR implementation as fallback."""
        # Check if total is positive (possible positive IRR)
        if sum(cash_flows) <= 0:
            return None

        r_low, r_high = -0.99, 5.0

        def npv_at_rate(r: float) -> float:
            total = 0.0
            for t, cf in enumerate(cash_flows):
                total += cf / ((1 + r) ** t)
            return total

        for _ in range(max_iter):
            r_mid = (r_low + r_high) / 2
            npv = npv_at_rate(r_mid)

            if abs(npv) < tolerance:
                return r_mid

            if npv > 0:
                r_low = r_mid
            else:
                r_high = r_mid

        return (r_low + r_high) / 2

    def calculate_label_metrics(
        self, cash_flow_df: pd.DataFrame, label_investment: float
    ) -> Dict[str, Any]:
        """
        Calculate Label NPV, IRR, MOIC, and Payback Year using Year 0 investment timing.

        The label cash flow series is modeled as:
        - Year 0: -label_investment (upfront cash outflow at deal inception)
        - Years 1-10: label_share (annual cash inflows from revenue share)

        Args:
            cash_flow_df: DataFrame with year_number and label_share columns
            label_investment: Total upfront investment (advance + recording + marketing)

        Returns:
            Dictionary with label valuation metrics:
            - label_npv: NPV from Year 0 investment + discounted annual inflows
            - label_total_undiscounted: Sum of all cash flows including Year 0
            - label_payback_year: First year (1-10) where cumulative CF >= 0
            - label_irr: Internal Rate of Return on the investment
            - label_moic: Multiple on Invested Capital (total inflows / investment)
        """
        df = cash_flow_df.copy()

        # Build cash flow series: Year 0 = -investment, Years 1-10 = label_share
        # This represents: label pays investment upfront, receives share each year
        label_share_values = df["label_share"].tolist()

        # Full cash flow series starting from Year 0
        label_cashflows = [-label_investment] + label_share_values

        # Calculate Label NPV: sum(cf_t / (1+r)^t) for t = 0, 1, ..., 10
        label_npv = 0.0
        for t, cf in enumerate(label_cashflows):
            discount_factor = 1 / ((1 + self.discount_rate) ** t)
            label_npv += cf * discount_factor

        # Total undiscounted label cash flow (including Year 0 investment)
        label_total_undiscounted = sum(label_cashflows)

        # Label Payback Year: first year t >= 1 where cumulative sum >= 0
        # Cumulative starts from Year 0 investment
        payback_year = None
        cumulative = 0.0
        for t, cf in enumerate(label_cashflows):
            cumulative += cf
            if t >= 1 and cumulative >= 0:
                payback_year = t
                break

        # Label IRR: calculate from the full cash flow series (Year 0 through Year 10)
        label_irr = self.calculate_irr(label_cashflows)

        # Label MOIC: total positive inflows / investment
        # Investment is the Year 0 outflow (label_investment)
        # Inflows are Years 1-10 label_share values
        total_inflows = sum(max(0, cf) for cf in label_cashflows[1:])
        label_moic = (total_inflows / label_investment) if label_investment > 0 else None

        return {
            "label_npv": label_npv,
            "label_total_undiscounted": label_total_undiscounted,
            "label_payback_year": payback_year,
            "label_irr": label_irr,
            "label_moic": label_moic,
            "label_investment": label_investment,
        }

    def sensitivity_analysis(
        self,
        cash_flow_df: pd.DataFrame,
        discount_rates: List[float],
        cash_flow_column: str = "net_artist_cash_flow",
    ) -> pd.DataFrame:
        """
        Perform sensitivity analysis across multiple discount rates.

        Args:
            cash_flow_df: DataFrame with cash flows
            discount_rates: List of discount rates to test
            cash_flow_column: Name of cash flow column

        Returns:
            DataFrame with NPV for each discount rate
        """
        results = []

        for rate in discount_rates:
            calc = NPVCalculator(rate)
            df_with_discount = calc.calculate_discounted_cash_flows(cash_flow_df, cash_flow_column)
            npv = df_with_discount["discounted_cash_flow"].sum()

            results.append({"discount_rate": rate, "npv": npv})

        return pd.DataFrame(results)

    def compare_scenarios(
        self,
        scenario_cash_flows: Dict[str, pd.DataFrame],
        cash_flow_column: str = "net_artist_cash_flow",
    ) -> pd.DataFrame:
        """
        Compare NPV across multiple scenarios.

        Args:
            scenario_cash_flows: Dictionary mapping scenario name to cash flow DataFrame
            cash_flow_column: Name of cash flow column

        Returns:
            DataFrame comparing NPV across scenarios
        """
        results = []

        for scenario_name, df in scenario_cash_flows.items():
            df_with_discount = self.calculate_discounted_cash_flows(df, cash_flow_column)

            total_npv = df_with_discount["discounted_cash_flow"].sum()
            total_undiscounted = df[cash_flow_column].sum()

            results.append(
                {
                    "scenario": scenario_name,
                    "npv": total_npv,
                    "total_undiscounted": total_undiscounted,
                    "discount_applied": total_undiscounted - total_npv,
                }
            )

        return pd.DataFrame(results)

    def calculate_payback_period(
        self, cash_flow_df: pd.DataFrame, initial_investment: float
    ) -> Optional[float]:
        """
        Calculate payback period (years to recover initial investment).

        Args:
            cash_flow_df: DataFrame with annual cash flows
            initial_investment: Initial investment amount (positive number)

        Returns:
            Payback period in years, or None if never pays back
        """
        df = cash_flow_df.copy()

        # Calculate cumulative cash flow
        df["cumulative"] = df["net_artist_cash_flow"].cumsum()

        # Find where cumulative exceeds investment
        payback_rows = df[df["cumulative"] >= initial_investment]

        if payback_rows.empty:
            return None

        # Get the first year where payback occurs
        payback_year_idx = payback_rows.index[0]
        payback_year = df.loc[payback_year_idx, "year_number"]

        # Interpolate for more precise payback period
        if payback_year_idx > 0:
            prev_cumulative = df.loc[payback_year_idx - 1, "cumulative"]
            current_cumulative = df.loc[payback_year_idx, "cumulative"]
            year_cash_flow = current_cumulative - prev_cumulative

            # How much of the year's cash flow is needed?
            remaining = initial_investment - prev_cumulative
            fraction = remaining / year_cash_flow if year_cash_flow > 0 else 0

            return float(payback_year - 1 + fraction)

        return float(payback_year)

    def calculate_profitability_index(
        self, cash_flow_df: pd.DataFrame, initial_investment: float
    ) -> float:
        """
        Calculate Profitability Index (PI = PV of future cash flows / Initial Investment).

        Args:
            cash_flow_df: DataFrame with cash flows
            initial_investment: Initial investment amount

        Returns:
            Profitability Index
        """
        if initial_investment == 0:
            return float("inf")

        df = self.calculate_discounted_cash_flows(cash_flow_df)
        pv_future_cash_flows = df["discounted_cash_flow"].sum()

        return pv_future_cash_flows / initial_investment


def create_npv_calculator(discount_rate: float) -> NPVCalculator:
    """
    Create an NPV calculator instance.

    Args:
        discount_rate: Discount rate (e.g., 0.10 for 10%)

    Returns:
        NPVCalculator instance
    """
    return NPVCalculator(discount_rate)


def calculate_npv(cash_flows: List[float], discount_rate: float) -> float:
    """
    Calculate NPV (convenience function).

    Args:
        cash_flows: List of annual cash flows
        discount_rate: Discount rate

    Returns:
        Net present value
    """
    calculator = create_npv_calculator(discount_rate)
    return calculator.calculate_npv(cash_flows)
