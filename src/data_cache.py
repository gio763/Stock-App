"""Local data cache for artist metrics - stores historical data to avoid repeated API calls."""

from __future__ import annotations

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

from .models import TimeSeriesPoint

logger = logging.getLogger(__name__)

# Cache file path
DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "metrics_cache.json"


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _serialize_date(d: date) -> str:
    """Convert date to ISO string."""
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()


def _deserialize_date(s: str) -> date:
    """Convert ISO string to date."""
    return datetime.strptime(s, "%Y-%m-%d").date()


class DataCache:
    """Local cache for artist metrics data."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        _ensure_data_dir()
        if CACHE_FILE.exists():
            try:
                with CACHE_FILE.open("r") as f:
                    self._cache = json.load(f)
            except Exception as e:
                logger.error("Failed to load cache: %s", e)
                self._cache = {}
        else:
            self._cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        _ensure_data_dir()
        try:
            with CACHE_FILE.open("w") as f:
                json.dump(self._cache, f, indent=2, default=str)
        except Exception as e:
            logger.error("Failed to save cache: %s", e)

    def get_last_refresh(self, artist_id: str) -> Optional[datetime]:
        """Get the last refresh time for an artist."""
        artist_data = self._cache.get(artist_id, {})
        last_refresh = artist_data.get("last_refresh")
        if last_refresh:
            return datetime.fromisoformat(last_refresh)
        return None

    def needs_refresh(self, artist_id: str, max_age_hours: int = 24) -> bool:
        """Check if artist data needs refreshing."""
        last_refresh = self.get_last_refresh(artist_id)
        if not last_refresh:
            return True
        age = datetime.now() - last_refresh
        return age > timedelta(hours=max_age_hours)

    def set_streaming_data(self, artist_id: str, us_streams: List[TimeSeriesPoint],
                           global_streams: List[TimeSeriesPoint],
                           us_video_streams: Optional[List[TimeSeriesPoint]] = None) -> None:
        """Store streaming time series data."""
        if artist_id not in self._cache:
            self._cache[artist_id] = {}

        self._cache[artist_id]["streaming"] = {
            "us_streams": [{"date": _serialize_date(p.date), "value": p.value} for p in us_streams],
            "global_streams": [{"date": _serialize_date(p.date), "value": p.value} for p in global_streams],
            "us_video_streams": [{"date": _serialize_date(p.date), "value": p.value} for p in (us_video_streams or [])],
        }
        self._cache[artist_id]["last_refresh"] = datetime.now().isoformat()
        self._save()

    def get_streaming_data(self, artist_id: str, period: str = "1Y") -> Dict[str, List[TimeSeriesPoint]]:
        """Get streaming time series data, filtered by period."""
        artist_data = self._cache.get(artist_id, {})
        streaming = artist_data.get("streaming", {})

        # Calculate cutoff date based on period
        cutoff = self._get_cutoff_date(period)

        us_streams = []
        for p in streaming.get("us_streams", []):
            d = _deserialize_date(p["date"])
            if d >= cutoff:
                us_streams.append(TimeSeriesPoint(date=d, value=p["value"]))

        global_streams = []
        for p in streaming.get("global_streams", []):
            d = _deserialize_date(p["date"])
            if d >= cutoff:
                global_streams.append(TimeSeriesPoint(date=d, value=p["value"]))

        us_video_streams = []
        for p in streaming.get("us_video_streams", []):
            d = _deserialize_date(p["date"])
            if d >= cutoff:
                us_video_streams.append(TimeSeriesPoint(date=d, value=p["value"]))

        return {
            "us_streams": sorted(us_streams, key=lambda x: x.date),
            "global_streams": sorted(global_streams, key=lambda x: x.date),
            "us_video_streams": sorted(us_video_streams, key=lambda x: x.date),
        }

    def set_social_data(self, artist_id: str, spotify: List[TimeSeriesPoint],
                        instagram: List[TimeSeriesPoint], tiktok: List[TimeSeriesPoint]) -> None:
        """Store social time series data."""
        if artist_id not in self._cache:
            self._cache[artist_id] = {}

        self._cache[artist_id]["social"] = {
            "spotify": [{"date": _serialize_date(p.date), "value": p.value} for p in spotify],
            "instagram": [{"date": _serialize_date(p.date), "value": p.value} for p in instagram],
            "tiktok": [{"date": _serialize_date(p.date), "value": p.value} for p in tiktok],
        }
        self._cache[artist_id]["last_refresh"] = datetime.now().isoformat()
        self._save()

    def get_social_data(self, artist_id: str, period: str = "1Y") -> Dict[str, List[TimeSeriesPoint]]:
        """Get social time series data, filtered by period."""
        artist_data = self._cache.get(artist_id, {})
        social = artist_data.get("social", {})

        cutoff = self._get_cutoff_date(period)

        result = {}
        for platform in ["spotify", "instagram", "tiktok"]:
            points = []
            for p in social.get(platform, []):
                d = _deserialize_date(p["date"])
                if d >= cutoff:
                    points.append(TimeSeriesPoint(date=d, value=p["value"]))
            result[platform] = sorted(points, key=lambda x: x.date)

        return result

    def _get_cutoff_date(self, period: str) -> date:
        """Calculate cutoff date based on period string."""
        today = date.today()
        if period == "1W":
            return today - timedelta(days=7)
        elif period == "1M":
            return today - timedelta(days=30)
        elif period == "3M":
            return today - timedelta(days=90)
        elif period == "6M":
            return today - timedelta(days=180)
        elif period == "1Y":
            return today - timedelta(days=365)
        elif period == "2Y":
            return today - timedelta(days=730)
        else:
            return today - timedelta(days=30)

    def get_sparkline_values(self, artist_id: str, metric: str = "us_streams") -> List[float]:
        """Get values for sparkline chart (last 14 data points)."""
        if metric in ["us_streams", "global_streams"]:
            data = self.get_streaming_data(artist_id, "1M")
            points = data.get(metric, [])
        else:
            data = self.get_social_data(artist_id, "1M")
            points = data.get(metric, [])

        # Return last 14 values
        values = [p.value for p in points[-14:]]
        return values if len(values) >= 2 else []

    def clear_artist(self, artist_id: str) -> None:
        """Clear cached data for an artist."""
        if artist_id in self._cache:
            del self._cache[artist_id]
            self._save()

    def clear_all(self) -> None:
        """Clear all cached data."""
        self._cache = {}
        self._save()


# Global cache instance
data_cache = DataCache()
