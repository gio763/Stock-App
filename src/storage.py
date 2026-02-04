"""Storage for tracked artists using Streamlit session state.

On Railway and other cloud platforms, the filesystem is ephemeral.
Using session state ensures data persists within the user's session.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import streamlit as st

from .models import TrackedArtist

logger = logging.getLogger(__name__)

# Session state key for tracked artists
TRACKED_ARTISTS_KEY = "tracked_artists_list"


def _get_tracked_artists_list() -> List[dict]:
    """Get the tracked artists list from session state."""
    if TRACKED_ARTISTS_KEY not in st.session_state:
        st.session_state[TRACKED_ARTISTS_KEY] = []
    return st.session_state[TRACKED_ARTISTS_KEY]


def _set_tracked_artists_list(artists: List[dict]) -> None:
    """Set the tracked artists list in session state."""
    st.session_state[TRACKED_ARTISTS_KEY] = artists


def load_tracked_artists() -> List[TrackedArtist]:
    """Load tracked artists from session state."""
    data = _get_tracked_artists_list()

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


def save_tracked_artists(artists: List[TrackedArtist]) -> bool:
    """Save tracked artists to session state."""
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
        _set_tracked_artists_list(data)
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
