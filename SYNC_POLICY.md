# SongPullHobby Sync Policy

SongPullHobby is the public-facing, terms-conscious version of SongPull. Sync
agents may port functionality from SongPull only when it preserves the
SongPullHobby boundary: metadata in, reviewable reference links out, and no
audio or video copying.

## Allowed To Port

- Spotify playlist metadata syncing, playlist lookup, and display improvements.
- YouTube Data API search metadata, candidate scoring, and cached reference
  link behavior.
- SQLite schema changes for playlists, tracks, source/reference metadata, sync
  history, and CSV/JSON export of metadata.
- CLI, README, troubleshooting, and test improvements that describe metadata
  review workflows.
- Refactors that reduce duplication without introducing media download behavior.

## Blocked From SongPullHobby

- Downloading, copying, extracting, transcoding, or storing Spotify or YouTube
  audio/video content.
- Dependencies or commands for media extraction, including `yt-dlp`, `ffmpeg`,
  and `imageio-ffmpeg`.
- MP3 bookkeeping, media output directories, or commands such as
  `download-mp3s`, `download-track`, and `missing-mp3s`.
- Local secrets, OAuth tokens, SQLite state, generated exports, virtual
  environments, build artifacts, or downloaded media files.
- Documentation that encourages using SongPullHobby to store provider audio or
  video content.

When unsure, the sync agent should stop and report that the change needs human
review instead of opening a SongPullHobby PR.
