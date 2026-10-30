"""Tests for the cleaning steps in src/transform.py, using tiny hand-made tables."""
import pandas as pd

from src.transform import (
    add_features, clean_text, handle_missing, parse_types, rating_tier,
    remove_exact_duplicates, resolve_duplicate_keys, runtime_bucket,
    validate_records,
)


def row(**overrides):
    base = {
        "id": 1, "media_type": "movie", "title": "Inception",
        "release_date": "2010-07-16", "release_year": 2010,
        "vote_average": "8.8", "vote_count": 100, "popularity": 50.0,
        "original_language": "en", "genres": "Action|Drama",
        "countries": "US", "runtime": 148, "content_rating": None,
        "overview": "x", "source": "tmdb", "extracted_at": "2026-10-30T00:00:00",
    }
    base.update(overrides)
    return base


def frame(*rows):
    return pd.DataFrame(list(rows))


def test_exact_duplicates_are_removed_ignoring_extracted_at():
    out, removed = remove_exact_duplicates(
        frame(row(), row(extracted_at="2026-10-31T00:00:00")))
    assert len(out) == 1 and removed == 1


def test_same_id_and_media_type_same_title_keeps_one_row():
    out, dropped = resolve_duplicate_keys(frame(row(vote_average="6.086"),
                                                row(vote_average="6.1")))
    assert len(out) == 1 and dropped == 1
    assert not out["duplicate_key_conflict"].any()


def test_same_id_different_media_type_is_NOT_a_duplicate():
    # Contract rule: a movie and a show can share a number. Both must be kept.
    df = frame(row(id=676, media_type="movie", title="Pearl Harbor"),
               row(id=676, media_type="tv", title="Tom and Jerry Tales"))
    out, dropped = resolve_duplicate_keys(df)
    assert len(out) == 2 and dropped == 0
    assert not out["duplicate_key_conflict"].any()


def test_same_key_different_titles_flags_every_copy():
    df = frame(row(id=5, media_type="movie", title="A"),
               row(id=5, media_type="movie", title="B"))
    out, dropped = resolve_duplicate_keys(df)
    assert len(out) == 2 and dropped == 0
    assert out["duplicate_key_conflict"].all()


def test_conflicting_key_is_rejected_by_validation():
    df = add_features(handle_missing(parse_types(clean_text(frame(
        row(id=5, media_type="movie", title="A"),
        row(id=5, media_type="movie", title="B"),
    )))))
    resolved, _ = resolve_duplicate_keys(df)
    valid, rejected = validate_records(resolved)
    assert len(valid) == 0 and len(rejected) == 2


def test_text_rating_becomes_number():
    out = parse_types(frame(row(vote_average="8.5")))
    assert out["vote_average"].iloc[0] == 8.5


def test_bad_date_becomes_missing_not_an_error():
    out = parse_types(frame(row(release_date="not a date")))
    assert pd.isna(out["release_date"].iloc[0])


def test_zero_votes_makes_average_missing():
    out = handle_missing(parse_types(frame(row(vote_average="0", vote_count=0))))
    assert pd.isna(out["vote_average"].iloc[0])


def test_missing_countries_become_unknown():
    out = handle_missing(parse_types(frame(row(countries=None))))
    assert out["countries"].iloc[0] == "Unknown"


def test_genres_split_into_list():
    out = handle_missing(parse_types(frame(row(genres="Action|Drama"))))
    assert out["genres"].iloc[0] == ["Action", "Drama"]


def test_missing_runtime_stays_missing_not_zero():
    out = handle_missing(parse_types(frame(row(runtime=None))))
    assert pd.isna(out["runtime"].iloc[0])


def test_rating_tier_bands():
    assert rating_tier(8.5) == "High"
    assert rating_tier(6.5) == "Medium"
    assert rating_tier(3.0) == "Low"
    assert rating_tier(float("nan")) == "Unrated"


def test_runtime_bucket_bands():
    assert runtime_bucket(45) == "Under 60 min"
    assert runtime_bucket(148) == "120-179 min"
    assert runtime_bucket(float("nan")) == "Unknown"


def test_validation_splits_good_and_bad_rows_with_reason():
    df = add_features(handle_missing(parse_types(clean_text(frame(
        row(id=1), row(id=2, title="Bad", vote_average="15")
    )))))
    valid, rejected = validate_records(df)
    assert len(valid) == 1 and len(rejected) == 1
    assert "vote_average" in rejected[0]["error_reason"]
    assert "source_payload" in rejected[0]
