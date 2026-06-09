from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from songpull_hobby.db import Match, Source


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_SEARCH_MAX_RESULTS = 25
VERSION_TITLE_TERMS = {
    "radio edit",
    "extended mix",
    "club mix",
    "original mix",
    "original",
    "edit",
    "remix",
}
TITLE_STOP_WORDS = {"a", "an", "and", "the", "to", "of", "feat", "ft"}
NEGATIVE_TITLE_TERMS = {
    "cover",
    "instrumental",
    "karaoke",
    "live",
    "reaction",
    "remix",
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
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class CandidateScore:
    score: float
    reasons: List[str]


class YouTubeClient:
    def __init__(self, api_key: str, delay_seconds: float = 0.15) -> None:
        self.api_key = api_key
        self.delay_seconds = delay_seconds

    def find_best_match(
        self,
        spotify_track_id: str,
        name: str,
        artists: str,
        duration_ms: Optional[int] = None,
        min_confidence: float = 0.35,
    ) -> Optional[Match]:
        candidates = self.search_candidates(name, artists)
        if not candidates:
            return None

        scored = [
            (score_candidate_details(candidate, name, artists, duration_ms), candidate)
            for candidate in candidates
        ]
        scored.sort(key=lambda item: item[0].score, reverse=True)
        candidate_score, candidate = scored[0]
        if candidate_score.score < min_confidence:
            return None

        return Match(
            spotify_track_id=spotify_track_id,
            youtube_url=candidate.url,
            youtube_video_id=candidate.video_id,
            title=candidate.title,
            channel=candidate.channel,
            confidence=candidate_score.score,
        )

    def source_from_url(self, link: str) -> Source:
        video_id = extract_video_id(link)
        candidates = self._with_video_details(
            [YouTubeCandidate(video_id=video_id, title="", channel=None)]
        )
        if not candidates or not candidates[0].title:
            raise YouTubeError("YouTube video metadata was not found for that link.")
        candidate = candidates[0]
        return Source(
            playlist_id="",
            spotify_track_id="",
            provider="youtube",
            source_url=candidate.url,
            source_id=candidate.video_id,
            source_title=candidate.title,
            source_author=candidate.channel,
            confidence=1.0,
            selection_method="manual",
        )

    def search_candidates(
        self, name: str, artists: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    ) -> List[YouTubeCandidate]:
        candidates_by_id: Dict[str, YouTubeCandidate] = {}
        for query in search_queries(name, artists):
            for candidate in self.search(query, max_results=max_results):
                candidates_by_id.setdefault(candidate.video_id, candidate)
        return list(candidates_by_id.values())

    def search(
        self, query: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    ) -> List[YouTubeCandidate]:
        response = requests.get(
            YOUTUBE_SEARCH_URL,
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "relevance",
                "maxResults": max_results,
                "key": self.api_key,
            },
            timeout=30,
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if not response.ok:
            raise YouTubeError(f"YouTube search failed: {response.text}")

        candidates = [
            candidate_from_item(item) for item in response.json().get("items", [])
        ]
        return self._with_video_details(candidates)

    def _with_video_details(
        self, candidates: List[YouTubeCandidate]
    ) -> List[YouTubeCandidate]:
        if not candidates:
            return candidates

        response = requests.get(
            YOUTUBE_VIDEOS_URL,
            params={
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(candidate.video_id for candidate in candidates),
                "key": self.api_key,
            },
            timeout=30,
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if not response.ok:
            raise YouTubeError(f"YouTube video details failed: {response.text}")

        details = {
            item["id"]: item
            for item in response.json().get("items", [])
            if item.get("id")
        }
        enriched: List[YouTubeCandidate] = []
        for candidate in candidates:
            detail = details.get(candidate.video_id, {})
            snippet = detail.get("snippet") or {}
            statistics = detail.get("statistics") or {}
            enriched.append(
                YouTubeCandidate(
                    video_id=candidate.video_id,
                    title=snippet.get("title") or candidate.title,
                    channel=snippet.get("channelTitle") or candidate.channel,
                    duration_seconds=parse_duration(
                        (detail.get("contentDetails") or {}).get("duration")
                    ),
                    view_count=parse_int(statistics.get("viewCount")),
                )
            )
        return enriched


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


def base_title(value: str) -> str:
    title = normalize(value)
    for term in sorted(VERSION_TITLE_TERMS, key=len, reverse=True):
        title = re.sub(rf"\b{re.escape(term)}\b", " ", title)
    return " ".join(title.split())


def important_title_tokens(value: str) -> List[str]:
    version_words = {
        word for term in VERSION_TITLE_TERMS for word in term.split()
    }
    return [
        token
        for token in base_title(value).split()
        if len(token) > 2 and token not in TITLE_STOP_WORDS and token not in version_words
    ]


def title_token_overlap(song: str, title: str) -> float:
    song_tokens = important_title_tokens(song)
    if not song_tokens:
        return 0.0
    title_tokens = set(important_title_tokens(title))
    matches = sum(1 for token in song_tokens if token in title_tokens)
    return matches / len(song_tokens)


def search_queries(name: str, artists: str) -> List[str]:
    song = name.strip()
    artist_text = artists.strip()
    first_artist = artist_text.split(",", 1)[0].strip()
    variants = [
        f"{song} {artist_text} official audio",
        f"{song} {artist_text}",
        f"{artist_text} {song}",
    ]
    if first_artist and first_artist != artist_text:
        variants.append(f"{song} {first_artist}")

    deduped: List[str] = []
    seen = set()
    for query in variants:
        normalized = normalize(query)
        if normalized and normalized not in seen:
            deduped.append(query)
            seen.add(normalized)
    return deduped


def parse_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_duration(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?"
        r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value,
    )
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def extract_video_id(link: str) -> str:
    parsed = urllib.parse.urlparse(link.strip())
    hostname = (parsed.hostname or "").lower()
    if hostname in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif hostname.endswith("youtube.com"):
        if parsed.path == "/watch":
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
            video_id = parsed.path.strip("/").split("/")[1]
        else:
            video_id = ""
    else:
        video_id = ""

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise YouTubeError("Expected a YouTube video URL.")
    return video_id


def score_candidate(
    candidate: YouTubeCandidate,
    name: str,
    artists: str,
    duration_ms: Optional[int] = None,
) -> float:
    return score_candidate_details(candidate, name, artists, duration_ms).score


def score_candidate_details(
    candidate: YouTubeCandidate,
    name: str,
    artists: str,
    duration_ms: Optional[int] = None,
) -> CandidateScore:
    score = 0.0
    reasons: List[str] = []
    title = normalize(candidate.title)
    channel = normalize(candidate.channel or "")
    song = normalize(name)
    song_base = base_title(name)
    artist_names = [normalize(artist) for artist in artists.split(",") if artist.strip()]
    artists_in_title = [artist for artist in artist_names if artist and artist in title]
    artists_in_channel = [
        artist for artist in artist_names if artist and artist in channel
    ]

    if song and song in title:
        score += 0.45
        reasons.append("song title match")
    elif song_base and song_base in title:
        score += 0.35
        reasons.append("base song title match")
    elif artists_in_title and title_token_overlap(name, candidate.title) >= 0.75:
        score += 0.2
        reasons.append("song title token overlap")

    if artists_in_title:
        if len(artist_names) > 1 and len(artists_in_title) == len(artist_names):
            score += 0.35
            reasons.append("all artists in title")
        else:
            score += 0.25
            reasons.append("artist in title")

    if artists_in_channel:
        score += 0.15
        reasons.append("artist in channel")

    if "official" in title or "official" in channel:
        score += 0.15
        reasons.append("official signal")

    negative_terms = [term for term in NEGATIVE_TITLE_TERMS if term in title]
    expected_terms = {term for term in NEGATIVE_TITLE_TERMS if term in song}
    unexpected_negative_terms = [
        term for term in negative_terms if term not in expected_terms
    ]
    if unexpected_negative_terms:
        score -= 0.35
        reasons.append(f"negative terms: {', '.join(unexpected_negative_terms)}")

    if duration_ms and candidate.duration_seconds:
        spotify_seconds = duration_ms / 1000
        duration_delta = abs(candidate.duration_seconds - spotify_seconds)
        if candidate.duration_seconds < 120 and spotify_seconds >= 180:
            score -= 0.55
            reasons.append("short video")
        elif duration_delta <= 5:
            score += 0.15
            reasons.append("duration close")
        elif duration_delta <= 15:
            score += 0.05
            reasons.append("duration approximate")
        elif duration_delta >= 45:
            score -= 0.1
            reasons.append("duration mismatch")

    if candidate.view_count and candidate.view_count >= 100_000:
        score += 0.05
        reasons.append("popular result")

    return CandidateScore(score=max(score, 0.0), reasons=reasons)
