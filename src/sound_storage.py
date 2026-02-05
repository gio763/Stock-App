"""Storage for tracked TikTok sounds using PostgreSQL with session state cache."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import streamlit as st

from .models import TrackedSound
from .db import (
    load_tracked_sounds_db,
    add_tracked_sound_db,
    remove_tracked_sound_db,
)

logger = logging.getLogger(__name__)

# Session state keys
TRACKED_SOUNDS_KEY = "tracked_sounds_list"
SOUNDS_LOADED_KEY = "tracked_sounds_loaded_from_db"


def _sync_session_state(sounds: List[TrackedSound]) -> None:
    """Sync sounds to session state cache."""
    data = []
    for sound in sounds:
        data.append({
            "sound_id": sound.sound_id,
            "name": sound.name,
            "artist_name": sound.artist_name,
            "tiktok_url": sound.tiktok_url,
            "added_at": sound.added_at,
        })
    st.session_state[TRACKED_SOUNDS_KEY] = data


def load_tracked_sounds() -> List[TrackedSound]:
    """Load tracked sounds from database (with session state cache)."""
    # On first load of session, fetch from database
    if not st.session_state.get(SOUNDS_LOADED_KEY, False):
        db_sounds = load_tracked_sounds_db()
        if db_sounds:
            _sync_session_state(db_sounds)
            st.session_state[SOUNDS_LOADED_KEY] = True
            return db_sounds
        st.session_state[SOUNDS_LOADED_KEY] = True

    # Return from session state cache
    if TRACKED_SOUNDS_KEY not in st.session_state:
        st.session_state[TRACKED_SOUNDS_KEY] = []

    data = st.session_state[TRACKED_SOUNDS_KEY]
    sounds = []
    for item in data:
        sounds.append(TrackedSound(
            sound_id=item.get("sound_id", ""),
            name=item.get("name", ""),
            artist_name=item.get("artist_name"),
            tiktok_url=item.get("tiktok_url"),
            added_at=item.get("added_at"),
        ))
    return sounds


def add_tracked_sound(
    sound_id: str,
    name: str,
    artist_name: Optional[str] = None,
    tiktok_url: Optional[str] = None,
) -> bool:
    """Add a new tracked sound to database and session cache."""
    sounds = load_tracked_sounds()

    # Check if already tracked
    for sound in sounds:
        if sound.sound_id == sound_id:
            logger.info("Sound %s already tracked.", sound_id)
            return True

    # Add to database first
    final_url = tiktok_url or f"https://www.tiktok.com/music/original-sound-{sound_id}"
    db_success = add_tracked_sound_db(sound_id, name, artist_name, final_url)
    if not db_success:
        logger.warning("Failed to add sound to database, using session state only")

    # Add to session state cache
    new_sound = TrackedSound(
        sound_id=sound_id,
        name=name,
        artist_name=artist_name,
        tiktok_url=final_url,
        added_at=datetime.now().isoformat(),
    )
    sounds.append(new_sound)
    _sync_session_state(sounds)

    return True


def remove_tracked_sound(sound_id: str) -> bool:
    """Remove a tracked sound from database and session cache."""
    sounds = load_tracked_sounds()
    original_count = len(sounds)

    sounds = [s for s in sounds if s.sound_id != sound_id]

    if len(sounds) == original_count:
        logger.info("Sound %s not found in tracked list.", sound_id)
        return True

    # Remove from database
    db_success = remove_tracked_sound_db(sound_id)
    if not db_success:
        logger.warning("Failed to remove sound from database")

    # Update session state cache
    _sync_session_state(sounds)
    return True


def get_tracked_sound_ids() -> List[str]:
    """Get list of tracked TikTok sound IDs."""
    sounds = load_tracked_sounds()
    return [s.sound_id for s in sounds if s.sound_id]
