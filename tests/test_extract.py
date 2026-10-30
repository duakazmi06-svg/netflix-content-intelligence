"""Offline tests for extract.py (no real API calls)."""

import pandas as pd
import pytest

from src import extract as ex
from src.contract import CONTRACT_COLUMNS


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Serves canned TMDB responses: 2 movie pages, 1 tv page."""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        path = url.replace(ex.BASE_URL, "")
        if path == "/genre/movie/list":
            return FakeResponse({"genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}]})
        if path == "/genre/tv/list":
            return FakeResponse({"genres": [{"id": 18, "name": "Drama"}]})
        if path == "/discover/movie":
            page = params["page"]
            return FakeResponse({"total_pages": 2, "results": [{
                "id": 100 + page, "title": f"Movie {page}", "release_date": "2021-05-01",
                "vote_average": 7.5, "vote_count": 1200, "popularity": 55.2,
                "original_language": "en", "genre_ids": [18, 80], "overview": "x"}]})
        if path == "/discover/tv":
            return FakeResponse({"total_pages": 1, "results": [{
                "id": 101, "name": "Show A", "first_air_date": "", "vote_average": 8.0,
                "vote_count": 300, "popularity": 20.0, "original_language": "ko",
                "genre_ids": [18], "origin_country": ["KR"], "overview": ""}]})
        if path == "/movie/101":
            return FakeResponse({"runtime": 118, "production_countries": [{"iso_3166_1": "US"}]})
        if path == "/movie/102":
            return FakeResponse({"runtime": 0, "production_countries": []})
        if path == "/tv/101":
            return FakeResponse({"episode_run_time": [50, 60], "origin_country": ["KR"]})
        return FakeResponse({}, 404)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(ex, "MIN_SECONDS_BETWEEN_CALLS", 0)


def make_client():
    return ex.TMDBClient(api_key="test", session=FakeSession())


def test_tmdb_pagination_and_contract_shape():
    df, raw = ex.extract_tmdb("PK", max_pages=10, client=make_client())
    assert list(df.columns) == CONTRACT_COLUMNS
    assert len(df) == 3 and len(raw) == 3
    assert set(df["media_type"]) == {"movie", "tv"}
    movie = df[df["id"] == 101].query("media_type == 'movie'").iloc[0]
    assert movie["title"] == "Movie 1" and movie["genres"] == "Drama|Crime"
    assert movie["release_year"] == 2021


def test_same_id_allowed_for_movie_and_tv():
    df, _ = ex.extract_tmdb("US", max_pages=10, client=make_client())
    assert (df["id"] == 101).sum() == 2           # one movie, one show
    assert not df.duplicated(["id", "media_type"]).any()


def test_netflix_filter_and_region_sent():
    client = make_client()
    ex.extract_tmdb("PK", max_pages=1, client=client)
    discover = [p for u, p in client.session.calls if "/discover/" in u]
    assert all(p["with_watch_providers"] == 8 and p["watch_region"] == "PK" for p in discover)
    assert len(discover) == 2                      # max_pages=1 stops after page 1


def test_empty_tv_date_becomes_none():
    df, _ = ex.extract_tmdb("US", max_pages=10, client=make_client())
    show = df[df["media_type"] == "tv"].iloc[0]
    assert pd.isna(show["release_date"]) and pd.isna(show["release_year"])
    assert show["countries"] == "KR" and pd.isna(show["overview"])


def test_details_fill_runtime_and_countries():
    df, _ = ex.extract_tmdb("US", max_pages=10, with_details=True, client=make_client())
    m1 = df[(df["id"] == 101) & (df["media_type"] == "movie")].iloc[0]
    m2 = df[(df["id"] == 102)].iloc[0]
    tv = df[df["media_type"] == "tv"].iloc[0]
    assert m1["runtime"] == 118 and m1["countries"] == "US"
    assert pd.isna(m2["runtime"])                   # TMDB uses 0 for unknown
    assert tv["runtime"] == 55


def test_missing_credentials_raises():
    with pytest.raises(ex.ExtractError):
        ex.TMDBClient(api_key=None, read_token=None)


def test_bad_key_raises_clear_error():
    class Unauthorized(FakeSession):
        def get(self, *a, **k):
            return FakeResponse({"status_message": "Invalid API key"}, 401)
    client = ex.TMDBClient(api_key="bad", session=Unauthorized())
    with pytest.raises(ex.ExtractError, match="401"):
        client.get("/genre/movie/list")


def test_kaggle_fallback(tmp_path):
    csv = tmp_path / "netflix_titles.csv"
    pd.DataFrame({
        "show_id": ["s1", "s2"], "type": ["Movie", "TV Show"],
        "title": ["Dick Johnson Is Dead", "Blood & Water"], "director": [None, None],
        "cast": [None, None], "country": ["United States", "South Africa, Nigeria"],
        "date_added": ["September 25, 2021"] * 2, "release_year": [2020, 2021],
        "rating": ["PG-13", "TV-MA"], "duration": ["90 min", "2 Seasons"],
        "listed_in": ["Documentaries", "International TV Shows, TV Dramas"],
        "description": ["a", "b"],
    }).to_csv(csv, index=False)

    df, raw = ex.extract_kaggle(csv)
    assert list(df.columns) == CONTRACT_COLUMNS and len(raw) == 2
    assert df.loc[0, "id"] == 1 and df.loc[0, "media_type"] == "movie"
    assert df.loc[0, "runtime"] == 90 and pd.isna(df.loc[1, "runtime"])
    assert df.loc[1, "countries"] == "South Africa|Nigeria"
    assert df.loc[1, "genres"] == "International TV Shows|TV Dramas"


def test_save_outputs(tmp_path):
    df, raw = ex.extract_tmdb("US", max_pages=10, client=make_client())
    paths = ex.save_outputs(df, raw, "tmdb", "US", raw_dir=tmp_path)
    assert paths["snapshot"].exists() and paths["latest"].exists()
    assert len(pd.read_csv(paths["latest"])) == 3
