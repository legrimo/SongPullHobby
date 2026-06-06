# SongPullHobby

SongPullHobby is a local CLI that syncs a Spotify playlist, searches for matching
YouTube videos, and stores the results in a SQLite database so repeated runs do
not create duplicate CSV files.

## What It Stores

SongPullHobby keeps its state in `.songpull-hobby/songpull-hobby.db` by default:

- Playlists synced from Spotify.
- Tracks in each playlist.
- Saved YouTube links for tracks that have already been matched.
- Sync run history.

The database is the source of truth. CSV export is available when you want a
spreadsheet file.

## Setup

SongPullHobby requires Python 3.10 or newer. On macOS, if `python3` reports that
Xcode command line tools are missing, install either the command line tools or
Python from python.org/Homebrew before continuing.

Create and activate a virtual environment:

```bash
cd SongPullHobby
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Create your environment file:

```bash
cp .env.example .env
```

Then fill in `.env`.

### Spotify Credentials

1. Go to the Spotify Developer Dashboard.
2. Create an app.
3. Add this redirect URI to the app:

```text
http://127.0.0.1:8888/callback
```

4. Copy the app's client ID and client secret into `.env`.

SongPullHobby uses these Spotify scopes:

```text
playlist-read-private playlist-read-collaborative
```

### YouTube Credentials

1. Create or open a Google Cloud project.
2. Enable the YouTube Data API v3.
3. Create an API key.
4. Add it to `.env` as `YOUTUBE_API_KEY`.

SongPullHobby uses the official YouTube Data API search endpoint. It caches saved
links in SQLite so rerunning a playlist does not repeatedly search YouTube for
tracks that already have links.

### MP3 Downloads

SongPullHobby shells out to `yt-dlp` and `ffmpeg` when downloading saved YouTube
links as MP3 files. Install them with Homebrew:

```bash
brew install yt-dlp ffmpeg
```

If Homebrew is not available, installing SongPullHobby also installs `yt-dlp` and an
`ffmpeg` fallback package in the virtual environment.

## Usage

Authorize Spotify once:

```bash
songpull-hobby setup
```

Sync a playlist:

```bash
songpull-hobby sync "https://open.spotify.com/playlist/PLAYLIST_ID"
```

List playlists visible to the authorized Spotify account:

```bash
songpull-hobby get-playlists
```

Show saved tracks and links:

```bash
songpull-hobby show
```

Export the saved table to CSV:

```bash
songpull-hobby export exports/playlist.csv
```

Test with only the first few tracks:

```bash
songpull-hobby sync "https://open.spotify.com/playlist/PLAYLIST_ID" --limit 10
```

Force YouTube links to be searched again:

```bash
songpull-hobby sync "https://open.spotify.com/playlist/PLAYLIST_ID" --refresh-youtube
```

Download saved YouTube links as MP3 files:

```bash
songpull-hobby download-mp3s "Wineshop"
```

This writes files to `songpull-hobby-mp3s/<playlist name>/`. If that playlist folder
already exists, SongPullHobby replaces it so the folder reflects the latest synced
tracks with saved YouTube links.

## Notes

- Spotify API access is free for this personal metadata use case.
- YouTube API search calls consume quota, so SongPullHobby avoids repeated searches
  by reusing saved links.
- The first matching version is intentionally simple and can be improved with
  duration comparison or manual match correction commands later.
