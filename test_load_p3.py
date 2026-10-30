"""Person 3 test: running the load twice must give the same row counts."""
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import load  # noqa: E402


def sample():
    return pd.DataFrame({
        "tmdb_id": [1, 1, 2],
        "media_type": ["movie", "tv", "movie"],   # id 1 exists as movie AND tv
        "title": ["A", "A show", "B"],
        "release_year": [2020, 2021, 2019],
        "genres": [["Drama", "Comedy"], ["Drama"], "Action|Drama"],
        "countries": [["US"], ["US", "UK"], "PK"],
        "regions": ["US", "US", "PK"],
        "source": "test",
    })


def counts(engine):
    with engine.connect() as c:
        return {t: c.execute(text(f"select count(*) from {t}")).scalar()
                for t in ["titles", "genres", "title_genres", "countries",
                          "title_availability"]}


def test_load_twice_same_counts(tmp_path):
    engine = load.get_engine(tmp_path / "test.db")
    load.create_tables(engine)
    load.load_titles(engine, sample())
    first = counts(engine)
    load.load_titles(engine, sample())
    assert counts(engine) == first
    assert first["titles"] == 3          # movie:1 and tv:1 are different titles


def test_update_changes_row(tmp_path):
    engine = load.get_engine(tmp_path / "test.db")
    load.create_tables(engine)
    load.load_titles(engine, sample())
    df = sample()
    df.loc[0, "title"] = "A (new name)"
    load.load_titles(engine, df)
    with engine.connect() as c:
        name = c.execute(text("select title from titles where title_id='movie:1'")).scalar()
    assert name == "A (new name)"
    assert counts(engine)["titles"] == 3
