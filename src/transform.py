"""Person 2: clean the raw extract and validate every row.

Pipeline inside this file:
  load_raw -> remove_exact_duplicates -> resolve_duplicate_keys
  -> clean_text -> parse_types -> handle_missing -> add_features
  -> validate_records -> write outputs

Input : data/raw/extracted_latest.csv   (written by extract.py, never edited here)
Output: data/processed/titles_clean.csv, rejected_records.csv, data_quality_summary.csv

A title is identified by (id, media_type), as src/contract.py requires.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from pydantic import ValidationError

from src.contract import CONTRACT_COLUMNS, LATEST_EXTRACT_PATH
from src.models import Title

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# Primary key from contract.py: TMDB movie and TV ids overlap, so both are needed.
KEY = ["id", "media_type"]

# Fields checked by the Title model.
MODEL_FIELDS = list(Title.model_fields.keys())

# Columns added by this stage, on top of the contract columns.
DERIVED_COLUMNS = ["decade", "is_recent", "rating_tier", "runtime_bucket"]

OUTPUT_COLUMNS = CONTRACT_COLUMNS + DERIVED_COLUMNS

# Columns of rejected_records.csv. Always written, even when there are zero rejections.
REJECTION_COLUMNS = ["id", "media_type", "title", "error_reason", "source_payload"]


# ---------------------------------------------------------------- input
def load_raw(path: str | Path) -> pd.DataFrame:
    """Read the raw CSV exactly as extract.py saved it. No changes yet."""
    return pd.read_csv(path)


# ---------------------------------------------------------------- duplicates
def remove_exact_duplicates(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Drop rows identical in every column except extracted_at."""
    content_cols = [c for c in df.columns if c != "extracted_at"]
    cleaned = df.drop_duplicates(subset=content_cols, keep="first")
    return cleaned, len(df) - len(cleaned)


