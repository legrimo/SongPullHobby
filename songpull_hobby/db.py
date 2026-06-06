from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Track:
    spotify_track_id: str
    playlist_id: str
    position: int
    name: str
    artists: str
    album: Optional[str]
    duration_ms: Optional[int]


@dataclass(frozen=True)
class Match:
    spotify_track_id: str
    youtube_url: str
    youtube_video_id: str
    title: str
    channel: Optional[str]
    confidence: float


class SongPullHobbyDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS playlists (
                    spotify_playlist_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner TEXT,
                    url TEXT,
                    last_synced_at TEXT
                );

                CREATE TABLE IF NOT EXISTS tracks (
                    spotify_track_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    artists TEXT NOT NULL,
                    album TEXT,
                    duration_ms INTEGER,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id TEXT NOT NULL,
                    spotify_track_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlist_id, spotify_track_id),
                    FOREIGN KEY (playlist_id)
                        REFERENCES playlists (spotify_playlist_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (spotify_track_id)
                        REFERENCES tracks (spotify_track_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS youtube_matches (
                    spotify_track_id TEXT PRIMARY KEY,
                    youtube_url TEXT NOT NULL,
                    youtube_video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    channel TEXT,
                    confidence REAL NOT NULL,
                    selected_at TEXT NOT NULL,
                    FOREIGN KEY (spotify_track_id)
                        REFERENCES tracks (spotify_track_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    tracks_seen INTEGER NOT NULL,
                    links_added INTEGER NOT NULL,
                    FOREIGN KEY (playlist_id)
                        REFERENCES playlists (spotify_playlist_id)
                        ON DELETE CASCADE
                );
                """
            )

    def upsert_playlist(
        self, playlist_id: str, name: str, owner: Optional[str], url: Optional[str]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO playlists (
                    spotify_playlist_id, name, owner, url, last_synced_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(spotify_playlist_id) DO UPDATE SET
                    name = excluded.name,
                    owner = excluded.owner,
                    url = excluded.url,
                    last_synced_at = excluded.last_synced_at
                """,
                (playlist_id, name, owner, url, utc_now()),
            )

    def upsert_tracks(self, tracks: Iterable[Track]) -> int:
        track_list = list(tracks)
        playlist_ids = {track.playlist_id for track in track_list}
        count = 0
        with self.connect() as connection:
            for playlist_id in playlist_ids:
                connection.execute(
                    "DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
                )

            for track in track_list:
                connection.execute(
                    """
                    INSERT INTO tracks (
                        spotify_track_id, name, artists, album, duration_ms, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(spotify_track_id) DO UPDATE SET
                        name = excluded.name,
                        artists = excluded.artists,
                        album = excluded.album,
                        duration_ms = excluded.duration_ms,
                        updated_at = excluded.updated_at
                    """,
                    (
                        track.spotify_track_id,
                        track.name,
                        track.artists,
                        track.album,
                        track.duration_ms,
                        utc_now(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO playlist_tracks (
                        playlist_id, spotify_track_id, position
                    )
                    VALUES (?, ?, ?)
                    """,
                    (track.playlist_id, track.spotify_track_id, track.position),
                )
                count += 1
        return count

    def save_match(self, match: Match) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO youtube_matches (
                    spotify_track_id, youtube_url, youtube_video_id, title,
                    channel, confidence, selected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(spotify_track_id) DO UPDATE SET
                    youtube_url = excluded.youtube_url,
                    youtube_video_id = excluded.youtube_video_id,
                    title = excluded.title,
                    channel = excluded.channel,
                    confidence = excluded.confidence,
                    selected_at = excluded.selected_at
                """,
                (
                    match.spotify_track_id,
                    match.youtube_url,
                    match.youtube_video_id,
                    match.title,
                    match.channel,
                    match.confidence,
                    utc_now(),
                ),
            )

    def tracks_needing_youtube(self, playlist_id: str, refresh: bool) -> List[sqlite3.Row]:
        query = """
            SELECT tracks.*, playlist_tracks.position
            FROM playlist_tracks
            JOIN tracks ON tracks.spotify_track_id = playlist_tracks.spotify_track_id
            LEFT JOIN youtube_matches
                ON youtube_matches.spotify_track_id = tracks.spotify_track_id
            WHERE playlist_tracks.playlist_id = ?
        """
        params: Tuple[object, ...] = (playlist_id,)
        if not refresh:
            query += " AND youtube_matches.spotify_track_id IS NULL"
        query += " ORDER BY playlist_tracks.position"

        with self.connect() as connection:
            return list(connection.execute(query, params))

    def playlist_rows(self, playlist_id_or_name: Optional[str] = None) -> List[sqlite3.Row]:
        query = """
            SELECT
                playlists.name AS playlist_name,
                playlist_tracks.position,
                tracks.name,
                tracks.artists,
                youtube_matches.youtube_url,
                youtube_matches.title AS youtube_title,
                youtube_matches.channel,
                youtube_matches.confidence
            FROM tracks
            JOIN playlist_tracks
                ON playlist_tracks.spotify_track_id = tracks.spotify_track_id
            JOIN playlists
                ON playlists.spotify_playlist_id = playlist_tracks.playlist_id
            LEFT JOIN youtube_matches
                ON youtube_matches.spotify_track_id = tracks.spotify_track_id
        """
        params: Tuple[object, ...] = ()
        if playlist_id_or_name:
            query += """
                WHERE playlists.spotify_playlist_id = ?
                   OR lower(playlists.name) = lower(?)
            """
            params = (playlist_id_or_name, playlist_id_or_name)
        query += " ORDER BY playlists.name, playlist_tracks.position"

        with self.connect() as connection:
            return list(connection.execute(query, params))

    def playlist_rows_with_youtube(self, playlist_id_or_name: str) -> List[sqlite3.Row]:
        query = """
            SELECT
                playlists.spotify_playlist_id,
                playlists.name AS playlist_name,
                playlist_tracks.position,
                tracks.name,
                tracks.artists,
                youtube_matches.youtube_url,
                youtube_matches.title AS youtube_title
            FROM tracks
            JOIN playlist_tracks
                ON playlist_tracks.spotify_track_id = tracks.spotify_track_id
            JOIN playlists
                ON playlists.spotify_playlist_id = playlist_tracks.playlist_id
            JOIN youtube_matches
                ON youtube_matches.spotify_track_id = tracks.spotify_track_id
            WHERE playlists.spotify_playlist_id = ?
               OR lower(playlists.name) = lower(?)
            ORDER BY playlist_tracks.position
        """
        params: Tuple[object, ...] = (playlist_id_or_name, playlist_id_or_name)

        with self.connect() as connection:
            return list(connection.execute(query, params))

    def playlist_id_for_name(self, name: str) -> Optional[str]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT spotify_playlist_id
                FROM playlists
                WHERE lower(name) = lower(?)
                """,
                (name,),
            ).fetchone()
            if not row:
                return None
            return str(row["spotify_playlist_id"])

    def add_sync_run(self, playlist_id: str, tracks_seen: int, links_added: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs (
                    playlist_id, started_at, tracks_seen, links_added
                )
                VALUES (?, ?, ?, ?)
                """,
                (playlist_id, utc_now(), tracks_seen, links_added),
            )
