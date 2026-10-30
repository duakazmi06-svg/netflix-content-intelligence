"""
Stage 1: Extract.

Pulls Netflix titles from the TMDB API (watch provider 8) for a chosen region,
saves the raw responses as a timestamped JSON snapshot, and returns a pandas
DataFrame in the shared contract shape (see contract.py).

If no TMDB credentials are set, or the API fails, it falls back to the Kaggle
"Netflix Movies and TV Shows" CSV in data/raw/netflix_titles.csv.

Usage:
    python -m src.extract                      # auto: TMDB if key set, else Kaggle
    python -m src.extract --source tmdb --region PK --max-pages 20
    python -m src.extract --source kaggle
    python -m src.extract --details            # also fetch runtime + countries (slower)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.contract import CONTRACT_COLUMNS, LATEST_EXTRACT_PATH, MULTI_SEP

log = logging.getLogger("extract")

BASE_URL = "https://api.themoviedb.org/3"
NETFLIX_PROVIDER_ID = 8
TMDB_MAX_PAGES = 500           # TMDB never serves pages beyond 500
MIN_SECONDS_BETWEEN_CALLS = 0.05  # ~20 requests/sec, well under TMDB's limit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
KAGGLE_PATH = RAW_DIR / "netflix_titles.csv"


class ExtractError(RuntimeError):
    """Raised when the API cannot be used and the caller should fall back."""


# --------------------------------------------------------------------------- #
# TMDB client
# --------------------------------------------------------------------------- #
class TMDBClient:
    """Small TMDB wrapper with retries, back-off and request throttling."""

    def __init__(self, api_key: str | None = None, read_token: str | None = None,
                 session: requests.Session | None = None):
        if not api_key and not read_token:
            raise ExtractError("No TMDB_API_KEY or TMDB_READ_TOKEN found in .env")
        self.api_key = api_key
        self.session = session or self._build_session()
        if read_token:  # v4 bearer token is preferred when available
            self.session.headers["Authorization"] = f"Bearer {read_token}"
        self.session.headers["Accept"] = "application/json"
        self._last_call = 0.0
        self.calls = 0

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=5,
            backoff_factor=1.0,             # waits 1s, 2s, 4s, 8s, ...
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        s = requests.Session()
        s.mount("https://", HTTPAdapter(max_retries=retry))
        return s

    def get(self, path: str, **params) -> dict:
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        if self.api_key and "Authorization" not in self.session.headers:
            params["api_key"] = self.api_key

        try:
            resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=20)
        except requests.RequestException as e:
            raise ExtractError(f"Network error calling {path}: {e}") from e
        finally:
            self._last_call = time.monotonic()
            self.calls += 1

        if resp.status_code == 401:
            raise ExtractError("TMDB rejected the credentials (401). Check your .env key.")
        if resp.status_code == 404:
            return {}
        if not resp.ok:
            raise ExtractError(f"TMDB {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # --- endpoints -------------------------------------------------------- #
    def genre_map(self, media_type: str) -> dict[int, str]:
        data = self.get(f"/genre/{media_type}/list", language="en-US")
        return {g["id"]: g["name"] for g in data.get("genres", [])}

    def discover(self, media_type: str, region: str, max_pages: int) -> list[dict]:
        """All Netflix titles of one media type in a region, page by page."""
        results: list[dict] = []
        page, total_pages = 1, 1
        limit = min(max_pages, TMDB_MAX_PAGES)
        while page <= min(total_pages, limit):
            data = self.get(
                f"/discover/{media_type}",
                with_watch_providers=NETFLIX_PROVIDER_ID,
                watch_region=region,
                sort_by="popularity.desc",
                include_adult="false",
                language="en-US",
                page=page,
            )
            total_pages = data.get("total_pages", 0)
            for item in data.get("results", []):
                item["media_type"] = media_type
                results.append(item)
            log.info("%s page %d/%d (%d titles so far)",
                     media_type, page, min(total_pages, limit), len(results))
            page += 1
        return results

    def details(self, media_type: str, tmdb_id: int) -> dict:
        return self.get(f"/{media_type}/{tmdb_id}", language="en-US")


# --------------------------------------------------------------------------- #
# TMDB -> contract
# --------------------------------------------------------------------------- #
def _year(date_str: str | None) -> int | None:
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


def tmdb_to_row(item: dict, genres: dict[int, str], extracted_at: str,
                detail: dict | None = None) -> dict:
    is_movie = item["media_type"] == "movie"
    date = (item.get("release_date") if is_movie else item.get("first_air_date")) or None
    row = {
        "id": item.get("id"),
        "media_type": item["media_type"],
        "title": item.get("title") if is_movie else item.get("name"),
        "release_date": date,
        "release_year": _year(date),
        "vote_average": item.get("vote_average"),
        "vote_count": item.get("vote_count"),
        "popularity": item.get("popularity"),
        "original_language": item.get("original_language") or None,
        "genres": MULTI_SEP.join(genres.get(g, f"Unknown({g})")
                                 for g in item.get("genre_ids", [])) or None,
        "countries": MULTI_SEP.join(item.get("origin_country", [])) or None,
        "runtime": None,
        "content_rating": None,
        "overview": item.get("overview") or None,
        "source": "tmdb",
        "extracted_at": extracted_at,
        "date_added": None,  # TMDB does not record when Netflix added a title
    }
    if detail:
        if is_movie:
            row["runtime"] = detail.get("runtime") or None
            countries = [c["iso_3166_1"] for c in detail.get("production_countries", [])]
        else:
            ep = detail.get("episode_run_time") or []
            row["runtime"] = int(sum(ep) / len(ep)) if ep else None
            countries = detail.get("origin_country", [])
        if countries:
            row["countries"] = MULTI_SEP.join(countries)
    return row


def extract_tmdb(region: str = "US", max_pages: int = 25, with_details: bool = False,
                 client: TMDBClient | None = None) -> tuple[pd.DataFrame, list[dict]]:
    load_dotenv(PROJECT_ROOT / ".env")
    client = client or TMDBClient(os.getenv("TMDB_API_KEY"), os.getenv("TMDB_READ_TOKEN"))
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    raw: list[dict] = []
    rows: list[dict] = []
    for media_type in ("movie", "tv"):
        genres = client.genre_map(media_type)
        items = client.discover(media_type, region, max_pages)
        for i, item in enumerate(items, 1):
            detail = client.details(media_type, item["id"]) if with_details else None
            if with_details and i % 50 == 0:
                log.info("details %s: %d/%d", media_type, i, len(items))
            raw.append({"item": item, "detail": detail})
            rows.append(tmdb_to_row(item, genres, extracted_at, detail))

    if not rows:
        raise ExtractError(f"TMDB returned no Netflix titles for region {region}")
    log.info("TMDB done: %d titles, %d API calls", len(rows), client.calls)
    return finalize(pd.DataFrame(rows, columns=CONTRACT_COLUMNS)), raw


# --------------------------------------------------------------------------- #
# Kaggle fallback -> contract
# --------------------------------------------------------------------------- #
def _kaggle_runtime(duration, media_type: str) -> int | None:
    """'90 min' -> 90 for movies. TV rows give seasons, not minutes, so None."""
    if media_type != "movie" or not isinstance(duration, str):
        return None
    m = re.match(r"\s*(\d+)\s*min", duration)
    return int(m.group(1)) if m else None


def _split_join(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return MULTI_SEP.join(p.strip() for p in value.split(",") if p.strip())


def extract_kaggle(path: Path = KAGGLE_PATH) -> tuple[pd.DataFrame, list[dict]]:
    if not Path(path).exists():
        raise ExtractError(
            f"Kaggle fallback file not found at {path}. Download 'Netflix Movies and "
            "TV Shows' from Kaggle and save it as data/raw/netflix_titles.csv"
        )
    src = pd.read_csv(path)
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    media = src["type"].map({"Movie": "movie", "TV Show": "tv"})

    df = pd.DataFrame({
        "id": pd.to_numeric(src["show_id"].astype(str).str.extract(r"(\d+)")[0],
                            errors="coerce").astype("Int64"),
        "media_type": media,
        "title": src["title"],
        "release_date": None,  # Kaggle only gives the year
        "release_year": pd.to_numeric(src["release_year"], errors="coerce").astype("Int64"),
        "vote_average": None,
        "vote_count": None,
        "popularity": None,
        "original_language": None,
        "genres": src["listed_in"].map(_split_join),
        "countries": src["country"].map(_split_join),
        "runtime": [_kaggle_runtime(d, m) for d, m in zip(src["duration"], media)],
        "content_rating": src["rating"].where(src["rating"].notna(), None),
        "overview": src["description"],
        "source": "kaggle",
        "extracted_at": extracted_at,
        # "September 25, 2021" (some rows have a leading space) -> "2021-09-25"
        "date_added": pd.to_datetime(src["date_added"].astype("string").str.strip(),
                                     format="%B %d, %Y", errors="coerce")
                        .dt.strftime("%Y-%m-%d"),
    }, columns=CONTRACT_COLUMNS)
    log.info("Kaggle done: %d titles from %s", len(df), path)
    return finalize(df), src.to_dict(orient="records")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
INT_COLS = ["id", "release_year", "vote_count", "runtime"]
FLOAT_COLS = ["vote_average", "popularity"]


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Consistent dtypes for the next stage: nullable ints, floats, strings.
    Missing values are pandas NA/NaN, so test them with pd.isna()."""
    df = df[CONTRACT_COLUMNS].copy()
    for c in INT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    for c in FLOAT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df
