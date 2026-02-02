"""Spotify Web API client for finding similar artists."""

from __future__ import annotations

import base64
import logging
import time
from typing import List, Optional

import httpx

from .config import settings
from .models import ArtistSummary

logger = logging.getLogger(__name__)


class SpotifyAPIError(RuntimeError):
    """Raised when Spotify API returns an error response."""


class SpotifyClient:
    """Wrapper around Spotify Web API using client credentials."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires_at: float = 0

    @property
    def configured(self) -> bool:
        return settings.spotify.configured

    def _get_access_token(self) -> str:
        """Get or refresh access token."""
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        client_id = settings.spotify.client_id
        client_secret = settings.spotify.client_secret

        if not client_id or not client_secret:
            raise SpotifyAPIError("Spotify credentials not configured.")

        credentials = f"{client_id}:{client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(settings.spotify.token_url, data=data, headers=headers)

        if response.status_code >= 400:
            raise SpotifyAPIError(f"Failed to obtain Spotify access token: {response.text}")

        payload = response.json()
        self._token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        self._token_expires_at = time.time() + expires_in

        if not self._token:
            raise SpotifyAPIError("Spotify token response did not include access_token.")

        return self._token

    def search_artist(self, query: str) -> Optional[ArtistSummary]:
        """Search for an artist by name."""
        if not self.configured:
            return None

        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        with httpx.Client(timeout=30.0) as client:
            params = {"q": query, "type": "artist", "limit": 1}
            response = client.get(
                f"{settings.spotify.api_base_url}/search",
                params=params,
                headers=headers,
            )

        if response.status_code >= 400:
            logger.error("Spotify search failed: %s", response.text)
            return None

        data = response.json()
        artists = data.get("artists", {}).get("items", [])

        if not artists:
            return None

        return self._to_summary(artists[0])

    def get_similar_artists(self, artist: ArtistSummary) -> List[ArtistSummary]:
        """Get similar artists for a given artist.

        Note: Spotify deprecated their related-artists and recommendations endpoints
        in November 2024. We now use alternative methods: collaborations from tracks/albums
        and genre-based search.
        """
        if not self.configured or not artist.spotify_id:
            return []

        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Try multiple strategies in order
        for fetcher in [
            self._fetch_via_top_tracks_and_albums,
            self._fetch_via_genre_search,
            self._fetch_via_collaborations,
        ]:
            artists = fetcher(artist, headers)
            if artists:
                return artists

        return []

    def _fetch_via_top_tracks_and_albums(self, artist: ArtistSummary, headers: dict) -> List[ArtistSummary]:
        """Fetch similar artists from top tracks and albums (appears_on)."""
        seen_ids = {artist.spotify_id}
        collaborator_ids: List[str] = []

        with httpx.Client(timeout=30.0) as client:
            # Get top tracks
            response = client.get(
                f"{settings.spotify.api_base_url}/artists/{artist.spotify_id}/top-tracks",
                params={"market": "US"},
                headers=headers,
            )
            if response.status_code == 200:
                tracks = response.json().get("tracks", []) or []
                for track in tracks:
                    for track_artist in track.get("artists", []):
                        aid = track_artist.get("id")
                        if aid and aid not in seen_ids:
                            seen_ids.add(aid)
                            collaborator_ids.append(aid)

            # Get albums including "appears_on" for collaborations
            response = client.get(
                f"{settings.spotify.api_base_url}/artists/{artist.spotify_id}/albums",
                params={"include_groups": "single,album,appears_on", "limit": 50, "market": "US"},
                headers=headers,
            )
            if response.status_code == 200:
                albums = response.json().get("items", []) or []
                for album in albums[:20]:
                    album_id = album.get("id")
                    if not album_id:
                        continue
                    # Get album tracks to find more collaborators
                    resp2 = client.get(
                        f"{settings.spotify.api_base_url}/albums/{album_id}/tracks",
                        params={"limit": 50},
                        headers=headers,
                    )
                    if resp2.status_code == 200:
                        for track in resp2.json().get("items", []):
                            for track_artist in track.get("artists", []):
                                aid = track_artist.get("id")
                                if aid and aid not in seen_ids:
                                    seen_ids.add(aid)
                                    collaborator_ids.append(aid)

        if not collaborator_ids:
            return []

        # Fetch full artist details
        return self._fetch_artist_details(collaborator_ids, artist.spotify_id, headers)

    def _fetch_via_genre_search(self, artist: ArtistSummary, headers: dict) -> List[ArtistSummary]:
        """Fetch similar artists by searching the same genre."""
        with httpx.Client(timeout=30.0) as client:
            # First get artist's genres
            response = client.get(
                f"{settings.spotify.api_base_url}/artists/{artist.spotify_id}",
                headers=headers,
            )
            if response.status_code >= 400:
                return []

            artist_data = response.json()
            genres = artist_data.get("genres", [])

            if not genres:
                return []

            # Search for artists in the same genre
            genre = genres[0]
            response = client.get(
                f"{settings.spotify.api_base_url}/search",
                params={"q": f'genre:"{genre}"', "type": "artist", "limit": 20},
                headers=headers,
            )
            if response.status_code >= 400:
                return []

            items = response.json().get("artists", {}).get("items", []) or []
            summaries = []
            for item in items:
                if item and item.get("id") != artist.spotify_id:
                    summaries.append(self._to_summary(item))
                if len(summaries) >= 12:
                    break
            return summaries

    def _fetch_artist_details(self, artist_ids: List[str], exclude_id: str, headers: dict) -> List[ArtistSummary]:
        """Fetch full artist details for a list of IDs."""
        summaries: List[ArtistSummary] = []
        with httpx.Client(timeout=30.0) as client:
            for i in range(0, len(artist_ids), 50):
                chunk = artist_ids[i : i + 50]
                response = client.get(
                    f"{settings.spotify.api_base_url}/artists",
                    params={"ids": ",".join(chunk)},
                    headers=headers,
                )
                if response.status_code >= 400:
                    continue

                items = response.json().get("artists", []) or []
                for item in items:
                    if item and item.get("id") != exclude_id:
                        summaries.append(self._to_summary(item))
                    if len(summaries) >= 12:
                        return summaries
        return summaries[:12]

    def _fetch_via_collaborations(self, artist: ArtistSummary, headers: dict) -> List[ArtistSummary]:
        """Fetch similar artists via track collaborations."""
        if not artist.name:
            return []

        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{settings.spotify.api_base_url}/search",
                params={"q": f'artist:"{artist.name}"', "type": "track", "limit": 50},
                headers=headers,
            )

        if response.status_code >= 400:
            logger.warning("Spotify track search failed: %s", response.text)
            return []

        tracks = response.json().get("tracks", {}).get("items", []) or []
        seen_ids = {artist.spotify_id}
        collaborator_ids: List[str] = []

        for track in tracks:
            for track_artist in track.get("artists", []):
                aid = track_artist.get("id")
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    collaborator_ids.append(aid)

        if not collaborator_ids:
            return []

        # Fetch full artist details
        summaries: List[ArtistSummary] = []
        with httpx.Client(timeout=30.0) as client:
            for i in range(0, len(collaborator_ids), 50):
                chunk = collaborator_ids[i : i + 50]
                response = client.get(
                    f"{settings.spotify.api_base_url}/artists",
                    params={"ids": ",".join(chunk)},
                    headers=headers,
                )
                if response.status_code >= 400:
                    continue

                items = response.json().get("artists", []) or []
                for item in items:
                    if item and item.get("id") != artist.spotify_id:
                        summaries.append(self._to_summary(item))
                    if len(summaries) >= 12:
                        return summaries

        return summaries[:12]

    @staticmethod
    def _to_summary(payload: dict) -> ArtistSummary:
        """Convert Spotify API response to ArtistSummary."""
        artist_id = payload.get("id")
        images = payload.get("images") or []
        image_url = images[0]["url"] if images else None
        href = payload.get("external_urls", {}).get("spotify") or (
            f"https://open.spotify.com/artist/{artist_id}" if artist_id else None
        )
        return ArtistSummary(
            name=payload.get("name") or "",
            spotify_id=artist_id,
            spotify_url=href,
            image_url=image_url,
        )


# Global client instance
spotify_client = SpotifyClient()
