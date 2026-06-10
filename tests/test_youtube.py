from songpull_hobby.youtube import (
    YouTubeClient,
    YouTubeCandidate,
    YouTubeQuotaExceededError,
    base_title,
    candidate_from_item,
    extract_video_id,
    normalize,
    parse_duration,
    parse_int,
    score_candidate,
    score_candidate_details,
    search_queries,
)


def test_candidate_from_item_keeps_reference_metadata():
    candidate = candidate_from_item(
        {
            "id": {"videoId": "abc123"},
            "snippet": {"title": "Track Title", "channelTitle": "Artist - Topic"},
        }
    )

    assert candidate.video_id == "abc123"
    assert candidate.url == "https://www.youtube.com/watch?v=abc123"
    assert candidate.title == "Track Title"
    assert candidate.channel == "Artist - Topic"


def test_score_candidate_prefers_song_artist_and_official_metadata():
    candidate = YouTubeCandidate(
        video_id="abc123",
        title="Artist Name - Song Title Official Audio",
        channel="Artist Name",
    )

    assert score_candidate(candidate, "Song Title", "Artist Name") == 1.0


def test_score_candidate_penalizes_common_bad_match_terms():
    official = YouTubeCandidate("abc123", "Artist Name - Song Title", "Artist Name")
    karaoke = YouTubeCandidate("def456", "Artist Name - Song Title Karaoke", "Fan")

    assert score_candidate(karaoke, "Song Title", "Artist Name") < score_candidate(
        official, "Song Title", "Artist Name"
    )


def test_search_queries_use_multiple_deduped_relevance_shapes():
    assert search_queries("Song Title", "Artist One, Artist Two") == [
        "Song Title Artist One, Artist Two official audio",
        "Song Title Artist One, Artist Two",
        "Artist One, Artist Two Song Title",
        "Song Title Artist One",
    ]


def test_base_title_removes_common_version_suffixes():
    assert base_title("Tribute To Malibu - Radio Edit") == "tribute to malibu"
    assert base_title("Stir Me Up - Ryan Murgatroyd Remix") == "stir me up ryan murgatroyd"


def test_search_uses_explicit_relevance_order(monkeypatch):
    captured = {}

    class Response:
        ok = True

        def json(self):
            return {"items": []}

    def fake_get(url, params, timeout):
        captured.update(params)
        return Response()

    client = YouTubeClient("key", delay_seconds=0)
    monkeypatch.setattr("songpull_hobby.youtube.requests.get", fake_get)

    assert client.search("query") == []
    assert captured["order"] == "relevance"
    assert captured["maxResults"] == 25


def test_search_candidates_dedupes_results_across_queries(monkeypatch):
    client = YouTubeClient("key", delay_seconds=0)
    calls = []

    def fake_search(query, max_results=25):
        calls.append((query, max_results))
        if len(calls) == 1:
            return [YouTubeCandidate("same-id", "First", "Channel")]
        return [YouTubeCandidate("same-id", "Duplicate", "Channel")]

    monkeypatch.setattr(client, "search", fake_search)

    candidates = client.search_candidates("Song Title", "Artist One")

    assert len(candidates) == 1
    assert candidates[0].title == "First"
    assert len(calls) == 3
    assert all(max_results == 25 for _, max_results in calls)


def test_search_candidates_can_limit_query_variants(monkeypatch):
    client = YouTubeClient("key", delay_seconds=0)
    calls = []

    def fake_search(query, max_results=25):
        calls.append((query, max_results))
        return [YouTubeCandidate(query, query, "Channel")]

    monkeypatch.setattr(client, "search", fake_search)

    candidates = client.search_candidates(
        "Song Title", "Artist One", max_query_variants=1
    )

    assert len(candidates) == 1
    assert calls == [("Song Title Artist One official audio", 25)]


def test_search_raises_quota_error_for_resource_exhausted_response(monkeypatch):
    class Response:
        ok = False
        status_code = 429
        text = """
        {
          "error": {
            "status": "RESOURCE_EXHAUSTED",
            "errors": [{"reason": "rateLimitExceeded"}]
          }
        }
        """

        def json(self):
            raise ValueError("no json")

    monkeypatch.setattr(
        "songpull_hobby.youtube.requests.get", lambda url, params, timeout: Response()
    )
    client = YouTubeClient("key", delay_seconds=0)

    try:
        client.search("query")
    except YouTubeQuotaExceededError as exc:
        assert "quota exceeded" in str(exc).lower()
    else:
        raise AssertionError("expected quota error")


