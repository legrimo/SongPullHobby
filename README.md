# SongPullHobby

SongPullHobby is a local command line app for turning a Spotify playlist into a
small reviewable library: Spotify track metadata in, candidate YouTube reference
links out, with a CSV export when you want a spreadsheet.

You interact with it entirely through the `songpull-hobby` CLI:

1. Authorize the CLI with your Spotify account.
2. List playlists visible to that account.
3. Sync one playlist into a local SQLite cache.
4. Show or export the saved track table.

SongPullHobby does not download, copy, or store Spotify or YouTube audio/video
content. It is intended for personal metadata review and CSV export only.

## Quickstart

SongPullHobby requires Python 3.9 or newer. On macOS, if `python3` reports that
Xcode command line tools are missing, install either the command line tools,
[Python](https://www.python.org/downloads/), or Python through
[Homebrew](https://brew.sh/) before continuing.

```bash
# Clone the repo, then install the CLI locally in an isolated environment.
cd SongPullHobby
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Create your local secrets file, then fill in the values described below.
cp .env.example .env
```

For development, install and run the test suite with:

```bash
pip install -e ".[test]"
python -m pytest
```

After `.env` is filled in, authorize Spotify and try the CLI:

```bash
# Opens Spotify in your browser once and saves a local refresh token.
songpull-hobby setup

# Shows playlists visible to the authorized Spotify account.
songpull-hobby get-playlists --limit 5

# Syncs the first 10 tracks from an example playlist and searches YouTube links.
songpull-hobby sync "https://open.spotify.com/playlist/3zO9BEXAMPLE1234567890" --limit 10

# Rerun automatic YouTube matching for one saved track when you want to spend
# extra quota only on that item.
songpull-hobby match-track "My top tracks playlist" 12 --youtube-query-variants 4

# Shows the saved local table for that playlist.
songpull-hobby show "https://open.spotify.com/playlist/3zO9BEXAMPLE1234567890"

# Manually replace one saved reference link after reviewing a track.
songpull-hobby set-source "My top tracks playlist" 12 "https://www.youtube.com/watch?v=VIDEO_ID"

# Exports the saved table when you want to review it in a spreadsheet.
songpull-hobby export exports/my-top-tracks.csv
```

You can pass a Spotify playlist URL, a playlist ID, or an exact visible playlist
name to `sync` and `show`.

## Spotify Setup

SongPullHobby uses Spotify OAuth so it can read playlists visible to your own
Spotify account.

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app.
3. In the app settings, add this redirect URI:

```text
http://127.0.0.1:8888/callback
```

4. Copy the app's client ID and client secret into `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

SongPullHobby requests these Spotify scopes:

```text
playlist-read-private playlist-read-collaborative
```

Useful Spotify references:

- [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) is where
  you create the app and copy credentials.
- [Spotify Authorization Guide](https://developer.spotify.com/documentation/web-api/concepts/authorization)
  explains the browser-based OAuth flow.
- [Spotify Scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes)
  documents what `playlist-read-private` and `playlist-read-collaborative` allow.

## YouTube Setup

YouTube matching is optional, but recommended. If `YOUTUBE_API_KEY` is missing,
`sync` still saves Spotify playlist tracks and skips YouTube search.

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a Google Cloud project.
3. Enable the [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).
4. Create an API key and add it to `.env`:

```dotenv
YOUTUBE_API_KEY=your_youtube_api_key
```

Useful Google/YouTube references:

- [YouTube Data API v3 Overview](https://developers.google.com/youtube/v3) explains
  the API SongPullHobby calls.
- [Search: list](https://developers.google.com/youtube/v3/docs/search/list) is the
  endpoint used to find candidate reference videos.
- [API key best practices](https://cloud.google.com/docs/authentication/api-keys)
  explains how to restrict and rotate your key.

## What The CLI Shows

`get-playlists` confirms which Spotify account is authorized and prints a Rich
table of visible playlists:

```text
Authorized Spotify user: Leo Mont
                    Available Spotify Playlists
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Name                  ┃ Owner    ┃ Public ┃ Tracks ┃ ID                     ┃ URL                          ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ My top tracks playlist│ Leo Mont │ True   │ 50     │ 3zO9BEXAMPLE1234567890 │ https://open.spotify.com/... │
│ 2 │ Nov 2025 playlist     │ Leo Mont │ True   │ 42     │ 5Fr2FEXAMPLE1234567890 │ https://open.spotify.com/... │
└───┴───────────────────────┴──────────┴────────┴────────┴────────────────────────┴──────────────────────────────┘
```

`sync` fetches playlist tracks, stores them locally, and fills in missing
YouTube reference links when a key is configured:

```bash
# Sync an example Spotify playlist into the local library.
songpull-hobby sync "My top tracks playlist" --limit 10
```

```text
Synced 10 tracks from My top tracks playlist. Added 10 YouTube links.
```

Sync starts with one YouTube search query per track to conserve the daily
YouTube Data API quota. If that first query has no confident match, SongPullHobby
can automatically spend a few extra query variants as a fallback. Set
`--youtube-query-variants 1` for strict quota mode, or raise the value when you
want broader matching recall:

```bash
songpull-hobby sync "My top tracks playlist" --youtube-query-variants 4
```

`show` prints the saved local library table:

```bash
# Review the synced tracks and saved candidate YouTube reference links.
songpull-hobby show "My top tracks playlist"
```

```text
                              SongPullHobby Library
┏━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Song               ┃ Artist            ┃ Link                                 ┃ Source Title              ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ Midnight City      │ M83               │ https://www.youtube.com/watch?v=...  │ M83 - Midnight City        │
│ 2 │ Sweet Disposition  │ The Temper Trap   │ https://www.youtube.com/watch?v=...  │ Sweet Disposition - Audio  │
│ 3 │ Electric Feel      │ MGMT              │ missing                              │                            │
└───┴────────────────────┴───────────────────┴──────────────────────────────────────┴────────────────────────────┘
```

## Command Reference

```bash
# One-time Spotify browser authorization.
songpull-hobby setup

# List playlists visible to the authorized Spotify account.
songpull-hobby get-playlists --limit 5

# Sync tracks and fill missing YouTube links.
songpull-hobby sync "https://open.spotify.com/playlist/PLAYLIST_ID"

# Test with only the first few tracks.
songpull-hobby sync "https://open.spotify.com/playlist/PLAYLIST_ID" --limit 10

# Force YouTube links to be searched again for saved tracks.
songpull-hobby sync "https://open.spotify.com/playlist/PLAYLIST_ID" --refresh-youtube

# Automatically search YouTube again for one saved playlist track.
songpull-hobby match-track "My top tracks playlist" 12 --youtube-query-variants 4

# Show saved tracks and links.
songpull-hobby show "https://open.spotify.com/playlist/PLAYLIST_ID"

# Manually replace the saved YouTube reference link for one track.
songpull-hobby set-source "My top tracks playlist" 12 "https://www.youtube.com/watch?v=VIDEO_ID"

# Retrieve the saved link, match title, and score for one track.
songpull-hobby get-link "My top tracks playlist" 12

# Export the saved table to CSV.
songpull-hobby export exports/playlist.csv

# Export manually selected reference matches for analysis.
songpull-hobby export-manual-matches exports/manual-matches.jsonl

# Print safe Spotify auth diagnostics for troubleshooting.
songpull-hobby debug-spotify "https://open.spotify.com/playlist/PLAYLIST_ID"
```

## What It Stores Locally

SongPullHobby stores local state under `.songpull-hobby/` by default:

- `.songpull-hobby/songpull-hobby.db` stores synced playlists, tracks, saved
  source reference metadata, manual selection markers, and sync run history.
- `.songpull-hobby/spotify_token.json` stores the Spotify OAuth token generated
  by `songpull-hobby setup`.

The SQLite database is a local cache. Refresh or delete stored API data as needed
to stay aligned with the [Spotify Developer Terms](https://developer.spotify.com/terms/)
and [YouTube API Services Terms](https://developers.google.com/youtube/terms/api-services-terms-of-service).

## Troubleshooting

- `Missing Spotify credentials.`: run
  `cp .env.example .env`, fill in your Spotify app credentials, and retry.
- Redirect URI mismatch: make sure the Spotify app contains exactly
  `http://127.0.0.1:8888/callback` and that `.env` uses the same value.
- Browser authorization succeeded but sync fails: run `songpull-hobby debug-spotify`
  to confirm the saved token, authorized user, and visible playlists.
- `YOUTUBE_API_KEY is not set`: Spotify sync still works, but YouTube matching is
  skipped until you add a YouTube Data API key to `.env`.
- YouTube quota or API errors: check that the YouTube Data API v3 is enabled for
  the Google Cloud project attached to your API key. If quota is exhausted,
  SongPullHobby stops matching early and keeps the Spotify playlist metadata
  synced.

## Compliance Notes

- Spotify API access is free for this personal metadata use case.
- YouTube API search calls consume quota, so SongPullHobby avoids repeated
  searches by reusing saved reference links. `sync` starts with one search query
  and only spends extra variants as a fallback for weak or missing matches.
- Do not use SongPullHobby to download, copy, or store Spotify or YouTube audio
  or video content.
- Review and follow the [Spotify Developer Terms](https://developer.spotify.com/terms/),
  [Spotify Developer Policy](https://developer.spotify.com/policy/),
  [YouTube API Services Terms](https://developers.google.com/youtube/terms/api-services-terms-of-service),
  [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies),
  and [Google API key best practices](https://cloud.google.com/docs/authentication/api-keys).
- Restrict your Google API key to the YouTube Data API and to the narrowest
  application context practical for your usage.
- Matching considers title, artist, official metadata signals, duration, and
  popularity metadata returned by the YouTube Data API.
- Manual source corrections are validated through the YouTube Data API and store
  only reference metadata.
