"""Chartex API client for TikTok sound data."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import httpx

from .config import settings
from .models import TikTokSound, TimeSeriesPoint

logger = logging.getLogger(__name__)


class ChartexAPIError(RuntimeError):
    """Raised when Chartex API returns an error response."""


class ChartexClient:
    """Client for Chartex TikTok API."""

    def __init__(self) -> None:
        self._base_url = settings.chartex.api_base_url

    @property
    def configured(self) -> bool:
        return settings.chartex.configured

    def _get_headers(self) -> dict:
        """Get request headers with authentication."""
        app_id = settings.chartex.app_id
        app_token = settings.chartex.app_token

        if not app_id or not app_token:
            raise ChartexAPIError(
                "Chartex credentials not configured. "
                "Set CHARTEX_APP_ID and CHARTEX_APP_TOKEN environment variables."
            )

        # Chartex uses X-APP-ID and X-APP-TOKEN headers
        return {
            "X-APP-ID": app_id,
            "X-APP-TOKEN": app_token,
            "Accept": "application/json",
        }

    def get_sound_views(
        self,
        sound_id: str,
        mode: str = "daily",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit_days: Optional[int] = None,
    ) -> List[TimeSeriesPoint]:
        """Get TikTok video views time series for a sound.

        Args:
            sound_id: TikTok sound ID
            mode: 'daily' for daily values, 'total' for cumulative
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit_days: Optional limit to last N days

        Returns:
            List of TimeSeriesPoint with view data
        """
        if not self.configured:
            logger.warning("Chartex not configured, returning empty data")
            return []

        # Correct endpoint: /tiktok-sounds/{tiktok_sound_id}/stats/{metric}/
        url = f"{self._base_url}/tiktok-sounds/{sound_id}/stats/tiktok-video-views/"

        params = {"mode": mode}
        if start_date:
            params["start_date"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["end_date"] = end_date.strftime("%Y-%m-%d")
        if limit_days:
            params["limit_by_latest_days"] = limit_days

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url, headers=self._get_headers(), params=params)

            logger.info("Chartex views API: %s %s - %s", response.status_code, url, response.text[:300] if response.text else "empty")

            if response.status_code == 401:
                raise ChartexAPIError("Invalid Chartex credentials")
            if response.status_code == 403:
                raise ChartexAPIError("Access denied - sound may not be tracked")
            if response.status_code == 404:
                logger.warning("Sound %s not found in Chartex", sound_id)
                return []
            if response.status_code >= 400:
                raise ChartexAPIError(f"Chartex API error: {response.status_code} - {response.text}")

            if not response.text:
                logger.warning("Chartex returned empty response")
                return []

            data = response.json()
            return self._parse_time_series(data)

        except httpx.RequestError as e:
            logger.error("Chartex request failed: %s", e)
            return []

    def get_sound_creates(
        self,
        sound_id: str,
        mode: str = "daily",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit_days: Optional[int] = None,
    ) -> List[TimeSeriesPoint]:
        """Get TikTok creates (videos using sound) time series.

        Args:
            sound_id: TikTok sound ID
            mode: 'daily' for daily values, 'total' for cumulative
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit_days: Optional limit to last N days

        Returns:
            List of TimeSeriesPoint with creates data
        """
        if not self.configured:
            logger.warning("Chartex not configured, returning empty data")
            return []

        # Correct endpoint: /tiktok-sounds/{tiktok_sound_id}/stats/{metric}/
        # tiktok-video-counts = number of videos using the sound
        url = f"{self._base_url}/tiktok-sounds/{sound_id}/stats/tiktok-video-counts/"

        params = {"mode": mode}
        if start_date:
            params["start_date"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["end_date"] = end_date.strftime("%Y-%m-%d")
        if limit_days:
            params["limit_by_latest_days"] = limit_days

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url, headers=self._get_headers(), params=params)

            logger.info("Chartex creates API: %s %s - %s", response.status_code, url, response.text[:300] if response.text else "empty")

            if response.status_code >= 400:
                logger.warning("Chartex creates API error: %s - %s", response.status_code, response.text[:200] if response.text else "empty")
                return []

            if not response.text:
                return []

            data = response.json()
            return self._parse_time_series(data)

        except httpx.RequestError as e:
            logger.error("Chartex request failed: %s", e)
            return []

    def list_tracked_sounds(self, limit: int = 20) -> List[dict]:
        """Get list of sounds tracked in your Chartex dashboard.

        Returns:
            List of sound dictionaries with ID, name, and stats
        """
        if not self.configured:
            return []

        url = f"{self._base_url}/tiktok-sounds/"
        params = {"limit": limit, "sort_by": "tiktok_last_7_days_video_count"}

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url, headers=self._get_headers(), params=params)

            logger.info("Chartex list sounds: %s - %s", response.status_code, response.text[:500] if response.text else "empty")

            if response.status_code >= 400:
                logger.warning("Chartex list error: %s", response.status_code)
                return []

            data = response.json()
            # Return the results list
            if isinstance(data, dict):
                return data.get("results", data.get("data", []))
            elif isinstance(data, list):
                return data
            return []

        except Exception as e:
            logger.error("Chartex list failed: %s", e)
            return []

    def get_sound_data(
        self,
        sound_id: str,
        lookback_days: int = 90,
    ) -> TikTokSound:
        """Get complete TikTok sound data including views and creates.

        Args:
            sound_id: TikTok sound ID
            lookback_days: Number of days of historical data

        Returns:
            TikTokSound with metrics and time series
        """
        # Get views time series (total mode for current total)
        views_total = self.get_sound_views(sound_id, mode="total", limit_days=1)
        views_daily = self.get_sound_views(sound_id, mode="daily", limit_days=lookback_days)

        # Get creates time series
        creates_total = self.get_sound_creates(sound_id, mode="total", limit_days=1)
        creates_daily = self.get_sound_creates(sound_id, mode="daily", limit_days=lookback_days)

        # Calculate current totals
        total_views = int(views_total[-1].value) if views_total else 0
        total_creates = int(creates_total[-1].value) if creates_total else 0

        # Calculate 7-day and 24-hour changes
        views_7d = self._sum_last_n_days(views_daily, 7)
        views_24h = self._sum_last_n_days(views_daily, 1)
        creates_7d = self._sum_last_n_days(creates_daily, 7)
        creates_24h = self._sum_last_n_days(creates_daily, 1)

        return TikTokSound(
            sound_id=sound_id,
            name=f"TikTok Sound {sound_id[-8:]}",  # Will be updated with actual name
            tiktok_url=f"https://www.tiktok.com/music/original-sound-{sound_id}",
            total_views=total_views,
            views_7d=views_7d,
            views_24h=views_24h,
            total_creates=total_creates,
            creates_7d=creates_7d,
            creates_24h=creates_24h,
            views_history=views_daily,
            creates_history=creates_daily,
        )

    def _parse_time_series(self, data: dict) -> List[TimeSeriesPoint]:
        """Parse Chartex API response into TimeSeriesPoint list."""
        points = []

        # Handle different response formats
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", data.get("results", []))
        else:
            return []

        for item in items:
            try:
                # Try different date field names
                date_str = item.get("date") or item.get("timestamp") or item.get("day")
                value = item.get("value") or item.get("count") or item.get("views") or 0

                if date_str:
                    if isinstance(date_str, str):
                        # Parse various date formats
                        for fmt in ["%Y-%m-%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S"]:
                            try:
                                parsed_date = datetime.strptime(date_str[:10], fmt[:len(date_str[:10])]).date()
                                break
                            except ValueError:
                                continue
                        else:
                            continue
                    else:
                        parsed_date = date_str

                    points.append(TimeSeriesPoint(date=parsed_date, value=float(value)))
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Failed to parse time series item: %s", e)
                continue

        # Sort by date
        points.sort(key=lambda p: p.date)
        return points

    def _sum_last_n_days(self, points: List[TimeSeriesPoint], days: int) -> int:
        """Sum values from the last N days."""
        if not points:
            return 0

        cutoff = date.today() - timedelta(days=days)
        return int(sum(p.value for p in points if p.date >= cutoff))


# Global client instance
chartex_client = ChartexClient()
