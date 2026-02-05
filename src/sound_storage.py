"""Storage for tracked TikTok sounds using Streamlit session state."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import streamlit as st

from .models import TrackedSound

logger = logging.getLogger(__name__)

# Session state key for tracked sounds
TRACKED_SOUNDS_KEY = "tracked_sounds_list"


def _get_tracked_sounds_list() -> List[dict]:
    """Get the tracked sounds list from session state."""
    if TRACKED_SOUNDS_KEY not in st.session_state:
        st.session_state[TRACKED_SOUNDS_KEY] = []
    return st.session_state[TRACKED_SOUNDS_KEY]


def _set_tracked_sounds_list(sounds: List[dict]) -> None:
    """Set the tracked sounds list in session state."""
    st.session_state[TRACKED_SOUNDS_KEY] = sounds


def load_tracked_sounds() -> List[TrackedSound]:
    """Load tracked sounds from session state."""
    data = _get_tracked_sounds_list()

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


def save_tracked_sounds(sounds: List[TrackedSound]) -> bool:
    """Save tracked sounds to session state."""
    try:
        data = []
        for sound in sounds:
            data.append({
                "sound_id": sound.sound_id,
                "name": sound.name,
                "artist_name": sound.artist_name,
                "tiktok_url": sound.tiktok_url,
                "added_at": sound.added_at,
            })
        _set_tracked_sounds_list(data)
        return True
    except Exception as e:
        logger.error("Failed to save tracked sounds: %s", e)
        return False


def add_tracked_sound(
    sound_id: str,
    name: str,
    artist_name: Optional[str] = None,
    tiktok_url: Optional[str] = None,
) -> bool:
    """Add a new tracked sound."""
    sounds = load_tracked_sounds()

    # Check if already tracked
    for sound in sounds:
        if sound.sound_id == sound_id:
            logger.info("Sound %s already tracked.", sound_id)
            return True

    # Add new sound
    new_sound = TrackedSound(
        sound_id=sound_id,
        name=name,
        artist_name=artist_name,
        tiktok_url=tiktok_url or f"https://www.tiktok.com/music/original-sound-{sound_id}",
        added_at=datetime.now().isoformat(),
    )
    sounds.append(new_sound)

    return save_tracked_sounds(sounds)


def remove_tracked_sound(sound_id: str) -> bool:
    """Remove a tracked sound."""
    sounds = load_tracked_sounds()
    original_count = len(sounds)

    sounds = [s for s in sounds if s.sound_id != sound_id]

    if len(sounds) == original_count:
        logger.info("Sound %s not found in tracked list.", sound_id)
        return True

    return save_tracked_sounds(sounds)


def get_tracked_sound_ids() -> List[str]:
    """Get list of tracked TikTok sound IDs."""
    sounds = load_tracked_sounds()
    return [s.sound_id for s in sounds if s.sound_id]