def test_score_candidate_rewards_duration_and_popularity():
    candidate = YouTubeCandidate(
        video_id="abc123",
        title="Artist Name - Song Title Official Audio",
        channel="Artist Name",
        duration_seconds=225,
        view_count=150_000,
    )

    scored = score_candidate_details(
        candidate, "Song Title", "Artist Name", duration_ms=225_000
    )

    assert scored.score == 1.2
    assert "duration close" in scored.reasons
    assert "popular result" in scored.reasons


def test_score_candidate_rewards_base_title_and_all_artists_despite_duration_mismatch():
    candidate = YouTubeCandidate(
        video_id="abc123",
        title="Aline Umber & Maxime dB - Tribute to Malibu [AF003]",
        channel="trommel",
        duration_seconds=300,
        view_count=150_000,
    )

    scored = score_candidate_details(
        candidate,
        "Tribute To Malibu - Radio Edit",
        "Aline Umber, Maxime dB",
        duration_ms=198_000,
    )

    assert scored.score == 0.65
    assert "base song title match" in scored.reasons
    assert "all artists in title" in scored.reasons
    assert "duration mismatch" in scored.reasons


def test_score_candidate_heavily_penalizes_short_video_for_full_length_track():
    candidate = YouTubeCandidate(
        video_id="abc123",
        title="Artist Name - Song Title Official Audio",
        channel="Artist Name",
        duration_seconds=60,
        view_count=150_000,
    )

    scored = score_candidate_details(
        candidate, "Song Title", "Artist Name", duration_ms=225_000
    )

    assert "short video" in scored.reasons
    assert scored.score < 0.6


def test_parse_duration_handles_youtube_iso_duration_values():
    assert parse_duration("PT3M45S") == 225
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration(None) is None
    assert parse_duration("not-a-duration") is None


def test_parse_int_returns_none_for_invalid_values():
    assert parse_int("123") == 123
    assert parse_int(None) is None
    assert parse_int("many") is None


def test_extract_video_id_accepts_common_youtube_url_shapes():
    assert extract_video_id("https://www.youtube.com/watch?v=abc123_DEF0") == "abc123_DEF0"
    assert extract_video_id("https://youtu.be/abc123_DEF0") == "abc123_DEF0"
    assert extract_video_id("https://www.youtube.com/shorts/abc123_DEF0") == "abc123_DEF0"


def test_find_best_match_uses_detailed_candidate_scores(monkeypatch):
    client = YouTubeClient("key", delay_seconds=0)
    monkeypatch.setattr(
        client,
        "search_candidates",
        lambda name, artists, **kwargs: [
            YouTubeCandidate(
                video_id="abc123_DEF0",
                title="Artist Name - Song Title Official Audio",
                channel="Artist Name",
                duration_seconds=225,
                view_count=150_000,
            )
        ],
    )

    match = client.find_best_match("track-1", "Song Title", "Artist Name", 225_000)

    assert match is not None
    assert match.youtube_video_id == "abc123_DEF0"
    assert match.confidence == 1.2


def test_find_best_match_uses_fallback_variants_after_weak_first_query(monkeypatch):
    client = YouTubeClient("key", delay_seconds=0)
    calls = []

    def fake_search(query, max_results=25):
        calls.append(query)
        if query == "Artist Name Song Title":
            return [
                YouTubeCandidate(
                    "strong",
                    "Artist Name - Song Title Official Audio",
                    "Artist Name",
                    duration_seconds=225,
                    view_count=150_000,
                )
            ]
        return [YouTubeCandidate("weak", "Unrelated", "Channel")]

    monkeypatch.setattr(client, "search", fake_search)

    match = client.find_best_match(
        "track-1",
        "Song Title",
        "Artist Name",
        225_000,
        max_query_variants=1,
        fallback_query_variants=3,
    )

    assert match is not None
    assert match.youtube_video_id == "strong"
    assert calls == [
        "Song Title Artist Name official audio",
        "Song Title Artist Name",
        "Artist Name Song Title",
    ]


def test_find_best_match_scores_candidates_from_all_query_variants(monkeypatch):
    client = YouTubeClient("key", delay_seconds=0)
    monkeypatch.setattr(
        client,
        "search",
        lambda query, max_results=25: [
            YouTubeCandidate("weak", "Unrelated", "Channel"),
            YouTubeCandidate(
                "strong",
                "Artist Name - Song Title Official Audio",
                "Artist Name",
                duration_seconds=225,
                view_count=150_000,
            ),
        ]
        if query == "Artist Name Song Title"
        else [YouTubeCandidate("weak", "Unrelated", "Channel")],
    )

    match = client.find_best_match("track-1", "Song Title", "Artist Name", 225_000)

    assert match is not None
    assert match.youtube_video_id == "strong"
    assert match.confidence == 1.2


def test_normalize_removes_case_and_punctuation_noise():
    assert normalize("  Song.Title (Official Audio)! ") == "song title official audio"
