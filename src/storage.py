"""Storage for tracked artists using PostgreSQL with session state cache.

Uses PostgreSQL for persistent storage across sessions/tabs.
Session state is used as a cache within the current session.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import streamlit as st

from .models import TrackedArtist
from .db import (
    load_tracked_artists_db,
    add_tracked_artist_db,
    remove_tracked_artist_db,
)

logger = logging.getLogger(__name__)

# Session state key for tracked artists cache
TRACKED_ARTISTS_KEY = "tracked_artists_list"
ARTISTS_LOADED_KEY = "tracked_artists_loaded_from_db"


def _sync_session_state(artists: List[TrackedArtist]) -> None:
    """Sync artists to session state cache."""
    data = []
    for artist in artists:
        data.append({
            "sodatone_id": artist.sodatone_id,
            "name": artist.name,
            "spotify_id": artist.spotify_id,
            "image_url": artist.image_url,
            "added_at": artist.added_at,
        })
    st.session_state[TRACKED_ARTISTS_KEY] = data


def load_tracked_artists() -> List[TrackedArtist]:
    """Load tracked artists from database (with session state cache)."""
    # On first load of session, fetch from database
    if not st.session_state.get(ARTISTS_LOADED_KEY, False):
        db_artists = load_tracked_artists_db()
        if db_artists:
            _sync_session_state(db_artists)
            st.session_state[ARTISTS_LOADED_KEY] = True
            return db_artists
        st.session_state[ARTISTS_LOADED_KEY] = True

    # Return from session state cache
    if TRACKED_ARTISTS_KEY not in st.session_state:
        st.session_state[TRACKED_ARTISTS_KEY] = []

    data = st.session_state[TRACKED_ARTISTS_KEY]
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


def add_tracked_artist(
    sodatone_id: str,
    name: str,
    spotify_id: Optional[str] = None,
    image_url: Optional[str] = None,
) -> bool:
    """Add a new tracked artist to database and session cache."""
    # Add to database first (uses ON CONFLICT to handle duplicates)
    db_success = add_tracked_artist_db(sodatone_id, name, spotify_id, image_url)

    if db_success:
        # Reload from database to get authoritative state and sync to session
        # This prevents race conditions where multiple tabs could add the same artist
        db_artists = load_tracked_artists_db()
        if db_artists:
            _sync_session_state(db_artists)
            return True

    # Fallback: if DB failed, check session cache and add locally
    artists = load_tracked_artists()
    for artist in artists:
        if artist.sodatone_id == sodatone_id:
            logger.info("Artist %s already tracked.", sodatone_id)
            return True

    logger.warning("Failed to add artist to database, using session state only")
    new_artist = TrackedArtist(
        sodatone_id=sodatone_id,
        name=name,
        spotify_id=spotify_id,
        image_url=image_url,
        added_at=datetime.now().isoformat(),
    )
    artists.append(new_artist)
    _sync_session_state(artists)

    return True


def remove_tracked_artist(sodatone_id: str) -> bool:
    """Remove a tracked artist from database and session cache."""
    artists = load_tracked_artists()
    original_count = len(artists)

    artists = [a for a in artists if a.sodatone_id != sodatone_id]

    if len(artists) == original_count:
        logger.info("Artist %s not found in tracked list.", sodatone_id)
        return True

    # Remove from database
    db_success = remove_tracked_artist_db(sodatone_id)
    if not db_success:
        logger.warning("Failed to remove artist from database")

    # Update session state cache
    _sync_session_state(artists)
    return True


def get_tracked_artist_ids() -> List[str]:
    """Get list of tracked Sodatone artist IDs."""
    artists = load_tracked_artists()
    return [a.sodatone_id for a in artists if a.sodatone_id]
