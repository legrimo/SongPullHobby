import csv
import json

from songpull_hobby import cli
from songpull_hobby.db import Source


class FakeDB:
    saved_source = None

    def playlist_rows(self, playlist):
        assert playlist == "My Playlist"
        return [
            {
                "playlist_name": "My Playlist",
                "position": 1,
                "name": "Song One",
                "artists": "Artist One",
                "provider": "youtube",
                "source_url": "https://www.youtube.com/watch?v=abc123",
                "source_title": "Song One - Artist One",
                "source_author": "Artist One - Topic",
                "confidence": 0.91,
                "selection_method": "auto",
            },
            {
                "playlist_name": "My Playlist",
                "position": 2,
                "name": "Song Two",
                "artists": "Artist Two",
                "provider": None,
                "source_url": None,
                "source_title": None,
                "source_author": None,
                "confidence": None,
                "selection_method": None,
            },
        ]

    def manual_source_rows(self, playlist):
        assert playlist == "My Playlist"
        return [
            {
                "playlist_name": "My Playlist",
                "playlist_id": "playlist-1",
                "position": 1,
                "spotify_track_id": "track-1",
                "spotify_track_name": "Song One",
                "spotify_artists": "Artist One",
                "spotify_album": "Album",
                "spotify_duration_ms": 225000,
                "provider": "youtube",
                "source_url": "https://www.youtube.com/watch?v=abc123",
                "source_id": "abc123",
                "source_title": "Song One - Artist One",
                "source_author": "Artist One - Topic",
                "source_confidence": 1.0,
                "selected_at": "2026-01-01T00:00:00+00:00",
                "selection_method": "manual",
            }
        ]

    def resolve_playlist_id(self, playlist):
        assert playlist == "My Playlist"
        return "playlist-1"

    def resolve_playlist_track(self, playlist_id, track):
        assert playlist_id == "playlist-1"
        assert track == "1"
        return {"spotify_track_id": "track-1", "name": "Song One"}

    def save_source(self, source, overwrite_manual=False):
        assert overwrite_manual is True
        self.saved_source = source


class FakeYouTubeClient:
    def source_from_url(self, link):
        assert link == "https://www.youtube.com/watch?v=abc123"
        return Source(
            playlist_id="",
            spotify_track_id="",
            provider="youtube",
            source_url=link,
            source_id="abc123",
            source_title="Song One - Artist One",
            source_author="Artist One - Topic",
            confidence=1.0,
            selection_method="manual",
        )


def test_export_writes_csv_rows(monkeypatch, tmp_path):
    output = tmp_path / "exports" / "playlist.csv"
    monkeypatch.setattr(cli, "database", lambda: FakeDB())

    cli.export(output=output, playlist="My Playlist")

    with output.open(newline="") as file:
        rows = list(csv.reader(file))

    assert rows == [
        [
            "playlist",
            "position",
            "song",
            "artists",
            "source_provider",
            "source_url",
            "source_title",
            "source_author",
            "confidence",
            "selection_method",
        ],
        [
            "My Playlist",
            "1",
            "Song One",
            "Artist One",
            "youtube",
            "https://www.youtube.com/watch?v=abc123",
            "Song One - Artist One",
            "Artist One - Topic",
            "0.91",
            "auto",
        ],
        ["My Playlist", "2", "Song Two", "Artist Two", "", "", "", "", "", ""],
    ]


def test_export_manual_matches_writes_jsonl(monkeypatch, tmp_path):
    output = tmp_path / "exports" / "manual.jsonl"
    monkeypatch.setattr(cli, "database", lambda: FakeDB())

    cli.export_manual_matches(
        output=output, playlist="My Playlist", output_format="jsonl"
    )

    records = [json.loads(line) for line in output.read_text().splitlines()]

    assert records[0]["spotify_track_id"] == "track-1"
    assert records[0]["source_id"] == "abc123"
    assert records[0]["selection_method"] == "manual"


def test_set_source_validates_with_youtube_data_api(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cli, "database", lambda: db)
    monkeypatch.setattr(cli, "require_youtube_client", lambda: FakeYouTubeClient())

    cli.set_source("My Playlist", "1", "https://www.youtube.com/watch?v=abc123")

    assert db.saved_source.spotify_track_id == "track-1"
    assert db.saved_source.source_id == "abc123"
    assert db.saved_source.selection_method == "manual"
