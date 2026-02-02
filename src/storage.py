"""Local storage for tracked artists using JSON file."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import TrackedArtist

logger = logging.getLogger(__name__)

# Default data file path
DATA_DIR = Path(__file__).parent.parent / "data"
TRACKED_ARTISTS_FILE = DATA_DIR / "tracked_artists.json"


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_tracked_artists() -> List[TrackedArtist]:
    """Load tracked artists from JSON file."""
    _ensure_data_dir()

    if not TRACKED_ARTISTS_FILE.exists():
        return []

    try:
        with TRACKED_ARTISTS_FILE.open("r") as f:
            data = json.load(f)

        artists = []
        for item in data:
            artists.append(TrackedArtist(
                sodatone_id=item.get("sodatone_id", ""),
                name=item.get("name", ""),
                spotify_id=item.get("spotify_id"),
                image_url=item.get("image_url"),
                added_at=item.get("added_at"),
            ))
        return artists

    except Exception as e:
        logger.error("Failed to load tracked artists: %s", e)
        return []


def save_tracked_artists(artists: List[TrackedArtist]) -> bool:
    """Save tracked artists to JSON file."""
    _ensure_data_dir()

    try:
        data = []
        for artist in artists:
            data.append({
                "sodatone_id": artist.sodatone_id,
                "name": artist.name,
                "spotify_id": artist.spotify_id,
                "image_url": artist.image_url,
                "added_at": artist.added_at,
            })

        with TRACKED_ARTISTS_FILE.open("w") as f:
            json.dump(data, f, indent=2)

        return True

    except Exception as e:
        logger.error("Failed to save tracked artists: %s", e)
        return False


def add_tracked_artist(
    sodatone_id: str,
    name: str,
    spotify_id: Optional[str] = None,
    image_url: Optional[str] = None,
) -> bool:
    """Add a new tracked artist."""
    artists = load_tracked_artists()

    # Check if already tracked
    for artist in artists:
        if artist.sodatone_id == sodatone_id:
            logger.info("Artist %s already tracked.", sodatone_id)
            return True

    # Add new artist
    new_artist = TrackedArtist(
        sodatone_id=sodatone_id,
        name=name,
        spotify_id=spotify_id,
        image_url=image_url,
        added_at=datetime.now().isoformat(),
    )
    artists.append(new_artist)

    return save_tracked_artists(artists)


def remove_tracked_artist(sodatone_id: str) -> bool:
    """Remove a tracked artist."""
    artists = load_tracked_artists()
    original_count = len(artists)

    artists = [a for a in artists if a.sodatone_id != sodatone_id]

    if len(artists) == original_count:
        logger.info("Artist %s not found in tracked list.", sodatone_id)
        return True

    return save_tracked_artists(artists)


def get_tracked_artist_ids() -> List[str]:
    """Get list of tracked Sodatone artist IDs."""
    artists = load_tracked_artists()
    return [a.sodatone_id for a in artists if a.sodatone_id]
