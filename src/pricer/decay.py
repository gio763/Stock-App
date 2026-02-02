"""
Decay model loader for genre-based 10-year decay shapes.

Parses the Decay Model Excel workbook to extract annual multipliers for each genre.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd


# Known genre column names with fuzzy matching support
GENRE_ALIASES = {
    "dance": "Dance, Electronic, Electronica",
    "electronic": "Dance, Electronic, Electronica",
    "electronica": "Dance, Electronic, Electronica",
    "edm": "Dance, Electronic, Electronica",
    "jpop": "J-Pop & K-Pop",
    "kpop": "J-Pop & K-Pop",
    "j-pop": "J-Pop & K-Pop",
    "k-pop": "J-Pop & K-Pop",
    "pop": "Pop",
    "rock": "Rock",
    "singer": "Singer/Songwriter",
    "songwriter": "Singer/Songwriter",
    "singer/songwriter": "Singer/Songwriter",
    "urban": "Urban",
    "hip-hop": "Urban",
    "hiphop": "Urban",
    "hip hop": "Urban",
    "r&b": "Urban",
    "rnb": "Urban",
    "rap": "Urban",
}


class DecayLoader:
    """Loads and parses decay multipliers from the decay Excel workbook."""

    def __init__(self, filepath: Union[str, Path]):
        self.filepath = Path(filepath)
        self._df: Optional[pd.DataFrame] = None
        self._weeks_col: Optional[int] = None
        self._genre_columns: Dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        """Load the Excel file and identify column structure."""
        self._df = pd.read_excel(self.filepath, sheet_name=0, header=None)
        self._find_weeks_column()
        self._find_genre_columns()

    def _find_weeks_column(self) -> None:
        """Find the 'Weeks' column by scanning first few rows."""
        for row_idx in range(min(5, len(self._df))):
            for col_idx in range(len(self._df.columns)):
                val = self._df.iloc[row_idx, col_idx]
                if isinstance(val, str) and val.strip().lower() == "weeks":
                    self._weeks_col = col_idx
                    return
        raise ValueError("Could not find 'Weeks' column in decay workbook")

    def _find_genre_columns(self) -> None:
        """
        Find genre columns by scanning row 0 for genre names.
        Genre columns have the genre name in row 0, and we need the Revenue column
        which is at the same position as the genre name.
        Also finds the Rates column which is 2 columns after Revenue.
        """
        self._rates_columns: Dict[str, int] = {}

        for col_idx in range(len(self._df.columns)):
            val = self._df.iloc[0, col_idx]
            if pd.notna(val) and isinstance(val, str):
                val_clean = val.strip()
                # Check if it looks like a genre name (not 'Country' or other headers)
                if val_clean and "Country" not in val_clean:
                    # Row 0 contains genre names at the Revenue column position
                    # Check row 1 to see if this column has 'Revenue' header
                    row1_val = self._df.iloc[1, col_idx]
                    if pd.notna(row1_val) and isinstance(row1_val, str):
                        if row1_val.strip() == "Revenue":
                            self._genre_columns[val_clean] = col_idx
                            # Rates column is 2 columns after Revenue
                            rates_col = col_idx + 2
                            # Verify it's actually a Rates column
                            rates_header = self._df.iloc[1, rates_col] if rates_col < len(self._df.columns) else None
                            if pd.notna(rates_header) and isinstance(rates_header, str):
                                if rates_header.strip() == "Rates":
                                    self._rates_columns[val_clean] = rates_col

    def list_genres(self) -> List[str]:
        """Return list of available genres."""
        return list(self._genre_columns.keys())

    def _normalize_genre(self, genre: str) -> str:
        """Normalize genre name using fuzzy matching."""
        genre_lower = genre.strip().lower()

        # Try direct alias match
        if genre_lower in GENRE_ALIASES:
            return GENRE_ALIASES[genre_lower]

        # Try partial match
        for alias, canonical in GENRE_ALIASES.items():
            if alias in genre_lower or genre_lower in alias:
                return canonical

        # Try matching against actual genre column names
        for genre_col in self._genre_columns.keys():
            if genre_lower in genre_col.lower() or genre_col.lower() in genre_lower:
                return genre_col

        raise ValueError(
            f"Unknown genre: '{genre}'. Available genres: {self.list_genres()}"
        )

    def _find_year_rows(self) -> Dict[int, int]:
        """
        Find rows containing 'Year 1' through 'Year 10'.
        Returns mapping of year number to row index.
        """
        year_rows = {}
        pattern = re.compile(r"^Year\s+(\d+)\s*$", re.IGNORECASE)

        for row_idx in range(len(self._df)):
            val = self._df.iloc[row_idx, self._weeks_col]
            if isinstance(val, str):
                match = pattern.match(val.strip())
                if match:
                    year_num = int(match.group(1))
                    if 1 <= year_num <= 10:
                        year_rows[year_num] = row_idx

        return year_rows

    def get_multipliers(self, genre: str) -> Dict[int, float]:
        """
        Get decay multipliers for a genre.

        Args:
            genre: Genre name (supports fuzzy matching)

        Returns:
            Dictionary mapping year (1-10) to multiplier (year 1 = 1.0)
        """
        normalized_genre = self._normalize_genre(genre)

        if normalized_genre not in self._genre_columns:
            raise ValueError(
                f"Genre '{normalized_genre}' not found. Available: {self.list_genres()}"
            )

        revenue_col = self._genre_columns[normalized_genre]
        year_rows = self._find_year_rows()

        if len(year_rows) < 10:
            raise ValueError(
                f"Could not find all 10 year rows. Found years: {sorted(year_rows.keys())}"
            )

        # Extract revenue values for years 1-10
        values = {}
        for year in range(1, 11):
            row_idx = year_rows[year]
            val = self._df.iloc[row_idx, revenue_col]
            if pd.notna(val):
                values[year] = float(val)
            else:
                raise ValueError(f"Missing revenue value for Year {year}")

        # Convert to multipliers (value / year1_value)
        year1_value = values[1]
        multipliers = {year: val / year1_value for year, val in values.items()}

        # Verify year 1 multiplier is 1.0
        assert abs(multipliers[1] - 1.0) < 1e-9, "Year 1 multiplier should be 1.0"

        return multipliers

    def get_weekly_rates(self, genre: str) -> Dict[str, any]:
        """
        Get Year 1 weekly decay rates for a genre from the Excel sheet.

        The sheet has explicit week-over-week rates for weeks 1-52.
        Week 0 is the baseline (no rate).

        Args:
            genre: Genre name (supports fuzzy matching)

        Returns:
            Dict with:
            - week0_revenue: Baseline revenue at week 0
            - weekly_rates: List of 52 week-over-week multipliers for weeks 1-52
            - num_weeks: Number of weeks (53 for Year 1: weeks 0-52)
        """
        normalized_genre = self._normalize_genre(genre)

        if normalized_genre not in self._rates_columns:
            raise ValueError(
                f"No Rates column found for genre '{normalized_genre}'. "
                f"Available: {list(self._rates_columns.keys())}"
            )

        revenue_col = self._genre_columns[normalized_genre]
        rates_col = self._rates_columns[normalized_genre]

        # Week 0 revenue is at row index 2 (Excel row 3)
        week0_revenue = self._df.iloc[2, revenue_col]
        if pd.isna(week0_revenue):
            raise ValueError(f"Missing Week 0 revenue for {normalized_genre}")
        week0_revenue = float(week0_revenue)

        # Weekly rates are in rows 3-54 (Excel rows 4-55), for weeks 1-52
        weekly_rates = []
        for row_idx in range(3, 55):  # 52 rates
            val = self._df.iloc[row_idx, rates_col]
            if pd.isna(val):
                raise ValueError(f"Missing rate at row {row_idx} for {normalized_genre}")
            weekly_rates.append(float(val))

        return {
            "week0_revenue": week0_revenue,
            "weekly_rates": weekly_rates,
            "num_weeks": 53,  # Year 1 = weeks 0-52
        }

    def get_all_weekly_rates(self) -> Dict[str, Dict[str, any]]:
        """
        Get Year 1 weekly decay rates for ALL genres.

        Returns:
            Dictionary mapping genre name to weekly rates data
        """
        all_rates = {}
        for genre in self._rates_columns.keys():
            all_rates[genre] = self.get_weekly_rates(genre)
        return all_rates

    def get_all_multipliers(self) -> Dict[str, Dict[int, float]]:
        """
        Get decay multipliers for ALL genres.

        Returns:
            Dictionary mapping genre name to {year: multiplier}
        """
        all_multipliers = {}
        for genre in self.list_genres():
            all_multipliers[genre] = self.get_multipliers(genre)
        return all_multipliers

    def validate_all_genres(self) -> Dict[str, any]:
        """
        Validate extraction for ALL genres.

        Checks:
        - m1 must be ~1.0 (within 1e-6)
        - All multipliers must be numeric and non-negative
        - All 10 years must be present

        Returns:
            Validation results dict

        Raises:
            ValueError if any genre fails validation
        """
        all_multipliers = self.get_all_multipliers()
        errors = []

        for genre, mults in all_multipliers.items():
            # Check m1 is ~1.0
            m1 = mults.get(1, 0)
            if abs(m1 - 1.0) > 1e-6:
                errors.append(f"{genre}: m1={m1}, expected 1.0")

            # Check all years present and non-negative
            for year in range(1, 11):
                if year not in mults:
                    errors.append(f"{genre}: missing Year {year}")
                elif mults[year] < 0:
                    errors.append(f"{genre}: Year {year} is negative ({mults[year]})")

        if errors:
            raise ValueError(f"Decay extraction validation failed: {len(errors)} errors")

        return {"valid": True, "genres": list(all_multipliers.keys()), "multipliers": all_multipliers}

    def export_json(self, output_path: Union[str, Path], include_weekly: bool = False) -> None:
        """
        Export all genre multipliers to JSON for debugging.

        Args:
            output_path: Path to write JSON file
            include_weekly: If True, also include weekly curve data (large)
        """
        from .decay_weekly import build_weekly_curve, validate_weekly_curve

        all_multipliers = {}
        validation_summary = {}

        for genre in self.list_genres():
            try:
                mults = self.get_multipliers(genre)
                all_multipliers[genre] = {
                    "annual_multipliers": {str(k): v for k, v in mults.items()},
                }

                # Build and validate weekly curve
                weekly_result = build_weekly_curve(100000.0, mults)
                validation = validate_weekly_curve(weekly_result)

                all_multipliers[genre]["weekly_validation"] = {
                    "valid": validation["valid"],
                    "max_error": validation["max_error"],
                    "worst_year": validation["worst_year"],
                }

                if include_weekly:
                    all_multipliers[genre]["weekly_multipliers"] = {
                        str(k): v for k, v in weekly_result.annual_multipliers.items()
                    }
                    all_multipliers[genre]["yearly_decay_factors"] = {
                        str(k): v for k, v in weekly_result.yearly_decay_factors.items()
                    }

                validation_summary[genre] = validation["valid"]

            except Exception as e:
                all_multipliers[genre] = {"error": str(e)}
                validation_summary[genre] = False

        output = {
            "decay_by_genre": all_multipliers,
            "validation_summary": validation_summary,
            "all_valid": all(validation_summary.values()),
        }

        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)


def load_decay_multipliers(filepath: Union[str, Path], genre: str) -> Dict[int, float]:
    """
    Convenience function to load decay multipliers for a genre.

    Args:
        filepath: Path to decay Excel workbook
        genre: Genre name (supports fuzzy matching)

    Returns:
        Dictionary mapping year (1-10) to multiplier (year 1 = 1.0)
    """
    loader = DecayLoader(filepath)
    return loader.get_multipliers(genre)
