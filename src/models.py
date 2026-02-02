"""Data models for Stock App."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""
    date: date
    value: float


@dataclass
class ArtistSummary:
    """Basic artist information from Spotify."""
    name: str
    spotify_id: Optional[str] = None
    spotify_url: Optional[str] = None
    image_url: Optional[str] = None
    sodatone_id: Optional[str] = None


@dataclass
class SocialStats:
    """Social media statistics for an artist."""
    spotify_followers: int = 0
    spotify_followers_change: float = 0.0
    instagram_followers: int = 0
    instagram_followers_change: float = 0.0
    tiktok_followers: int = 0
    tiktok_followers_change: float = 0.0
    tiktok_sound_creates: int = 0
    tiktok_sound_creates_change: float = 0.0


@dataclass
class StreamingStats:
    """Streaming statistics for an artist."""
    weekly_us_streams: int = 0
    weekly_global_streams: int = 0
    daily_us_streams: int = 0
    daily_global_streams: int = 0
    us_wow_change: float = 0.0
    global_wow_change: float = 0.0


@dataclass
class ArtistMetrics:
    """Complete metrics for a tracked artist."""
    sodatone_id: str
    name: str
    artist_url: Optional[str] = None
    top_track_name: Optional[str] = None
    location: Optional[str] = None
    streaming: StreamingStats = field(default_factory=StreamingStats)
    social: SocialStats = field(default_factory=SocialStats)
    # Time series data for charts
    us_streams_history: List[TimeSeriesPoint] = field(default_factory=list)
    global_streams_history: List[TimeSeriesPoint] = field(default_factory=list)
    spotify_followers_history: List[TimeSeriesPoint] = field(default_factory=list)
    instagram_history: List[TimeSeriesPoint] = field(default_factory=list)
    tiktok_history: List[TimeSeriesPoint] = field(default_factory=list)


@dataclass
class TrackedArtist:
    """An artist being tracked in the user's portfolio."""
    sodatone_id: str
    name: str
    spotify_id: Optional[str] = None
    image_url: Optional[str] = None
    added_at: Optional[str] = None


@dataclass
class TrackData:
    """Track-level data for deal analysis with decay calculations."""
    track_id: str
    track_name: str
    album_name: Optional[str] = None
    release_date: Optional[date] = None
    spotify_popularity: int = 0
    weekly_us_audio_streams: int = 0
    weekly_global_audio_streams: int = 0
    weekly_us_video_streams: int = 0
    weeks_since_release: int = 0
