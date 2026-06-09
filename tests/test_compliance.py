from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = [
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / "setup.py",
    PROJECT_ROOT / "README.md",
    *sorted((PROJECT_ROOT / "songpull_hobby").glob("*.py")),
]
FORBIDDEN_PUBLIC_TOKENS = {
    "yt-dlp",
    "ffmpeg",
    "imageio-ffmpeg",
    "download-mp3s",
    "download-track",
    "track_downloads",
    "songpull-mp3s",
}


def test_public_package_does_not_include_media_download_surface():
    violations = {}
    for path in PUBLIC_FILES:
        text = path.read_text(encoding="utf-8").lower()
        matches = sorted(token for token in FORBIDDEN_PUBLIC_TOKENS if token in text)
        if matches:
            violations[path.relative_to(PROJECT_ROOT).as_posix()] = matches

    assert violations == {}
