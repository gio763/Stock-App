"""Snowflake client for Stock App using SQL API with JWT authentication."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jwt
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import settings
from .models import ArtistMetrics, SocialStats, StreamingStats, TimeSeriesPoint, TrackedArtist, TrackData
from .queries import (
    ARTIST_METRICS_QUERY,
    ARTIST_SEARCH_QUERY,
    ARTIST_SUMMARY_QUERY,
    CATALOG_TRACK_COUNT_QUERY,
    SOCIAL_TIME_SERIES_QUERY,
    SPOTIFY_TO_SODATONE_QUERY,
    STREAMING_TIME_SERIES_QUERY,
    TRACK_CATALOG_WITH_STREAMS_QUERY,
)

logger = logging.getLogger(__name__)

_DEFAULT_API_TIMEOUT_SECONDS = 60
_DEFAULT_POLL_TIMEOUT_SECONDS = 120
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0
_JWT_LIFETIME_SECONDS = 55 * 60


class SnowflakeSqlApiError(RuntimeError):
    """Raised when Snowflake SQL API requests fail."""


class SnowflakeClient:
    """Fetch Snowflake query results via the Snowflake SQL API (HTTP)."""

    def __init__(self) -> None:
        self._config = settings.snowflake

    def search_artists(self, search_term: str) -> List[Dict[str, Any]]:
        """Search for artists by name."""
        if not search_term or len(search_term) < 2:
            return []

        # Escape single quotes for SQL
        safe_term = search_term.replace("'", "''")
        sql = ARTIST_SEARCH_QUERY.format(search_term=safe_term)

        try:
            rows = self._execute_statement(sql)
            return rows
        except Exception as e:
            logger.error("Artist search failed: %s", e)
            return []

    def get_artist_metrics(self, artist_ids: List[str], fast: bool = True) -> Dict[str, ArtistMetrics]:
        """Fetch current metrics for the provided Sodatone artist IDs.

        Args:
            artist_ids: List of Sodatone artist IDs
            fast: If True, use simplified query for faster results (default)
        """
        if not artist_ids:
            return {}

        # Sanitize IDs (must be numeric)
        safe_ids = [aid for aid in artist_ids if str(aid).isdigit()]
        if not safe_ids:
            return {}

        id_filter = ", ".join(safe_ids)
        # Use fast summary query by default, full query for detailed view
        sql = ARTIST_SUMMARY_QUERY.format(id_filter=id_filter) if fast else ARTIST_METRICS_QUERY.format(id_filter=id_filter)

        try:
            rows = self._execute_statement(sql)
        except Exception as e:
            logger.error("Failed to fetch artist metrics: %s", e)
            return {}

        results: Dict[str, ArtistMetrics] = {}
        for row in rows:
            record = {k.upper(): v for k, v in row.items()}
            sodatone_id = str(record.get("SODATONE_ID", ""))
            if not sodatone_id:
                continue

            results[sodatone_id] = ArtistMetrics(
                sodatone_id=sodatone_id,
                name=record.get("ARTIST_NAME") or "",
                artist_url=record.get("ARTIST_URL"),
                top_track_name=record.get("TOP_TRACK_NAME"),
                location=record.get("LOCATION"),
                streaming=StreamingStats(
                    weekly_us_streams=_safe_int(record.get("WEEKLY_US_STREAMS")),
                    weekly_global_streams=_safe_int(record.get("WEEKLY_GLOBAL_STREAMS")),
                    daily_us_streams=_safe_int(record.get("DAILY_US_STREAMS")),
                    daily_global_streams=_safe_int(record.get("DAILY_GLOBAL_STREAMS")),
                    us_wow_change=_safe_float(record.get("US_WOW_CHANGE")),
                    global_wow_change=_safe_float(record.get("GLOBAL_WOW_CHANGE")),
                ),
                social=SocialStats(
                    spotify_followers=_safe_int(record.get("SPOTIFY_FOLLOWERS")),
                    spotify_followers_change=_safe_float(record.get("SPOTIFY_CHANGE")),
                    instagram_followers=_safe_int(record.get("INSTAGRAM_FOLLOWERS")),
                    instagram_followers_change=_safe_float(record.get("INSTAGRAM_CHANGE")),
                    tiktok_followers=_safe_int(record.get("TIKTOK_FOLLOWERS")),
                    tiktok_followers_change=_safe_float(record.get("TIKTOK_CHANGE")),
                    tiktok_sound_creates=_safe_int(record.get("TIKTOK_SOUND_CREATES")),
                    tiktok_sound_creates_change=_safe_float(record.get("TIKTOK_SOUND_CHANGE")),
                ),
            )

        return results

    def get_streaming_time_series(
        self, artist_ids: List[str], lookback_months: int = 24
    ) -> Dict[str, List[TimeSeriesPoint]]:
        """Fetch daily streaming time series for artists."""
        if not artist_ids:
            return {}

        safe_ids = [aid for aid in artist_ids if str(aid).isdigit()]
        if not safe_ids:
            return {}

        id_filter = ", ".join(safe_ids)
        sql = STREAMING_TIME_SERIES_QUERY.format(id_filter=id_filter, lookback_months=lookback_months)

        try:
            rows = self._execute_statement(sql)
        except Exception as e:
            logger.error("Failed to fetch streaming time series: %s", e)
            return {}

        us_streams: List[TimeSeriesPoint] = []
        global_streams: List[TimeSeriesPoint] = []
        us_video_streams: List[TimeSeriesPoint] = []

        for row in rows:
            record = {k.upper(): v for k, v in row.items()}
            date_val = record.get("DATE")
            if date_val:
                from datetime import datetime
                if isinstance(date_val, str):
                    date_val = datetime.strptime(date_val[:10], "%Y-%m-%d").date()
                us_streams.append(TimeSeriesPoint(date=date_val, value=_safe_float(record.get("US_STREAMS"))))
                global_streams.append(TimeSeriesPoint(date=date_val, value=_safe_float(record.get("GLOBAL_STREAMS"))))
                us_video_streams.append(TimeSeriesPoint(date=date_val, value=_safe_float(record.get("US_VIDEO_STREAMS"))))

        return {
            "us_streams": us_streams,
            "global_streams": global_streams,
            "us_video_streams": us_video_streams,
        }

    def get_social_time_series(
        self, artist_ids: List[str], lookback_months: int = 24
    ) -> Dict[str, List[TimeSeriesPoint]]:
        """Fetch daily social follower time series for artists."""
        if not artist_ids:
            return {}

        safe_ids = [aid for aid in artist_ids if str(aid).isdigit()]
        if not safe_ids:
            return {}

        id_filter = ", ".join(safe_ids)
        sql = SOCIAL_TIME_SERIES_QUERY.format(id_filter=id_filter, lookback_months=lookback_months)

        try:
            rows = self._execute_statement(sql)
        except Exception as e:
            logger.error("Failed to fetch social time series: %s", e)
            return {}

        spotify: List[TimeSeriesPoint] = []
        instagram: List[TimeSeriesPoint] = []
        tiktok: List[TimeSeriesPoint] = []

        for row in rows:
            record = {k.upper(): v for k, v in row.items()}
            date_val = record.get("DATE")
            platform = (record.get("PLATFORM") or "").lower()
            followers = _safe_float(record.get("FOLLOWERS"))

            if date_val:
                from datetime import datetime
                if isinstance(date_val, str):
                    date_val = datetime.strptime(date_val[:10], "%Y-%m-%d").date()
                point = TimeSeriesPoint(date=date_val, value=followers)

                if platform == "spotify":
                    spotify.append(point)
                elif platform == "instagram":
                    instagram.append(point)
                elif platform == "tiktok":
                    tiktok.append(point)

        return {
            "spotify": spotify,
            "instagram": instagram,
            "tiktok": tiktok,
        }

    def lookup_sodatone_ids(self, spotify_ids: List[str]) -> Dict[str, str]:
        """Lookup Sodatone IDs from Spotify IDs."""
        if not spotify_ids:
            return {}

        # Quote and join Spotify IDs
        quoted_ids = ", ".join(f"'{sid}'" for sid in spotify_ids if sid)
        if not quoted_ids:
            return {}

        sql = SPOTIFY_TO_SODATONE_QUERY.format(spotify_ids=quoted_ids)

        try:
            rows = self._execute_statement(sql)
        except Exception as e:
            logger.error("Failed to lookup Sodatone IDs: %s", e)
            return {}

        result: Dict[str, str] = {}
        for row in rows:
            record = {k.upper(): v for k, v in row.items()}
            spotify_id = record.get("SPOTIFY_ID")
            sodatone_id = record.get("SODATONE_ID")
            if spotify_id and sodatone_id:
                result[spotify_id] = str(sodatone_id)

        return result

    def get_catalog_track_count(self, artist_id: str) -> int:
        """Get the number of tracks in an artist's catalog."""
        if not artist_id or not str(artist_id).isdigit():
            return 0

        sql = CATALOG_TRACK_COUNT_QUERY.format(id_filter=artist_id)

        try:
            rows = self._execute_statement(sql)
            if rows:
                record = {k.upper(): v for k, v in rows[0].items()}
                return _safe_int(record.get("TRACK_COUNT"))
        except Exception as e:
            logger.error("Failed to get catalog track count: %s", e)

        return 0

    def get_track_catalog(self, artist_id: str) -> List[TrackData]:
        """Get track-level catalog data with release dates and current streams.

        Returns list of TrackData objects with per-track streaming and age info
        for use in individual track decay calculations.
        """
        if not artist_id or not str(artist_id).isdigit():
            return []

        sql = TRACK_CATALOG_WITH_STREAMS_QUERY.format(id_filter=artist_id)

        try:
            rows = self._execute_statement(sql)
        except Exception as e:
            logger.error("Failed to get track catalog: %s", e)
            return []

        tracks: List[TrackData] = []
        for row in rows:
            record = {k.upper(): v for k, v in row.items()}

            # Parse release date
            release_date = None
            release_date_val = record.get("RELEASE_DATE")
            if release_date_val:
                from datetime import datetime
                if isinstance(release_date_val, str):
                    try:
                        release_date = datetime.strptime(release_date_val[:10], "%Y-%m-%d").date()
                    except ValueError:
                        pass
                elif hasattr(release_date_val, 'date'):
                    release_date = release_date_val.date() if hasattr(release_date_val, 'date') else release_date_val
                else:
                    release_date = release_date_val

            tracks.append(TrackData(
                track_id=str(record.get("TRACK_ID", "")),
                track_name=record.get("TRACK_NAME") or "",
                album_name=record.get("ALBUM_NAME"),
                release_date=release_date,
                spotify_popularity=_safe_int(record.get("SPOTIFY_POPULARITY")),
                weekly_us_audio_streams=_safe_int(record.get("WEEKLY_US_AUDIO_STREAMS")),
                weekly_global_audio_streams=_safe_int(record.get("WEEKLY_GLOBAL_AUDIO_STREAMS")),
                weekly_us_video_streams=_safe_int(record.get("WEEKLY_US_VIDEO_STREAMS")),
                weeks_since_release=_safe_int(record.get("WEEKS_SINCE_RELEASE")),
            ))

        return tracks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def _execute_statement(self, statement: str) -> List[Dict[str, Any]]:
        """Execute a SQL statement via Snowflake Python connector with key-pair auth."""
        logger.info(
            "Executing Snowflake query (account=%s, user=%s)",
            self._config.connector_account_identifier or self._config.account,
            self._config.user,
        )
        return self._execute_via_connector(statement)

    def _poll_for_results(self, base_url: str, headers: Dict[str, str], statement_handle: str) -> List[Dict[str, Any]]:
        """Poll for async query results."""
        url = f"{base_url}/api/v2/statements/{statement_handle}"
        deadline = time.time() + _DEFAULT_POLL_TIMEOUT_SECONDS

        while time.time() < deadline:
            response = requests.get(url, headers=headers, timeout=_DEFAULT_API_TIMEOUT_SECONDS)
            if response.status_code >= 400:
                raise SnowflakeSqlApiError(f"Snowflake poll error ({response.status_code}): {response.text[:500]}")

            body = response.json()
            status = (body.get("statementStatus") or "").upper()

            if status in {"SUCCESS", "SUCCEEDED", "COMPLETE"} and "data" in body:
                return _parse_sql_api_result(body)
            if status in {"FAILED", "CANCELED", "ABORTED"}:
                raise SnowflakeSqlApiError(f"Statement failed ({status}): {body}")

            time.sleep(_DEFAULT_POLL_INTERVAL_SECONDS)

        raise SnowflakeSqlApiError(f"Timed out waiting for results (handle={statement_handle}).")

    def _execute_via_connector(self, statement: str) -> List[Dict[str, Any]]:
        """Fallback to Snowflake Python connector."""
        import snowflake.connector

        private_key = self._load_private_key()
        connector_account = self._config.connector_account_identifier or self._config.account

        # Convert private key to DER bytes for newer snowflake-connector versions
        private_key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        conn = snowflake.connector.connect(
            account=connector_account,
            user=self._config.user,
            role=self._config.role,
            warehouse=self._config.warehouse,
            database=self._config.database,
            schema=self._config.schema,
            private_key=private_key_bytes,
        )
        try:
            cur = conn.cursor(snowflake.connector.DictCursor)
            try:
                cur.execute(statement)
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            finally:
                cur.close()
        finally:
            conn.close()

    def _load_private_key(self):
        """Load RSA private key from environment variable or file.

        Supports (checked in order):
        1. SNOWFLAKE_PRIVATE_KEY_B64 - base64-encoded key (recommended for cloud)
        2. SNOWFLAKE_PRIVATE_KEY - key content directly
        3. SNOWFLAKE_PRIVATE_KEY_PATH - path to key file (local dev)
        """
        # Try base64-encoded key first (best for cloud - no newline issues)
        key_b64 = os.environ.get("SNOWFLAKE_PRIVATE_KEY_B64")
        if key_b64:
            logger.info("Loading private key from SNOWFLAKE_PRIVATE_KEY_B64")
            try:
                key_content = base64.b64decode(key_b64).decode("utf-8")
                return serialization.load_pem_private_key(
                    key_content.encode(),
                    password=None,
                    backend=default_backend(),
                )
            except Exception as e:
                logger.error("Failed to decode base64 key: %s", e)
                raise RuntimeError(f"Invalid base64 key: {e}")

        # Try direct key content
        key_content = os.environ.get("SNOWFLAKE_PRIVATE_KEY")
        if key_content:
            logger.info("Loading private key from SNOWFLAKE_PRIVATE_KEY")
            key_content = key_content.replace("\\n", "\n")
            try:
                return serialization.load_pem_private_key(
                    key_content.encode(),
                    password=None,
                    backend=default_backend(),
                )
            except Exception as e:
                logger.error("Failed to parse key: %s", e)
                raise RuntimeError(f"Invalid key content: {e}")

        # Fall back to file path
        key_path_str = os.environ.get(self._config.private_key_path_env_var)
        if not key_path_str:
            raise RuntimeError(
                "Set SNOWFLAKE_PRIVATE_KEY_B64, SNOWFLAKE_PRIVATE_KEY, or "
                f"'{self._config.private_key_path_env_var}'"
            )

        key_path = Path(key_path_str).expanduser()
        if not key_path.exists():
            raise RuntimeError(f"Private key file not found: {key_path}")

        with key_path.open("rb") as key_file:
            return serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend(),
            )

    def _build_keypair_jwt(self) -> Tuple[str, str]:
        """Build a KEYPAIR_JWT for Snowflake SQL API authentication."""
        private_key = self._load_private_key()

        public_der = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fp = base64.b64encode(hashlib.sha256(public_der).digest()).decode("ascii")
        fp_label = f"SHA256:{fp}"

        account_raw = (self._config.jwt_account_identifier or self._config.account).strip()
        account = _normalize_account_identifier(account_raw)
        user = self._config.user.upper()
        qualified_username = f"{account}.{user}"

        now = int(time.time()) - 30
        payload = {
            "iss": f"{qualified_username}.{fp_label}",
            "sub": qualified_username,
            "iat": now,
            "exp": now + _JWT_LIFETIME_SECONDS,
        }

        token = jwt.encode(payload, key=private_key, algorithm="RS256", headers={"typ": "JWT"})
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token, fp_label


def _normalize_account_identifier(account: str) -> str:
    """Normalize account identifier for JWT."""
    normalized = account.strip()
    if ".global" not in normalized:
        if "." in normalized:
            normalized = normalized.split(".", 1)[0]
    else:
        if "-" in normalized:
            normalized = normalized.split("-", 1)[0]
    return normalized.upper()


def _should_fallback_to_connector(response: requests.Response) -> bool:
    """Check if we should fallback to Python connector."""
    msg = response.text.lower()
    return "jwt token is invalid" in msg or response.status_code == 401


def _parse_sql_api_result(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse SQL API response into list of dicts."""
    meta = body.get("resultSetMetaData") or {}
    row_types = meta.get("rowType") or []
    columns = [col.get("name") for col in row_types]
    data = body.get("data") or []

    results: List[Dict[str, Any]] = []
    for row in data:
        record = {str(columns[i]).upper(): row[i] for i in range(min(len(columns), len(row)))}
        results.append(record)
    return results


def _safe_int(value: Any) -> int:
    """Safely convert value to int."""
    if value is None:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _safe_float(value: Any) -> float:
    """Safely convert value to float."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# Global client instance
snowflake_client = SnowflakeClient()
