from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from songpull_hobby.config import ensure_data_dir, load_settings
from songpull_hobby.db import SongPullHobbyDB, Source
from songpull_hobby.spotify import SpotifyClient, SpotifyError, extract_playlist_id
from songpull_hobby.youtube import YouTubeClient, YouTubeError, YouTubeQuotaExceededError


app = typer.Typer(help="Sync Spotify playlists and save matching YouTube links.")
console = Console()


def fail(message: str) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)


def database() -> SongPullHobbyDB:
    settings = load_settings()
    ensure_data_dir(settings)
    db = SongPullHobbyDB(settings.db_path)
    db.initialize()
    return db


def spotify_client() -> SpotifyClient:
    settings = load_settings()
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        fail(
            "Missing Spotify credentials. Run `cp .env.example .env`, then set "
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env. See README.md "
            "for the Spotify Developer Dashboard setup steps."
        )

    return SpotifyClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=settings.spotify_redirect_uri,
        token_path=settings.spotify_token_path,
    )


def youtube_client() -> Optional[YouTubeClient]:
    settings = load_settings()
    if not settings.youtube_api_key:
        return None
    return YouTubeClient(settings.youtube_api_key)


def require_youtube_client() -> YouTubeClient:
    youtube = youtube_client()
    if not youtube:
        fail("Set YOUTUBE_API_KEY in .env first so the YouTube Data API can validate links.")
    return youtube


