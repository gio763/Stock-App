"""PostgreSQL database for persistent storage of tracked artists and sounds."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List, Optional

from .models import TrackedArtist, TrackedSound

logger = logging.getLogger(__name__)

# Database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_connection():
    """Get a database connection."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")

    import psycopg2
    # Handle Render's postgres:// vs postgresql:// URL format
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(url)


def init_db():
    """Initialize database tables if they don't exist."""
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set, skipping database initialization")
        return False

    try:
        conn = get_connection()
        cur = conn.cursor()

        # Create tracked_artists table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tracked_artists (
                sodatone_id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                spotify_id VARCHAR(50),
                image_url TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create tracked_sounds table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tracked_sounds (
                sound_id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                artist_name VARCHAR(255),
                tiktok_url TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database tables initialized successfully")
        return True
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)
        return False


# ========== Artist Storage ==========

def load_tracked_artists_db() -> List[TrackedArtist]:
    """Load tracked artists from database."""
    if not DATABASE_URL:
        return []

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT sodatone_id, name, spotify_id, image_url, added_at
            FROM tracked_artists
            ORDER BY added_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        artists = []
        for row in rows:
            artists.append(TrackedArtist(
                sodatone_id=row[0],
                name=row[1],
                spotify_id=row[2],
                image_url=row[3],
                added_at=row[4].isoformat() if row[4] else None,
            ))
        return artists
    except Exception as e:
        logger.error("Failed to load tracked artists: %s", e)
        return []


def add_tracked_artist_db(
    sodatone_id: str,
    name: str,
    spotify_id: Optional[str] = None,
    image_url: Optional[str] = None,
) -> bool:
    """Add a tracked artist to database."""
    if not DATABASE_URL:
        return False

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tracked_artists (sodatone_id, name, spotify_id, image_url, added_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (sodatone_id) DO UPDATE SET
                name = EXCLUDED.name,
                spotify_id = EXCLUDED.spotify_id,
                image_url = EXCLUDED.image_url
        """, (sodatone_id, name, spotify_id, image_url, datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error("Failed to add tracked artist: %s", e)
        return False


def remove_tracked_artist_db(sodatone_id: str) -> bool:
    """Remove a tracked artist from database."""
    if not DATABASE_URL:
        return False

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM tracked_artists WHERE sodatone_id = %s", (sodatone_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error("Failed to remove tracked artist: %s", e)
        return False


# ========== Sound Storage ==========

def load_tracked_sounds_db() -> List[TrackedSound]:
    """Load tracked sounds from database."""
    if not DATABASE_URL:
        return []

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT sound_id, name, artist_name, tiktok_url, added_at
            FROM tracked_sounds
            ORDER BY added_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        sounds = []
        for row in rows:
            sounds.append(TrackedSound(
                sound_id=row[0],
                name=row[1],
                artist_name=row[2],
                tiktok_url=row[3],
                added_at=row[4].isoformat() if row[4] else None,
            ))
        return sounds
    except Exception as e:
        logger.error("Failed to load tracked sounds: %s", e)
        return []


def add_tracked_sound_db(
    sound_id: str,
    name: str,
    artist_name: Optional[str] = None,
    tiktok_url: Optional[str] = None,
) -> bool:
    """Add a tracked sound to database."""
    if not DATABASE_URL:
        return False

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tracked_sounds (sound_id, name, artist_name, tiktok_url, added_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (sound_id) DO UPDATE SET
                name = EXCLUDED.name,
                artist_name = EXCLUDED.artist_name,
                tiktok_url = EXCLUDED.tiktok_url
        """, (sound_id, name, artist_name, tiktok_url, datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error("Failed to add tracked sound: %s", e)
        return False


def remove_tracked_sound_db(sound_id: str) -> bool:
    """Remove a tracked sound from database."""
    if not DATABASE_URL:
        return False

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM tracked_sounds WHERE sound_id = %s", (sound_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error("Failed to remove tracked sound: %s", e)
        return False
