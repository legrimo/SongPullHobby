from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from songpull_hobby.config import ensure_data_dir, load_settings
from songpull_hobby.db import SongPullHobbyDB
from songpull_hobby.spotify import SpotifyClient, SpotifyError, extract_playlist_id
from songpull_hobby.youtube import YouTubeClient, YouTubeError


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
        fail("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env first.")

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


def executable_path(name: str) -> Optional[str]:
    path = shutil.which(name)
    if path:
        return path

    venv_candidate = Path(sys.executable).with_name(name)
    if venv_candidate.exists():
        return str(venv_candidate)

    return None


def ffmpeg_path() -> str:
    path = executable_path("ffmpeg")
    if path:
        return path

    try:
        import imageio_ffmpeg
    except ImportError:
        fail("`ffmpeg` is required. Install it with `brew install ffmpeg`.")

    return imageio_ffmpeg.get_ffmpeg_exe()


def safe_path_name(value: str, max_length: int = 120) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    return (cleaned[:max_length].rstrip(" .") or "untitled")


@app.command()
def setup() -> None:
    """Initialize storage and authorize SongPullHobby with Spotify."""
    database()
    try:
        spotify_client().authorize()
    except SpotifyError as exc:
        fail(str(exc))
    console.print("[green]Spotify setup complete.[/green]")


@app.command()
def sync(
    playlist: str = typer.Argument(..., help="Spotify playlist URL, ID, or exact name."),
    limit: Optional[int] = typer.Option(None, help="Only sync the first N tracks."),
    refresh_youtube: bool = typer.Option(
        False, help="Search YouTube again even when a saved link exists."
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
    if youtube:
        for row in db.tracks_needing_youtube(playlist_id, refresh=refresh_youtube):
            try:
                match = youtube.find_best_match(
                    spotify_track_id=row["spotify_track_id"],
                    name=row["name"],
                    artists=row["artists"],
                )
            except YouTubeError as exc:
                fail(str(exc))

            if match:
                db.save_match(match)
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
    table.add_column("YouTube Link")
    table.add_column("Match")

    for row in rows:
        table.add_row(
            str(row["position"]),
            row["name"],
            row["artists"],
            row["youtube_url"] or "[yellow]missing[/yellow]",
            row["youtube_title"] or "",
        )

    console.print(table)


@app.command("download-mp3s")
def download_mp3s(
    playlist: str = typer.Argument(..., help="Playlist name or Spotify playlist ID."),
    output_root: Path = typer.Option(
        Path("songpull-hobby-mp3s"), help="Directory where playlist MP3 folders are written."
    ),
) -> None:
    """Download saved YouTube matches for a playlist as MP3 files."""
    yt_dlp = executable_path("yt-dlp")
    if not yt_dlp:
        fail("`yt-dlp` is required. Install it with `brew install yt-dlp`.")
    ffmpeg = ffmpeg_path()

    rows = database().playlist_rows_with_youtube(playlist)
    if not rows:
        fail("No saved YouTube links found for that playlist. Run `songpull-hobby sync` first.")

    playlist_name = str(rows[0]["playlist_name"])
    playlist_dir = output_root / safe_path_name(playlist_name)
    if playlist_dir.exists():
        shutil.rmtree(playlist_dir)
    playlist_dir.mkdir(parents=True, exist_ok=True)

    position_width = max(2, len(str(max(row["position"] for row in rows))))
    downloaded = 0
    failed = 0

    for row in rows:
        stem = safe_path_name(
            f"{row['position']:0{position_width}d} - {row['artists']} - {row['name']}"
        )
        output_template = str(playlist_dir / f"{stem}.%(ext)s")
        console.print(f"Downloading {row['position']}. {row['name']}...")
        result = subprocess.run(
            [
                yt_dlp,
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "--ffmpeg-location",
                ffmpeg,
                "--extractor-args",
                "youtube:player_client=android",
                "--no-playlist",
                "--output",
                output_template,
                row["youtube_url"],
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            downloaded += 1
        else:
            failed += 1
            console.print(f"[red]Failed:[/red] {row['name']}")
            if result.stderr:
                console.print(result.stderr.strip())

    console.print(
        f"[green]Downloaded {downloaded} MP3 files to {playlist_dir}.[/green]"
    )
    if failed:
        fail(f"{failed} download(s) failed.")


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
            ["playlist", "position", "song", "artists", "youtube_url", "match_title"]
        )
        for row in rows:
            writer.writerow(
                [
                    row["playlist_name"],
                    row["position"],
                    row["name"],
                    row["artists"],
                    row["youtube_url"] or "",
                    row["youtube_title"] or "",
                ]
            )

    console.print(f"[green]Exported {len(rows)} rows to {output}.[/green]")


if __name__ == "__main__":
    app()
