"""Chartex API client for TikTok sound data."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import settings
from .models import TikTokSound, TimeSeriesPoint

logger = logging.getLogger(__name__)

# Retry decorator for transient failures
_retry_on_network_error = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
    reraise=True,
)


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

    @_retry_on_network_error
    def _make_request(self, url: str, params: dict) -> httpx.Response:
        """Make HTTP request with retry logic for transient failures."""
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            return client.get(url, headers=self._get_headers(), params=params)

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
            mode: 'daily' for daily values (note: 'total' not supported for views)
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit_days: Optional limit to last N days

        Returns:
            List of TimeSeriesPoint with view data
        """
        if not self.configured:
            logger.warning("Chartex not configured, returning empty data")
            return []

        url = f"{self._base_url}/tiktok-sounds/{sound_id}/stats/tiktok-video-views/"

        params = {"mode": "daily"}  # views only supports daily mode
        if start_date:
            params["start_date"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["end_date"] = end_date.strftime("%Y-%m-%d")
        if limit_days:
            params["limit_by_latest_days"] = limit_days

        try:
            response = self._make_request(url, params)

            logger.info("Chartex views API: %s %s - %s", response.status_code, url, response.text[:300] if response.text else "empty")

            if response.status_code in (401, 403):
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "Unknown error")
                    if "authentication" in error_msg.lower() or "credential" in error_msg.lower():
                        raise ChartexAPIError(f"Chartex auth failed: {error_msg}")
                except (ValueError, KeyError):
                    pass
                raise ChartexAPIError("Access denied - check credentials or add sound to Chartex dashboard")

            if response.status_code == 404:
                logger.warning("Sound %s not found in Chartex", sound_id)
                return []

            if response.status_code >= 400:
                raise ChartexAPIError(f"Chartex API error: {response.status_code}")

            if not response.text:
                return []

            data = response.json()
            return self._parse_time_series(data, metric="views")

        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.error("Chartex request failed after retries: %s", e)
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

        url = f"{self._base_url}/tiktok-sounds/{sound_id}/stats/tiktok-video-counts/"

        params = {"mode": mode}
        if start_date:
            params["start_date"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["end_date"] = end_date.strftime("%Y-%m-%d")
        if limit_days:
            params["limit_by_latest_days"] = limit_days

        try:
            response = self._make_request(url, params)

            logger.info("Chartex creates API: %s %s - %s", response.status_code, url, response.text[:300] if response.text else "empty")

            if response.status_code == 404:
                logger.warning("Sound %s not found in Chartex", sound_id)
                return []

            if response.status_code >= 400:
                logger.warning("Chartex creates API error: %s", response.status_code)
                return []

            if not response.text:
                return []

            data = response.json()
            return self._parse_time_series(data, metric="counts")

        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.error("Chartex request failed after retries: %s", e)
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
            response = self._make_request(url, params)

            logger.info("Chartex list sounds: %s - %s", response.status_code, response.text[:500] if response.text else "empty")

            if response.status_code >= 400:
                logger.warning("Chartex list error: %s", response.status_code)
                return []

            data = response.json()
            # Return the items list - API format is {"data": {"items": [...]}}
            if isinstance(data, dict):
                inner = data.get("data", data)
                if isinstance(inner, dict):
                    return inner.get("items", inner.get("results", []))
                elif isinstance(inner, list):
                    return inner
            elif isinstance(data, list):
                return data
            return []

        except Exception as e:
            logger.error("Chartex list failed after retries: %s", e)
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
        # Get daily time series (note: tiktok-video-views doesn't support total mode)
        views_daily = self.get_sound_views(sound_id, mode="daily", limit_days=lookback_days)
        creates_daily = self.get_sound_creates(sound_id, mode="daily", limit_days=lookback_days)

        # For totals, sum all available daily data (API doesn't provide cumulative totals for views)
        total_views = int(sum(p.value for p in views_daily)) if views_daily else 0
        total_creates = int(sum(p.value for p in creates_daily)) if creates_daily else 0

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

    def _parse_time_series(self, data: dict, metric: str = "views") -> List[TimeSeriesPoint]:
        """Parse Chartex API response into TimeSeriesPoint list."""
        points = []

        # Handle Chartex response format: {"data": {"video_views": [...]} or {"video_counts": [...]}}
        if isinstance(data, dict):
            inner_data = data.get("data", data)
            if isinstance(inner_data, dict):
                # Try to get the time series array
                if metric == "views":
                    items = inner_data.get("video_views", [])
                else:
                    items = inner_data.get("video_counts", [])
                # Fallback to other keys
                if not items:
                    items = inner_data.get("results", inner_data.get("items", []))
            elif isinstance(inner_data, list):
                items = inner_data
            else:
                items = []
        elif isinstance(data, list):
            items = data
        else:
            return []

        for item in items:
            try:
                # Get date
                date_str = item.get("date") or item.get("timestamp") or item.get("day")
                # Get value - try different field names
                value = (
                    item.get("daily_views") or
                    item.get("tiktok_video_count") or
                    item.get("value") or
                    item.get("count") or
                    item.get("views") or
                    0
                )

                if date_str:
                    if isinstance(date_str, str):
                        try:
                            parsed_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                        except ValueError:
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