def save_outputs(df: pd.DataFrame, raw: list[dict], source: str, region: str,
                 raw_dir: Path = RAW_DIR) -> dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = f"{source}_{region}_{stamp}" if source == "tmdb" else f"{source}_{stamp}"

    snapshot = raw_dir / f"snapshot_{tag}.json"
    snapshot.write_text(json.dumps(raw, default=str, ensure_ascii=False), encoding="utf-8")

    csv_path = raw_dir / f"extracted_{tag}.csv"
    df.to_csv(csv_path, index=False)
    latest = PROJECT_ROOT / LATEST_EXTRACT_PATH if raw_dir == RAW_DIR else raw_dir / "extracted_latest.csv"
    df.to_csv(latest, index=False)
    return {"snapshot": snapshot, "csv": csv_path, "latest": latest}


def extract(source: str = "auto", region: str = "US", max_pages: int = 25,
            with_details: bool = False, save: bool = True) -> pd.DataFrame:
    """Main entry point for run_pipeline.py. Returns a contract-shaped DataFrame."""
    used = source
    if source in ("auto", "tmdb"):
        try:
            df, raw = extract_tmdb(region, max_pages, with_details)
            used = "tmdb"
        except ExtractError as e:
            if source == "tmdb":
                raise
            log.warning("TMDB unavailable (%s). Falling back to Kaggle CSV.", e)
            df, raw = extract_kaggle()
            used = "kaggle"
    elif source == "kaggle":
        df, raw = extract_kaggle()
    else:
        raise ValueError("source must be 'auto', 'tmdb' or 'kaggle'")

    if save:
        paths = save_outputs(df, raw, used, region)
        log.info("Saved snapshot %s and %s", paths["snapshot"].name, paths["latest"])
    return df


def main() -> None:
    p = argparse.ArgumentParser(description="Extract Netflix titles (TMDB or Kaggle).")
    p.add_argument("--source", choices=["auto", "tmdb", "kaggle"], default="auto")
    p.add_argument("--region", default=os.getenv("TMDB_REGION", "US"),
                   help="ISO 3166-1 country code, e.g. US or PK")
    p.add_argument("--max-pages", type=int, default=25, help="pages per media type (20 titles each)")
    p.add_argument("--details", action="store_true", help="fetch runtime + countries per title")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        df = extract(args.source, args.region.upper(), args.max_pages, args.details)
    except ExtractError as e:
        raise SystemExit(f"Extract failed: {e}")
    print(df["media_type"].value_counts().to_string())
    print(f"\n{len(df)} titles extracted -> {LATEST_EXTRACT_PATH}")


if __name__ == "__main__":
    main()
