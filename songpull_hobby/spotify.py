from __future__ import annotations

import base64
import json
import re
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from songpull_hobby.db import Track


SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"


class SpotifyError(RuntimeError):
    pass


def extract_playlist_id(value: str) -> str:
    value = value.strip()
    match = re.search(r"open\.spotify\.com/playlist/([A-Za-z0-9]+)", value)
    if match:
        return match.group(1)

    if re.fullmatch(r"[A-Za-z0-9]{22}", value):
        return value

    raise SpotifyError("Expected a Spotify playlist URL or playlist ID.")


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_path: Path,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_path = token_path

    def authorize(self) -> None:
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SPOTIFY_SCOPES,
            "state": state,
        }
        auth_url = f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"
        callback = self._wait_for_callback(auth_url)

        if callback.get("state") != state:
            raise SpotifyError("Spotify authorization state did not match.")
        if "error" in callback:
            raise SpotifyError(f"Spotify authorization failed: {callback['error']}")
        if "code" not in callback:
            raise SpotifyError("Spotify authorization did not return a code.")

        token = self._request_token(
            {
                "grant_type": "authorization_code",
                "code": callback["code"],
                "redirect_uri": self.redirect_uri,
            }
        )
        self._save_token(token)

    def playlist(self, playlist_id: str) -> Dict[str, Any]:
        return self._get(f"/playlists/{playlist_id}")

    def current_user(self) -> Dict[str, Any]:
        return self._get("/me")

    def saved_token_info(self) -> Dict[str, Any]:
        token = self._load_token()
        return {
            "scope": token.get("scope", ""),
            "token_type": token.get("token_type", ""),
            "has_refresh_token": bool(token.get("refresh_token")),
        }

    def current_user_playlists(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        playlists: List[Dict[str, Any]] = []
        next_url: Optional[str] = f"{SPOTIFY_API_BASE}/me/playlists?limit=50"

        while next_url:
            payload = self._get_url(next_url)
            playlists.extend(payload.get("items", []))
            if limit and len(playlists) >= limit:
                return playlists[:limit]
            next_url = payload.get("next")

        return playlists

    def resolve_playlist_id(self, value: str) -> str:
        try:
            return extract_playlist_id(value)
        except SpotifyError:
            pass

        target = value.strip().lower()
        next_url: Optional[str] = f"{SPOTIFY_API_BASE}/me/playlists?limit=50"

        while next_url:
            payload = self._get_url(next_url)
            matches = [
                item for item in payload.get("items", [])
                if item.get("name", "").lower() == target
            ]
            if len(matches) == 1:
                return str(matches[0]["id"])
            if len(matches) > 1:
                raise SpotifyError(
                    f"Found multiple playlists named {value!r}. Use the playlist URL instead."
                )
            next_url = payload.get("next")

        raise SpotifyError(f"Could not find a visible playlist named {value!r}.")

    def probe_playlist(self, playlist_id: str) -> Dict[str, Any]:
        token = self._access_token()
        response = requests.get(
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code == 401:
            token = self._refresh_token()
            response = requests.get(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )

        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text

        return {"status_code": response.status_code, "payload": payload}

    def playlist_tracks(self, playlist_id: str, limit: Optional[int] = None) -> List[Track]:
        tracks: List[Track] = []
        next_url: Optional[str] = (
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?limit=100"
        )

        while next_url:
            payload = self._get_url(next_url)
            for item in payload["items"]:
                if item.get("is_local"):
                    continue
                track = item.get("track") or item.get("item")
                if not track or not track.get("id"):
                    continue
                if track.get("type") != "track":
                    continue

                tracks.append(
                    Track(
                        spotify_track_id=track["id"],
                        playlist_id=playlist_id,
                        position=len(tracks) + 1,
                        name=track["name"],
                        artists=", ".join(
                            artist["name"] for artist in track.get("artists", [])
                        ),
                        album=(track.get("album") or {}).get("name"),
                        duration_ms=track.get("duration_ms"),
                    )
                )
                if limit and len(tracks) >= limit:
                    return tracks
            next_url = payload.get("next")

        return tracks

    def _wait_for_callback(self, auth_url: str) -> Dict[str, str]:
        parsed = urllib.parse.urlparse(self.redirect_uri)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise SpotifyError("SPOTIFY_REDIRECT_URI must use localhost for setup.")

        response: Dict[str, str] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                nonlocal response
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                response = {key: values[0] for key, values in query.items()}
                body = b"SongPullHobby Spotify setup complete. You can close this tab."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = HTTPServer(
            (parsed.hostname or "127.0.0.1", parsed.port or 8888), CallbackHandler
        )
        webbrowser.open(auth_url)
        server.handle_request()
        server.server_close()
        return response

    def _auth_header(self) -> Dict[str, str]:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        encoded = base64.b64encode(raw).decode()
        return {"Authorization": f"Basic {encoded}"}

    def _request_token(self, data: Dict[str, str]) -> Dict[str, Any]:
        response = requests.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers=self._auth_header(),
            timeout=30,
        )
        if not response.ok:
            raise SpotifyError(f"Spotify token request failed: {response.text}")
        return response.json()

    def _load_token(self) -> Dict[str, Any]:
        if not self.token_path.exists():
            raise SpotifyError("Run `songpull-hobby setup` before syncing playlists.")
        return json.loads(self.token_path.read_text())

    def _save_token(self, token: Dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(token, indent=2))

    def _access_token(self) -> str:
        token = self._load_token()
        return str(token["access_token"])

    def _refresh_token(self) -> str:
        token = self._load_token()
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise SpotifyError("Saved Spotify token does not contain a refresh token.")

        refreshed = self._request_token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        refreshed.setdefault("refresh_token", refresh_token)
        self._save_token(refreshed)
        return str(refreshed["access_token"])

    def _get(self, path: str) -> Dict[str, Any]:
        return self._get_url(f"{SPOTIFY_API_BASE}{path}")

    def _get_url(self, url: str) -> Dict[str, Any]:
        token = self._access_token()
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code == 401:
            token = self._refresh_token()
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        if not response.ok:
            raise SpotifyError(
                f"Spotify API request failed for {url}: {response.text}"
            )
        return response.json()
