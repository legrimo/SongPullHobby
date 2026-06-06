from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    spotify_client_id: Optional[str]
    spotify_client_secret: Optional[str]
    spotify_redirect_uri: str
    youtube_api_key: Optional[str]
    data_dir: Path
    db_path: Path
    spotify_token_path: Path


def load_settings() -> Settings:
    project_dir = Path(os.getenv("SONGPULL_HOBBY_PROJECT_DIR", Path.cwd())).expanduser()
    default_data_dir = project_dir / ".songpull-hobby"

    load_dotenv(project_dir / ".env")

    data_dir = Path(os.getenv("SONGPULL_HOBBY_DATA_DIR", default_data_dir)).expanduser()
    db_path = Path(
        os.getenv("SONGPULL_HOBBY_DB_PATH", data_dir / "songpull-hobby.db")
    ).expanduser()
    token_path = Path(
        os.getenv("SONGPULL_HOBBY_SPOTIFY_TOKEN_PATH", data_dir / "spotify_token.json")
    ).expanduser()

    return Settings(
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        spotify_redirect_uri=os.getenv(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
        ),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
        data_dir=data_dir,
        db_path=db_path,
        spotify_token_path=token_path,
    )


def ensure_data_dir(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
