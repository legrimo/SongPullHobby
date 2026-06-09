from pathlib import Path

from songpull_hobby.config import load_settings


def clear_settings_env(monkeypatch):
    for name in [
        "SONGPULL_HOBBY_DATA_DIR",
        "SONGPULL_HOBBY_DB_PATH",
        "SONGPULL_HOBBY_SPOTIFY_TOKEN_PATH",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "YOUTUBE_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_load_settings_uses_project_defaults(monkeypatch, tmp_path):
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("SONGPULL_HOBBY_PROJECT_DIR", str(tmp_path))

    settings = load_settings()

    assert settings.data_dir == tmp_path / ".songpull-hobby"
    assert settings.db_path == tmp_path / ".songpull-hobby" / "songpull-hobby.db"
    assert settings.spotify_token_path == tmp_path / ".songpull-hobby" / "spotify_token.json"
    assert settings.spotify_redirect_uri == "http://127.0.0.1:8888/callback"


def test_load_settings_honors_explicit_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("SONGPULL_HOBBY_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("SONGPULL_HOBBY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SONGPULL_HOBBY_DB_PATH", str(tmp_path / "custom.db"))
    monkeypatch.setenv("SONGPULL_HOBBY_SPOTIFY_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost:9999/callback")
    monkeypatch.setenv("YOUTUBE_API_KEY", "youtube-key")

    settings = load_settings()

    assert settings.data_dir == Path(tmp_path / "data")
    assert settings.db_path == Path(tmp_path / "custom.db")
    assert settings.spotify_token_path == Path(tmp_path / "token.json")
    assert settings.spotify_client_id == "client-id"
    assert settings.spotify_client_secret == "client-secret"
    assert settings.spotify_redirect_uri == "http://localhost:9999/callback"
    assert settings.youtube_api_key == "youtube-key"
