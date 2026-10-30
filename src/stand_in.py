"""
stand_in.py  (Person 3, TEMPORARY)

Only for testing before Person 1 and Person 2 finish.
It fakes the three steps (extract, transform, validate) using the Kaggle CSV
at data/raw/netflix_titles.csv.

At integration day, run the pipeline WITHOUT --stand-in and delete this file.
"""
import re
from pathlib import Path

import pandas as pd

KAGGLE_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "netflix_titles.csv"


def extract(source="kaggle"):
    return pd.read_csv(KAGGLE_CSV)


def transform(raw):
    df = pd.DataFrame()
    df["tmdb_id"] = pd.to_numeric(raw["show_id"].astype(str).str.extract(r"(\d+)")[0],
                                  errors="coerce")
    df["title"] = raw["title"]
    df["media_type"] = raw["type"].map({"Movie": "movie", "TV Show": "tv"})
    df["release_year"] = raw["release_year"]
    df["date_added"] = pd.to_datetime(raw["date_added"].astype(str).str.strip(),
                                      errors="coerce")
    df["maturity_rating"] = raw["rating"]
    mins = raw["duration"].astype(str).str.extract(r"(\d+) min")[0]
    df["runtime"] = pd.to_numeric(mins, errors="coerce")
    df["genres"] = raw["listed_in"]
    df["countries"] = raw["country"]
    df["source"] = "kaggle"
    return df.drop_duplicates(subset=["tmdb_id", "media_type"])


def validate(df):
    reasons = pd.Series("", index=df.index)
    reasons[df["title"].isna() | (df["title"].astype(str).str.strip() == "")] = "title is empty"
    reasons[~df["media_type"].isin(["movie", "tv"]) & (reasons == "")] = "media_type must be movie or tv"
    reasons[df["tmdb_id"].isna() & (reasons == "")] = "id is missing"
    bad = reasons != ""
    rejected = pd.DataFrame({
        "source_payload": df[bad].apply(lambda r: r.to_json(date_format="iso"), axis=1),
        "error_reason": reasons[bad]})
    return df[~bad].copy(), rejected.reset_index(drop=True)
