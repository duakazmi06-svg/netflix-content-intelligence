"""
load.py  (Person 3)

What it does:
    Takes the clean, validated data and writes it into the SQLite database
    (netflix_analysis.db) using SQLAlchemy.

    It is safe to run again and again. Running it twice gives the same
    database, not double rows (this is called "idempotent").

Tables (7):
    titles, genres, title_genres, countries, title_availability,
    rejected_records, etl_runs
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import (Column, Date, DateTime, Float, ForeignKey, Index,
                        Integer, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, delete, select)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# The database file sits in the main project folder.
DB_PATH = Path(__file__).resolve().parent.parent / "netflix_analysis.db"

metadata = MetaData()

# ---------------------------------------------------------------- tables
titles = Table(
    "titles", metadata,
    Column("title_id", String, primary_key=True),      # example: "movie:550"
    Column("tmdb_id", Integer, nullable=False),
    Column("media_type", String, nullable=False),      # "movie" or "tv"
    Column("title", String, nullable=False),
    Column("release_date", Date),
    Column("release_year", Integer),
    Column("runtime", Integer),
    Column("maturity_rating", String),
    Column("language", String),
    Column("vote_average", Float),
    Column("vote_count", Integer),
    Column("popularity", Float),
    Column("date_added", Date),                        # only Kaggle has this
    Column("source", String),                          # "tmdb" or "kaggle"
    UniqueConstraint("tmdb_id", "media_type", name="uq_title_id_type"),
    Index("ix_titles_media_type", "media_type"),
    Index("ix_titles_release_year", "release_year"),
    Index("ix_titles_language", "language"),
)

genres = Table(
    "genres", metadata,
    Column("genre_id", Integer, primary_key=True, autoincrement=True),
    Column("genre_name", String, nullable=False, unique=True),
)

title_genres = Table(
    "title_genres", metadata,
    Column("title_id", String, ForeignKey("titles.title_id"), primary_key=True),
    Column("genre_id", Integer, ForeignKey("genres.genre_id"), primary_key=True),
)

countries = Table(
    "countries", metadata,
    Column("title_id", String, ForeignKey("titles.title_id"), primary_key=True),
    Column("country", String, primary_key=True),
)

title_availability = Table(
    "title_availability", metadata,
    Column("title_id", String, ForeignKey("titles.title_id"), primary_key=True),
    Column("region", String, primary_key=True),
)

rejected_records = Table(
    "rejected_records", metadata,
    Column("record_id", Integer, primary_key=True, autoincrement=True),
    Column("source_payload", Text),
    Column("error_reason", Text),
    Column("run_id", String),
)

etl_runs = Table(
    "etl_runs", metadata,
    Column("run_id", String, primary_key=True),
    Column("timestamp", DateTime),
    Column("rows_extracted", Integer),
    Column("rows_loaded", Integer),
    Column("rows_rejected", Integer),
)

TITLE_COLUMNS = ["title_id", "tmdb_id", "media_type", "title", "release_date",
                 "release_year", "runtime", "maturity_rating", "language",
                 "vote_average", "vote_count", "popularity", "date_added",
                 "source"]


# --------------------------------------------------------------- helpers
def get_engine(db_path=DB_PATH):
    """Open (or create) the database file."""
    return create_engine(f"sqlite:///{db_path}")


def create_tables(engine):
    """Make the tables if they do not exist yet. Safe to call every run."""
    metadata.create_all(engine)


def new_run_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _to_int(x):
    return None if x is None or pd.isna(x) else int(x)


def _to_float(x):
    return None if x is None or pd.isna(x) else float(x)


def _as_list(x):
    """Turn a cell into a list. Accepts a list, or text like 'A|B' or 'A, B'."""
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        items = list(x)
    elif isinstance(x, float) and pd.isna(x):
        return []
    else:
        text = str(x)
        items = text.split("|") if "|" in text else text.split(",")
    return [str(i).strip() for i in items if str(i).strip()]


def _chunks(items, size=400):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def prepare(df):
    """
    Get the DataFrame ready for the database.

    The input must have these columns (names agreed with Person 2):
        tmdb_id (or id), title, media_type
    These are optional (filled with empty if missing):
        release_date, release_year, runtime, maturity_rating,
        language (or original_language), vote_average, vote_count,
        popularity, date_added, source,
        genres, countries, regions (or region)
    """
    df = df.copy()
    df = df.rename(columns={"id": "tmdb_id", "original_language": "language",
                            "content_rating": "maturity_rating",
                            "region": "regions"})
    for needed in ["tmdb_id", "title", "media_type"]:
        if needed not in df.columns:
            raise ValueError(f"load.py: the DataFrame has no '{needed}' column")

    for col in ["release_date", "release_year", "runtime", "maturity_rating",
                "language", "vote_average", "vote_count", "popularity",
                "date_added", "source", "genres", "countries", "regions"]:
        if col not in df.columns:
            df[col] = None

    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce")
    # If release_year is empty, take it from release_date.
    year_from_date = df["release_date"].dt.year
    df["release_year"] = pd.to_numeric(df["release_year"], errors="coerce")
    df["release_year"] = df["release_year"].fillna(year_from_date)

    df["media_type"] = df["media_type"].astype(str).str.strip().str.lower()
    df["tmdb_id"] = pd.to_numeric(df["tmdb_id"], errors="coerce")
    df = df.dropna(subset=["tmdb_id", "title"])
    df["tmdb_id"] = df["tmdb_id"].astype(int)
    df["title_id"] = df["media_type"] + ":" + df["tmdb_id"].astype(str)

    # Same title twice in one batch? Keep the last one.
    df = df.drop_duplicates(subset="title_id", keep="last").reset_index(drop=True)
    return df


# ----------------------------------------------------------------- loading
def load_titles(engine, df):
    """Write titles and their genres, countries and regions. Returns row count."""
    df = prepare(df)
    if df.empty:
        return 0

    rows = []
    for r in df.itertuples(index=False):
        rows.append({
            "title_id": r.title_id,
            "tmdb_id": int(r.tmdb_id),
            "media_type": r.media_type,
            "title": str(r.title),
            "release_date": None if pd.isna(r.release_date) else r.release_date.date(),
            "release_year": _to_int(r.release_year),
            "runtime": _to_int(r.runtime),
            "maturity_rating": None if pd.isna(r.maturity_rating) else str(r.maturity_rating),
            "language": None if pd.isna(r.language) else str(r.language),
            "vote_average": _to_float(r.vote_average),
            "vote_count": _to_int(r.vote_count),
            "popularity": _to_float(r.popularity),
            "date_added": None if pd.isna(r.date_added) else r.date_added.date(),
            "source": None if pd.isna(r.source) else str(r.source),
        })

    with engine.begin() as conn:
        # 1) titles: insert new ones, update old ones (upsert)
        for chunk in _chunks(rows):
            stmt = sqlite_insert(titles).values(chunk)
            update_cols = {c: stmt.excluded[c] for c in TITLE_COLUMNS if c != "title_id"}
            conn.execute(stmt.on_conflict_do_update(index_elements=["title_id"],
                                                    set_=update_cols))

        # 2) genres list
        all_genres = sorted({g for v in df["genres"] for g in _as_list(v)})
        for chunk in _chunks([{"genre_name": g} for g in all_genres]):
            conn.execute(sqlite_insert(genres).values(chunk).on_conflict_do_nothing())
        genre_ids = {name: gid for gid, name in
                     conn.execute(select(genres.c.genre_id, genres.c.genre_name))}

        # 3) wipe old genre/country links of these titles, then write fresh ones
        ids = list(df["title_id"])
        for chunk in _chunks(ids):
            conn.execute(delete(title_genres).where(title_genres.c.title_id.in_(chunk)))
            conn.execute(delete(countries).where(countries.c.title_id.in_(chunk)))

        genre_rows, country_rows, region_rows = [], [], []
        for r in df.itertuples(index=False):
            for g in set(_as_list(r.genres)):
                genre_rows.append({"title_id": r.title_id, "genre_id": genre_ids[g]})
            for c in set(_as_list(r.countries)):
                country_rows.append({"title_id": r.title_id, "country": c})
            for reg in set(_as_list(r.regions)):
                region_rows.append({"title_id": r.title_id, "region": reg})

        for chunk in _chunks(genre_rows):
            conn.execute(sqlite_insert(title_genres).values(chunk).on_conflict_do_nothing())
        for chunk in _chunks(country_rows):
            conn.execute(sqlite_insert(countries).values(chunk).on_conflict_do_nothing())
        # Regions are only added, never wiped, so a US run and a PK run both stay.
        for chunk in _chunks(region_rows):
            conn.execute(sqlite_insert(title_availability).values(chunk).on_conflict_do_nothing())

    return len(rows)


def load_rejected(engine, rejected_df, run_id):
    """
    Save the rejected rows. Accepts columns
    source_payload (or payload) and error_reason (or reason).
    """
    if rejected_df is None or len(rejected_df) == 0:
        return 0
    rejected_df = rejected_df.rename(columns={"payload": "source_payload",
                                              "reason": "error_reason"})
    rows = []
    for r in rejected_df.to_dict("records"):
        payload = r.get("source_payload")
        if not isinstance(payload, str):
            payload = json.dumps(payload, default=str)
        rows.append({"source_payload": payload,
                     "error_reason": str(r.get("error_reason")),
                     "run_id": run_id})
    with engine.begin() as conn:
        for chunk in _chunks(rows):
            conn.execute(rejected_records.insert(), chunk)
    return len(rows)


def log_run(engine, run_id, rows_extracted, rows_loaded, rows_rejected):
    """Write one row in etl_runs (the audit log)."""
    with engine.begin() as conn:
        conn.execute(etl_runs.insert().values(
            run_id=run_id, timestamp=datetime.now(),
            rows_extracted=int(rows_extracted),
            rows_loaded=int(rows_loaded),
            rows_rejected=int(rows_rejected)))