def resolve_duplicate_keys(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Handle (id, media_type) pairs that still appear more than once.

    1. Same key, same title, only numbers differ (e.g. vote_average 6.086 vs 6.1):
       it is one title, so keep the first row and count the rest.
    2. Same key, different titles: the extract is wrong and we can't tell which
       row is right. Flag every copy so validate_records() rejects them.

    Returns the frame and the number of same-title copies dropped.
    """
    df = df.copy()
    per_key = df.groupby(KEY)["title"].nunique()
    conflicting = set(per_key[per_key > 1].index)
    key_tuples = list(zip(df["id"], df["media_type"]))
    df["duplicate_key_conflict"] = [k in conflicting for k in key_tuples]

    same_title = df[~df["duplicate_key_conflict"]]
    kept = same_title.drop_duplicates(subset=KEY, keep="first")
    dropped = len(same_title) - len(kept)

    df = pd.concat([df[df["duplicate_key_conflict"]], kept]).sort_index()
    return df, dropped


# ---------------------------------------------------------------- cleaning
def clean_text(df: pd.DataFrame) -> pd.DataFrame:
    """Remove stray spaces and standardise text."""
    df = df.copy()
    # astype(str) first: an all-empty column loads as float NaN, and .str fails on floats.
    df["title"] = df["title"].fillna("").astype(str).str.strip()
    df["overview"] = df["overview"].fillna("").astype(str).str.strip()
    lang = df["original_language"].fillna("").astype(str).str.strip().str.lower()
    df["original_language"] = lang.replace("", None)   # empty -> missing, not ""
    df["genres"] = df["genres"].fillna("").astype(str)
    df["countries"] = df["countries"].fillna("").astype(str)
    return df


def parse_types(df: pd.DataFrame) -> pd.DataFrame:
    """Turn text into real dates and numbers. Bad values become NaN/NaT, not errors."""
    df = df.copy()
    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce").dt.date
    for col in ["release_year", "vote_average", "vote_count", "popularity", "runtime"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def handle_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Missing-value policy. Each rule is deliberate.

    - countries: missing -> "Unknown" (keeps the title; we don't invent a country)
    - runtime: stays missing (we never fill with 0; 0 minutes is a different fact)
    - vote_average: if nobody has voted (vote_count == 0), the average is not real,
      so it becomes missing. This stops unrated titles distorting averages.
    - genres: "Drama|Action" -> ["Drama", "Action"]; missing -> []
    """
    df = df.copy()
    df["countries"] = df["countries"].fillna("").replace("", "Unknown")
    df.loc[df["vote_count"] == 0, "vote_average"] = float("nan")
    df["genres"] = df["genres"].apply(
        lambda s: [g.strip() for g in s.split("|") if g.strip()] if s else []
    )
    return df


# ---------------------------------------------------------------- features
def rating_tier(vote_average: float) -> str:
    """Our own bands for analysis. They are not official Netflix categories."""
    if pd.isna(vote_average):
        return "Unrated"
    if vote_average >= 8:
        return "High"
    if vote_average >= 6:
        return "Medium"
    return "Low"


def runtime_bucket(minutes: float) -> str:
    if pd.isna(minutes):
        return "Unknown"
    if minutes < 60:
        return "Under 60 min"
    if minutes < 120:
        return "60-119 min"
    if minutes < 180:
        return "120-179 min"
    return "180+ min"


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["decade"] = df["release_year"] // 10 * 10
    df["is_recent"] = df["release_year"] >= 2015   # our cut-off; state it in the report
    df["rating_tier"] = df["vote_average"].apply(rating_tier)
    df["runtime_bucket"] = df["runtime"].apply(runtime_bucket)
    return df


# ---------------------------------------------------------------- validation
def validate_records(df: pd.DataFrame) -> Tuple[List[dict], List[dict]]:
    """Check every row against the Title model.

    Returns (valid_rows, rejected_rows). Nothing is silently dropped: each
    rejected row keeps its original payload and the exact reason.
    """
    # Convert pandas NaN/NaT to None so Pydantic treats them as missing.
    records = df.astype(object).where(df.notna(), None).to_dict(orient="records")

    valid, rejected = [], []
    for record in records:
        if record.get("duplicate_key_conflict"):
            rejected.append(_rejection(record, [
                "duplicate (id, media_type): same key used for different titles in the source"
            ]))
            continue

        payload = {field: record.get(field) for field in MODEL_FIELDS}
        try:
            Title(**payload)
            valid.append(record)
        except ValidationError as err:
            reasons = [
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                for e in err.errors()
            ]
            rejected.append(_rejection(record, reasons))
    return valid, rejected


def _rejection(record: Dict, reasons: List[str]) -> dict:
    return {
        "id": record.get("id"),
        "media_type": record.get("media_type"),
        "title": record.get("title"),
        "error_reason": " | ".join(reasons),
        "source_payload": json.dumps(record, default=str),
    }


# ---------------------------------------------------------------- quality summary (Q1)
def build_quality_summary(raw: pd.DataFrame, exact_dupes: int, same_key_dupes: int,
                          valid: List[dict], rejected: List[dict]) -> pd.DataFrame:
    rows = [
        {"metric": "rows extracted", "value": len(raw)},
        {"metric": "exact duplicate rows removed", "value": exact_dupes},
        {"metric": "same (id, media_type) same-title duplicates removed", "value": same_key_dupes},
        {"metric": "rows passed validation", "value": len(valid)},
        {"metric": "rows rejected", "value": len(rejected)},
    ]
    for col, pct in (raw.isna().mean() * 100).round(1).items():
        rows.append({"metric": f"missing % in {col}", "value": pct})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main entry point
def transform(raw_path: str | Path = PROJECT_ROOT / LATEST_EXTRACT_PATH,
              processed_dir: str | Path = PROCESSED_DIR) -> dict:
    """Run the whole Person 2 pipeline and write the three output files."""
    raw = load_raw(raw_path)

    deduped, exact_dupes = remove_exact_duplicates(raw)
    df, same_key_dupes = resolve_duplicate_keys(deduped)
    df = clean_text(df)
    df = parse_types(df)
    df = handle_missing(df)
    df = add_features(df)

    valid, rejected = validate_records(df)

    clean = pd.DataFrame(valid)
    clean["genres"] = clean["genres"].apply(lambda g: "|".join(g))
    clean = clean[OUTPUT_COLUMNS]

    processed_dir = Path(processed_dir)
    os.makedirs(processed_dir, exist_ok=True)
    clean.to_csv(processed_dir / "titles_clean.csv", index=False)
    pd.DataFrame(rejected, columns=REJECTION_COLUMNS).to_csv(
        processed_dir / "rejected_records.csv", index=False)
    build_quality_summary(raw, exact_dupes, same_key_dupes, valid, rejected).to_csv(
        processed_dir / "data_quality_summary.csv", index=False)

    return {"extracted": len(raw), "exact_duplicates_removed": exact_dupes,
            "same_key_duplicates_removed": same_key_dupes,
            "valid": len(valid), "rejected": len(rejected)}


if __name__ == "__main__":
    print(transform())
