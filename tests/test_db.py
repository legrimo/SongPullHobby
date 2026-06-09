from songpull_hobby.db import Match, SongPullHobbyDB, Source, Track


def make_db(tmp_path):
    db = SongPullHobbyDB(tmp_path / "songpull-hobby.db")
    db.initialize()
    return db


def source(track_id="track-1", method="auto", title="Source Title"):
    return Source(
        playlist_id="playlist-1",
        spotify_track_id=track_id,
        provider="youtube",
        source_url=f"https://www.youtube.com/watch?v={track_id}",
        source_id=track_id,
        source_title=title,
        source_author="Artist - Topic",
        confidence=0.9,
        selection_method=method,
    )


def test_tracks_needing_youtube_skips_cached_matches_unless_refreshing(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", "Owner", "https://example.test")
    db.upsert_tracks(
        [
            Track("track-1", "playlist-1", 1, "Song One", "Artist One", "Album", 1000),
            Track("track-2", "playlist-1", 2, "Song Two", "Artist Two", None, None),
        ]
    )
    db.save_source(source(track_id="track-1"))

    missing = db.tracks_needing_youtube("playlist-1", refresh=False)
    refreshed = db.tracks_needing_youtube("playlist-1", refresh=True)

    assert [row["spotify_track_id"] for row in missing] == ["track-2"]
    assert [row["spotify_track_id"] for row in refreshed] == ["track-1", "track-2"]


def test_tracks_needing_youtube_does_not_refresh_manual_sources(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", "Owner", "https://example.test")
    db.upsert_tracks(
        [
            Track("track-1", "playlist-1", 1, "Song One", "Artist One", "Album", 1000),
            Track("track-2", "playlist-1", 2, "Song Two", "Artist Two", None, None),
        ]
    )
    db.save_source(source(track_id="track-1", method="manual"))
    db.save_source(source(track_id="track-2", method="auto"))

    refreshed = db.tracks_needing_youtube("playlist-1", refresh=True)

    assert [row["spotify_track_id"] for row in refreshed] == ["track-2"]


def test_upsert_tracks_replaces_playlist_membership(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", None, None)
    db.upsert_tracks(
        [
            Track("track-1", "playlist-1", 1, "Old Song", "Artist", None, None),
            Track("track-2", "playlist-1", 2, "Removed Song", "Artist", None, None),
        ]
    )

    count = db.upsert_tracks(
        [Track("track-1", "playlist-1", 1, "New Song", "Artist", "Album", 2000)]
    )
    rows = db.playlist_rows("My Playlist")

    assert count == 1
    assert len(rows) == 1
    assert rows[0]["name"] == "New Song"
    assert rows[0]["position"] == 1


def test_save_source_preserves_manual_override_by_default(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", None, None)
    db.upsert_tracks([Track("track-1", "playlist-1", 1, "Song", "Artist", None, None)])
    db.save_source(source(method="manual", title="Manual Source"), overwrite_manual=True)

    db.save_source(source(method="auto", title="Automatic Source"))
    row = db.playlist_track_with_source("playlist-1", "track-1")

    assert row["source_title"] == "Manual Source"
    assert row["selection_method"] == "manual"


def test_playlist_rows_with_sources_returns_only_matched_rows(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", "Owner", None)
    db.upsert_tracks(
        [
            Track("track-1", "playlist-1", 1, "Matched", "Artist", None, None),
            Track("track-2", "playlist-1", 2, "Missing", "Artist", None, None),
        ]
    )
    db.save_source(source(track_id="track-1", title="Matched - Artist"))

    rows = db.playlist_rows_with_sources("playlist-1")

    assert len(rows) == 1
    assert rows[0]["name"] == "Matched"
    assert rows[0]["youtube_url"].endswith("track-1")


def test_save_match_is_migrated_to_track_sources_on_initialize(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", "Owner", None)
    db.upsert_tracks([Track("track-1", "playlist-1", 1, "Matched", "Artist", None, None)])
    db.save_match(
        Match(
            spotify_track_id="track-1",
            youtube_url="https://www.youtube.com/watch?v=abc123",
            youtube_video_id="abc123",
            title="Matched - Artist",
            channel=None,
            confidence=1.0,
        )
    )

    db.initialize()
    row = db.playlist_track_with_source("playlist-1", "track-1")

    assert row["provider"] == "youtube"
    assert row["source_id"] == "abc123"
    assert row["selection_method"] == "auto"


def test_manual_source_rows_include_export_metadata(tmp_path):
    db = make_db(tmp_path)
    db.upsert_playlist("playlist-1", "My Playlist", "Owner", None)
    db.upsert_tracks([Track("track-1", "playlist-1", 1, "Matched", "Artist", "Album", 2000)])
    db.save_source(source(track_id="track-1", method="manual"), overwrite_manual=True)

    rows = db.manual_source_rows("My Playlist")

    assert len(rows) == 1
    assert rows[0]["playlist_name"] == "My Playlist"
    assert rows[0]["spotify_track_name"] == "Matched"
    assert rows[0]["selection_method"] == "manual"
