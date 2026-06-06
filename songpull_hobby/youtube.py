from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from songpull_hobby.db import Match


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
NEGATIVE_TITLE_TERMS = {
    "cover",
    "karaoke",
    "reaction",
    "sped up",
    "slowed",
    "nightcore",
    "tutorial",
}


class YouTubeError(RuntimeError):
    pass


@dataclass(frozen=True)
class YouTubeCandidate:
    video_id: str
    title: str
    channel: Optional[str]

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


class YouTubeClient:
    def __init__(self, api_key: str, delay_seconds: float = 0.15) -> None:
        self.api_key = api_key
        self.delay_seconds = delay_seconds

    def find_best_match(
        self, spotify_track_id: str, name: str, artists: str
    ) -> Optional[Match]:
        query = f"{name} {artists} official audio"
        candidates = self.search(query)
        if not candidates:
            return None

        scored = [
            (score_candidate(candidate, name, artists), candidate)
            for candidate in candidates
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        score, candidate = scored[0]

        return Match(
            spotify_track_id=spotify_track_id,
            youtube_url=candidate.url,
            youtube_video_id=candidate.video_id,
            title=candidate.title,
            channel=candidate.channel,
            confidence=score,
        )

    def search(self, query: str, max_results: int = 5) -> List[YouTubeCandidate]:
        response = requests.get(
            YOUTUBE_SEARCH_URL,
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
                "key": self.api_key,
            },
            timeout=30,
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if not response.ok:
            raise YouTubeError(f"YouTube search failed: {response.text}")

        return [candidate_from_item(item) for item in response.json().get("items", [])]


def candidate_from_item(item: Dict[str, Any]) -> YouTubeCandidate:
    snippet = item.get("snippet", {})
    return YouTubeCandidate(
        video_id=item["id"]["videoId"],
        title=snippet.get("title", ""),
        channel=snippet.get("channelTitle"),
    )


def normalize(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(normalized.split())


def score_candidate(candidate: YouTubeCandidate, name: str, artists: str) -> float:
    score = 0.0
    title = normalize(candidate.title)
    channel = normalize(candidate.channel or "")
    song = normalize(name)
    artist_names = [normalize(artist) for artist in artists.split(",") if artist.strip()]

    if song and song in title:
        score += 0.45

    if any(artist and artist in title for artist in artist_names):
        score += 0.25

    if any(artist and artist in channel for artist in artist_names):
        score += 0.15

    if "official" in title or "official" in channel:
        score += 0.15

    if any(term in title for term in NEGATIVE_TITLE_TERMS):
        score -= 0.35

    return max(score, 0.0)
