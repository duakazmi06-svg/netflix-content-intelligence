"""Tests for the Title schema. Each test checks one rule from the proposal."""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from src.models import Title


def valid_kwargs(**overrides):
    base = dict(
        id=101, title="Inception", media_type="movie",
        release_date=date(2010, 7, 16), release_year=2010,
        vote_average=8.8, vote_count=25000, popularity=85.5,
        original_language="en", genres=["Action", "Drama"],
        countries="US", runtime=148.0,
    )
    base.update(overrides)
    return base


def test_valid_record_is_accepted():
    assert Title(**valid_kwargs()).vote_average == 8.8


def test_missing_id_is_rejected():
    kwargs = valid_kwargs()
    del kwargs["id"]
    with pytest.raises(ValidationError):
        Title(**kwargs)


def test_empty_title_is_rejected():
    with pytest.raises(ValidationError):
        Title(**valid_kwargs(title=""))


def test_rating_above_10_is_rejected():
    with pytest.raises(ValidationError):
        Title(**valid_kwargs(vote_average=15))


def test_rating_of_8_5_is_accepted():
    assert Title(**valid_kwargs(vote_average=8.5)).vote_average == 8.5


def test_unrated_title_with_no_average_is_accepted():
    assert Title(**valid_kwargs(vote_average=None)).vote_average is None


def test_invalid_media_type_is_rejected():
    with pytest.raises(ValidationError):
        Title(**valid_kwargs(media_type="Movie"))  # must be lowercase "movie"


def test_missing_release_date_is_accepted_as_null():
    assert Title(**valid_kwargs(release_date=None, release_year=None)).release_date is None


def test_future_release_date_is_rejected():
    future = date.today() + timedelta(days=400)
    with pytest.raises(ValidationError):
        Title(**valid_kwargs(release_date=future))


def test_unknown_genre_is_rejected():
    with pytest.raises(ValidationError):
        Title(**valid_kwargs(genres=["Made Up Genre"]))


def test_missing_runtime_is_accepted_but_zero_runtime_is_not():
    assert Title(**valid_kwargs(runtime=None)).runtime is None
    with pytest.raises(ValidationError):
        Title(**valid_kwargs(runtime=0))
