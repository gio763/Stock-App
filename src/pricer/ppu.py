"""
PPU (Pay Per Unit) rates loader for country-level audio and video payouts.

Parses the PPU Streams By Country Excel workbook to extract streaming rates.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd


# Country name aliases for fuzzy matching
COUNTRY_ALIASES = {
    "united states": "USA",
    "us": "USA",
    "usa": "USA",
    "america": "USA",
    "united kingdom": "UK",
    "great britain": "UK",
    "britain": "UK",
    "england": "UK",
    "uk": "UK",
    "south korea": "KOREA",
    "republic of korea": "KOREA",
    "korea": "KOREA",
    "hong kong sar": "HONG KONG",
    "hong kong": "HONG KONG",
    "uae": "UNITED ARAB EMIRATES",
    "united arab emirates": "UNITED ARAB EMIRATES",
    "netherlands": "NETHERLANDS",
    "holland": "NETHERLANDS",
    "russia": "RUSSIAN FEDERATION",
    "russian federation": "RUSSIAN FEDERATION",
    "czech": "CZECH REPUBLIC",
    "czechia": "CZECH REPUBLIC",
    "czech republic": "CZECH REPUBLIC",
}

# Rows to exclude (region totals and non-country entries)
EXCLUDED_COUNTRIES = {
    "AFRICA",
    "OTHERS",
}


@dataclass
class CountryRate:
    """Represents streaming rates for a country."""

    country: str
    audio_rate: float
    video_rate: float


def parse_currency(value: str) -> float:
    """
    Parse currency string like " $     0.00307" to float.

    Args:
        value: Currency string with optional $ and whitespace

    Returns:
        Parsed float value
    """
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    # Remove $ and whitespace, then parse
    cleaned = re.sub(r"[$,\s]", "", str(value).strip())
    if not cleaned:
        return 0.0

    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class PPULoader:
    """Loads and parses country streaming rates from PPU Excel workbook."""

    def __init__(self, filepath: Union[str, Path]):
        self.filepath = Path(filepath)
        self._df: Optional[pd.DataFrame] = None
        self._country_rates: Dict[str, CountryRate] = {}
        self._load()

    def _load(self) -> None:
        """Load the Excel file and parse country rates."""
        self._df = pd.read_excel(self.filepath, sheet_name=0, header=None)
        self._parse_rates()

    def _is_valid_country_row(self, row_idx: int) -> bool:
        """
        Check if a row represents a valid country (not a region total).

        Filtering rules:
        - Skip header row (row 0)
        - Skip rows where Country is nan/empty
        - Skip rows where Region contains "Total" and Country is nan
        - Skip rows in EXCLUDED_COUNTRIES set
        """
        if row_idx == 0:
            return False

        region = self._df.iloc[row_idx, 0]
        country = self._df.iloc[row_idx, 2]

        # Skip if country is missing
        if pd.isna(country) or str(country).strip() == "":
            return False

        country_str = str(country).strip().upper()

        # Skip excluded countries (region names used as countries)
        if country_str in EXCLUDED_COUNTRIES:
            return False

        # Skip region total rows
        if pd.notna(region) and "Total" in str(region):
            # But keep if it's the only entry for that country (like CANADA, UK, USA)
            # Check if this row's country is meaningful
            if country_str in {"CANADA", "UK", "USA", "ISRAEL"}:
                return True
            return False

        return True

    def _parse_rates(self) -> None:
        """Parse country rates from the dataframe."""
        for row_idx in range(len(self._df)):
            if not self._is_valid_country_row(row_idx):
                continue

            country = str(self._df.iloc[row_idx, 2]).strip().upper()
            audio_rate = parse_currency(self._df.iloc[row_idx, 3])
            video_rate = parse_currency(self._df.iloc[row_idx, 4])

            # Skip rows with zero rates
            if audio_rate > 0 or video_rate > 0:
                self._country_rates[country] = CountryRate(
                    country=country, audio_rate=audio_rate, video_rate=video_rate
                )

    def list_countries(self) -> List[str]:
        """Return list of available countries."""
        return sorted(self._country_rates.keys())

    def _normalize_country(self, country: str) -> str:
        """Normalize country name using fuzzy matching."""
        country_upper = country.strip().upper()
        country_lower = country.strip().lower()

        # Try direct match first
        if country_upper in self._country_rates:
            return country_upper

        # Try alias match
        if country_lower in COUNTRY_ALIASES:
            alias = COUNTRY_ALIASES[country_lower]
            if alias in self._country_rates:
                return alias

        # Try partial match
        for known_country in self._country_rates.keys():
            if (
                country_upper in known_country
                or known_country in country_upper
                or country_lower in known_country.lower()
                or known_country.lower() in country_lower
            ):
                return known_country

        raise ValueError(
            f"Unknown country: '{country}'. Use list_countries() to see available options."
        )

    def get_rate(self, country: str) -> CountryRate:
        """
        Get streaming rates for a country.

        Args:
            country: Country name (supports fuzzy matching)

        Returns:
            CountryRate with audio and video rates
        """
        normalized = self._normalize_country(country)
        return self._country_rates[normalized]

    def get_audio_rate(self, country: str) -> float:
        """Get audio rate for a country."""
        return self.get_rate(country).audio_rate

    def get_video_rate(self, country: str) -> float:
        """Get video rate for a country."""
        return self.get_rate(country).video_rate

    def get_average_audio_rate(self) -> float:
        """
        Calculate average audio rate across all valid countries.
        Used as fallback for 'rest of world' rate.
        """
        rates = [r.audio_rate for r in self._country_rates.values() if r.audio_rate > 0]
        if not rates:
            return 0.0
        return sum(rates) / len(rates)

    def get_average_video_rate(self) -> float:
        """
        Calculate average video rate across all valid countries.
        Used as global video rate (no top-market split for video).
        """
        rates = [r.video_rate for r in self._country_rates.values() if r.video_rate > 0]
        if not rates:
            return 0.0
        return sum(rates) / len(rates)

    def compute_blended_audio_rate(
        self,
        market_shares: Dict[str, float],
        rest_mode: str = "avg",
    ) -> float:
        """
        Compute blended audio rate from market shares.

        Args:
            market_shares: Dict mapping country name to share of global audio streams
                          Shares should sum to <= 1.0
            rest_mode: How to handle rest-of-world rate: "avg" or "us"

        Returns:
            Blended audio rate
        """
        total_share = sum(market_shares.values())
        if total_share > 1.0:
            raise ValueError(f"Market shares sum to {total_share}, must be <= 1.0")

        # Calculate weighted rate for specified markets
        blended_rate = 0.0
        for country, share in market_shares.items():
            normalized = self._normalize_country(country)
            rate = self._country_rates[normalized].audio_rate
            blended_rate += share * rate

        # Add rest-of-world component
        rest_share = 1.0 - total_share
        if rest_share > 0:
            if rest_mode == "us":
                rest_rate = self.get_audio_rate("USA")
            else:  # avg
                rest_rate = self.get_average_audio_rate()
            blended_rate += rest_share * rest_rate

        return blended_rate


def load_country_rates(filepath: Union[str, Path]) -> PPULoader:
    """
    Convenience function to load country rates.

    Args:
        filepath: Path to PPU Excel workbook

    Returns:
        PPULoader instance
    """
    return PPULoader(filepath)