def format_score(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def resolve_saved_playlist(db: SongPullHobbyDB, playlist: str) -> str:
    playlist_id = db.resolve_playlist_id(playlist)
    if not playlist_id:
        fail(
            "Could not find a saved playlist with that name or ID. "
            "Run `songpull-hobby sync` first."
        )
    return playlist_id


def resolve_saved_track(db: SongPullHobbyDB, playlist_id: str, track: str):
    row = db.resolve_playlist_track(playlist_id, track)
    if not row:
        fail(
            "Could not find a unique saved track by that position, Spotify track ID, "
            "or exact track name."
        )
    return row


def source_from_match(playlist_id: str, match) -> Source:
    return Source(
        playlist_id=playlist_id,
        spotify_track_id=match.spotify_track_id,
        provider="youtube",
        source_url=match.youtube_url,
        source_id=match.youtube_video_id,
        source_title=match.title,
        source_author=match.channel,
        confidence=match.confidence,
        selection_method="auto",
    )


def save_youtube_match_for_track(
    db: SongPullHobbyDB,
    youtube: YouTubeClient,
    playlist_id: str,
    row,
    youtube_query_variants: int,
    overwrite_manual: bool = False,
) -> bool:
    match = youtube.find_best_match(
        spotify_track_id=row["spotify_track_id"],
        name=row["name"],
        artists=row["artists"],
        duration_ms=row["duration_ms"],
        max_query_variants=1,
        fallback_query_variants=youtube_query_variants,
    )
    if not match:
        return False

    db.save_match(match)
    db.save_source(source_from_match(playlist_id, match), overwrite_manual=overwrite_manual)
    return True


def source_row_for_track(db: SongPullHobbyDB, playlist: str, track: str):
    playlist_id = resolve_saved_playlist(db, playlist)
    track_row = resolve_saved_track(db, playlist_id, track)
    row = db.playlist_track_with_source(playlist_id, track_row["spotify_track_id"])
    if not row:
        fail(
            "No saved source link found for that track. Run `songpull-hobby sync` "
            "or `songpull-hobby set-source` first."
        )
    return row


def print_source_row(row) -> None:
    table = Table(title=f"{row['playlist_name']} / {row['position']}. {row['name']}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Track", row["name"])
    table.add_row("Artists", row["artists"])
    table.add_row("Provider", row["provider"] or "")
    table.add_row("Link", row["source_url"] or "")
    table.add_row("Match", row["source_title"] or "")
    table.add_row("Author", row["source_author"] or "")
    table.add_row("Score", format_score(row["confidence"]))
    table.add_row("Method", row["selection_method"] or "")
    console.print(table)


def manual_match_record(row) -> dict[str, object]:
    return {
        "playlist_name": row["playlist_name"],
        "playlist_id": row["playlist_id"],
        "position": row["position"],
        "spotify_track_id": row["spotify_track_id"],
        "spotify_track_name": row["spotify_track_name"],
        "spotify_artists": row["spotify_artists"],
        "spotify_album": row["spotify_album"],
        "spotify_duration_ms": row["spotify_duration_ms"],
        "provider": row["provider"],
        "source_url": row["source_url"],
        "source_id": row["source_id"],
        "source_title": row["source_title"],
        "source_author": row["source_author"],
        "source_confidence": row["source_confidence"],
        "selected_at": row["selected_at"],
        "selection_method": row["selection_method"],
    }


@app.command()
def setup() -> None:
    """Initialize storage and authorize SongPullHobby with Spotify."""
    database()
    try:
        spotify_client().authorize()
    except SpotifyError as exc:
        fail(str(exc))
    console.print("[green]Spotify setup complete.[/green]")
    console.print("Next: run `songpull-hobby get-playlists --limit 5`.")


@app.command()
def sync(
    playlist: str = typer.Argument(..., help="Spotify playlist URL, ID, or exact name."),
    limit: Optional[int] = typer.Option(None, help="Only sync the first N tracks."),
    refresh_youtube: bool = typer.Option(
        False, help="Search YouTube again even when a saved link exists."
    ),
    youtube_query_variants: int = typer.Option(
        4,
        min=1,
        help=(
            "Maximum YouTube search query variants to try per track. Sync starts "
            "with one quota-conscious query and spends extra variants only as a "
            "fallback for no or weak matches."
        ),
    ),
) -> None:
    """Fetch playlist tracks and fill in missing YouTube links."""
    db = database()

    try:
        spotify = spotify_client()
        try:
            playlist_id = spotify.resolve_playlist_id(playlist)
        except SpotifyError:
            playlist_id = db.playlist_id_for_name(playlist)
            if not playlist_id:
                raise
        playlist_payload = spotify.playlist(playlist_id)
        tracks = spotify.playlist_tracks(playlist_id, limit=limit)
    except SpotifyError as exc:
        fail(str(exc))

    owner = (playlist_payload.get("owner") or {}).get("display_name")
    playlist_url = (playlist_payload.get("external_urls") or {}).get("spotify")
    db.upsert_playlist(
        playlist_id=playlist_id,
        name=playlist_payload["name"],
        owner=owner,
        url=playlist_url,
    )
    track_count = db.upsert_tracks(tracks)

    youtube = youtube_client()
    links_added = 0
    youtube_quota_exhausted = False
    if youtube:
        for row in db.tracks_needing_youtube(playlist_id, refresh=refresh_youtube):
            try:
                matched = save_youtube_match_for_track(
                    db,
                    youtube,
                    playlist_id,
                    row,
                    youtube_query_variants=youtube_query_variants,
                )
            except YouTubeQuotaExceededError as exc:
                console.print(f"[yellow]{exc}[/yellow]")
                youtube_quota_exhausted = True
                break
            except YouTubeError as exc:
                fail(str(exc))

            if matched:
                links_added += 1
    else:
        console.print(
            "[yellow]YOUTUBE_API_KEY is not set, so YouTube matching was skipped.[/yellow]"
        )

    db.add_sync_run(playlist_id, tracks_seen=track_count, links_added=links_added)
    console.print(
        f"[green]Synced {track_count} tracks from {playlist_payload['name']}."
        f" Added {links_added} YouTube links.[/green]"
    )
    if youtube_quota_exhausted:
        console.print(
            "[yellow]YouTube matching stopped early because the API quota was "
            "exhausted.[/yellow]"
        )


@app.command("debug-spotify")
def debug_spotify(
    playlist: Optional[str] = typer.Argument(
        None, help="Optional Spotify playlist URL or playlist ID to test."
    ),
) -> None:
    """Print safe Spotify auth diagnostics for troubleshooting access errors."""
    try:
        spotify = spotify_client()
        token_info = spotify.saved_token_info()
        user = spotify.current_user()
        playlists = spotify.current_user_playlists()
    except SpotifyError as exc:
        fail(str(exc))

    console.print("[bold]Spotify token[/bold]")
    console.print(f"Scopes: {token_info.get('scope') or '[yellow]none reported[/yellow]'}")
    console.print(f"Token type: {token_info.get('token_type') or '[yellow]unknown[/yellow]'}")
    console.print(f"Has refresh token: {token_info.get('has_refresh_token')}")

    console.print("\n[bold]Authorized Spotify user[/bold]")
    console.print(f"Display name: {user.get('display_name')}")
    console.print(f"User ID: {user.get('id')}")
    console.print(f"Email: {user.get('email') or '[yellow]not returned[/yellow]'}")

    table = Table(title="Visible Playlists")
    table.add_column("Name")
    table.add_column("ID")
    table.add_column("Owner")
    table.add_column("Public")

    for item in playlists:
        owner = item.get("owner") or {}
        table.add_row(
            item.get("name", ""),
            item.get("id", ""),
            owner.get("display_name") or owner.get("id") or "",
            str(item.get("public")),
        )
    console.print(table)

    if playlist:
        playlist_id = extract_playlist_id(playlist)
        try:
            probe = spotify.probe_playlist(playlist_id)
        except SpotifyError as exc:
            fail(str(exc))

        console.print("\n[bold]Playlist probe[/bold]")
        console.print(f"Playlist ID: {playlist_id}")
        console.print(f"Status code: {probe['status_code']}")
        payload = probe["payload"]
        if isinstance(payload, dict) and probe["status_code"] == 200:
            owner = payload.get("owner") or {}
            console.print(f"Name: {payload.get('name')}")
            console.print(f"Owner: {owner.get('display_name') or owner.get('id')}")
            console.print(f"Public: {payload.get('public')}")
            tracks = payload.get("tracks") or {}
            console.print(f"Track count: {tracks.get('total')}")
        else:
            console.print(f"Response: {payload}")


@app.command("get-playlists")
def get_playlists(
    limit: Optional[int] = typer.Option(
        None, help="Maximum number of visible playlists to list."
    ),
) -> None:
    """List Spotify playlists visible to the authorized account."""
    try:
        spotify = spotify_client()
        user = spotify.current_user()
        playlists = spotify.current_user_playlists(limit=limit)
    except SpotifyError as exc:
        fail(str(exc))

    console.print(
        f"[bold]Authorized Spotify user:[/bold] "
        f"{user.get('display_name') or user.get('id')}"
    )

    if not playlists:
        console.print("[yellow]No visible playlists found.[/yellow]")
        return

    table = Table(title="Available Spotify Playlists")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Owner")
    table.add_column("Public")
    table.add_column("Tracks", justify="right")
    table.add_column("ID")
    table.add_column("URL")

    for index, item in enumerate(playlists, start=1):
        owner = item.get("owner") or {}
        tracks = item.get("tracks") or {}
        external_urls = item.get("external_urls") or {}
        table.add_row(
            str(index),
            item.get("name", ""),
            owner.get("display_name") or owner.get("id") or "",
            str(item.get("public")),
            str(tracks.get("total") or ""),
            item.get("id", ""),
            external_urls.get("spotify", ""),
        )

    console.print(table)


@app.command()
def show(
    playlist: Optional[str] = typer.Argument(
        None, help="Optional playlist name or Spotify playlist ID."
    ),
) -> None:
    """Show saved tracks and YouTube links."""
    rows = database().playlist_rows(playlist)
    if not rows:
        console.print("[yellow]No saved tracks found. Run `songpull-hobby sync` first.[/yellow]")
        return

    table = Table(title="SongPullHobby Library")
    table.add_column("#", justify="right")
    table.add_column("Song")
    table.add_column("Artist")
    table.add_column("Link")
    table.add_column("Source Title")
    table.add_column("Score", justify="right")
    table.add_column("Method")

    for row in rows:
        table.add_row(
            str(row["position"]),
            row["name"],
            row["artists"],
            row["source_url"] or "[yellow]missing[/yellow]",
            row["source_title"] or "",
            format_score(row["confidence"]),
            row["selection_method"] or "",
        )

    console.print(table)


@app.command("set-source")
def set_source(
    playlist: str = typer.Argument(..., help="Playlist name or Spotify playlist ID."),
    track: str = typer.Argument(
        ..., help="Track position, Spotify track ID, or unique exact track name."
    ),
    link: str = typer.Argument(..., help="YouTube link to use for this playlist track."),
) -> None:
    """Manually replace the source link for one saved playlist track."""
    db = database()
    playlist_id = resolve_saved_playlist(db, playlist)
    track_row = resolve_saved_track(db, playlist_id, track)

    try:
        validated = require_youtube_client().source_from_url(link)
    except YouTubeError as exc:
        fail(str(exc))

    source = Source(
        playlist_id=playlist_id,
        spotify_track_id=track_row["spotify_track_id"],
        provider=validated.provider,
        source_url=validated.source_url,
        source_id=validated.source_id,
        source_title=validated.source_title,
        source_author=validated.source_author,
        confidence=validated.confidence,
        selection_method=validated.selection_method,
    )
    db.save_source(source, overwrite_manual=True)
    console.print(
        f"[green]Updated source for {track_row['name']}:[/green] "
        f"{source.source_title}"
    )


@app.command("match-track")
def match_track(
    playlist: str = typer.Argument(..., help="Playlist name or Spotify playlist ID."),
    track: str = typer.Argument(
        ..., help="Track position, Spotify track ID, or unique exact track name."
    ),
    youtube_query_variants: int = typer.Option(
        4,
        min=1,
        help="Maximum YouTube search query variants to try for this track.",
    ),
    overwrite_manual: bool = typer.Option(
        False, help="Replace an existing manual source override."
    ),
) -> None:
    """Search YouTube again for one saved playlist track."""
    youtube = require_youtube_client()
    db = database()
    playlist_id = resolve_saved_playlist(db, playlist)
    track_row = resolve_saved_track(db, playlist_id, track)
    existing = db.playlist_track_with_source(playlist_id, track_row["spotify_track_id"])
    if (
        existing
        and existing["selection_method"] == "manual"
        and not overwrite_manual
    ):
        fail("Track has a manual source. Pass `--overwrite-manual` to replace it.")

    try:
        matched = save_youtube_match_for_track(
            db,
            youtube,
            playlist_id,
            track_row,
            youtube_query_variants=youtube_query_variants,
            overwrite_manual=overwrite_manual,
        )
    except YouTubeError as exc:
        fail(str(exc))

    if not matched:
        fail("No confident YouTube match found for that track.")

    row = db.playlist_track_with_source(playlist_id, track_row["spotify_track_id"])
    console.print(f"[green]Matched source for {track_row['name']}.[/green]")
    if row:
        print_source_row(row)


@app.command("get-link")
def get_link(
    playlist: str = typer.Argument(..., help="Playlist name or Spotify playlist ID."),
    track: str = typer.Argument(
        ..., help="Track position, Spotify track ID, or unique exact track name."
    ),
) -> None:
    """Show the saved link and match score for one playlist track."""
    print_source_row(source_row_for_track(database(), playlist, track))


@app.command("export-manual-matches")
def export_manual_matches(
    output: Path = typer.Argument(..., help="JSONL or CSV path to write."),
    playlist: Optional[str] = typer.Option(
        None, help="Optional playlist name or Spotify playlist ID."
    ),
    output_format: str = typer.Option(
        "jsonl", "--format", help="Export format: jsonl or csv."
    ),
) -> None:
    """Export manually selected source matches for analysis."""
    normalized_format = output_format.lower()
    if normalized_format not in {"jsonl", "csv"}:
        fail("Export format must be `jsonl` or `csv`.")

    rows = database().manual_source_rows(playlist)
    records = [manual_match_record(row) for row in rows]
    output.parent.mkdir(parents=True, exist_ok=True)

    if normalized_format == "jsonl":
        with output.open("w") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        fieldnames = [
            "playlist_name",
            "playlist_id",
            "position",
            "spotify_track_id",
            "spotify_track_name",
            "spotify_artists",
            "spotify_album",
            "spotify_duration_ms",
            "provider",
            "source_url",
            "source_id",
            "source_title",
            "source_author",
            "source_confidence",
            "selected_at",
            "selection_method",
        ]
        with output.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    console.print(f"[green]Exported {len(records)} manual matches to {output}.[/green]")


@app.command()
def export(
    output: Path = typer.Argument(..., help="CSV path to write."),
    playlist: Optional[str] = typer.Option(
        None, help="Optional playlist name or Spotify playlist ID."
    ),
) -> None:
    """Export saved rows to CSV."""
    rows = database().playlist_rows(playlist)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
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
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["playlist_name"],
                    row["position"],
                    row["name"],
                    row["artists"],
                    row["provider"] or "",
                    row["source_url"] or "",
                    row["source_title"] or "",
                    row["source_author"] or "",
                    format_score(row["confidence"]),
                    row["selection_method"] or "",
                ]
            )

    console.print(f"[green]Exported {len(rows)} rows to {output}.[/green]")


if __name__ == "__main__":
    app()
