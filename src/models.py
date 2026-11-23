"""Pydantic schema for one cleaned Netflix title.

Every row must pass Title(**row) before it is allowed into titles_clean.csv.
Rows that fail are written to rejected_records.csv together with the reason.
"""
from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Genre names as they appear in TMDB (movies and TV combined).
KNOWN_GENRES = {
    "Action", "Action & Adventure", "Adventure", "Animation", "Comedy", "Crime",
    "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Kids",
    "Music", "Mystery", "News", "Reality", "Romance", "Science Fiction",
    "Sci-Fi & Fantasy", "Soap", "Talk", "Thriller", "TV Movie", "War",
    "War & Politics", "Western",
}

# Kaggle's "listed_in" categories mapped to the TMDB genre names above, so both
# sources share one genre vocabulary. Categories that describe origin or format
# rather than a genre (e.g. "International Movies", "TV Shows") map to [] and
# are dropped; every other genre in the title is kept.
KAGGLE_GENRE_MAP = {
    "Dramas": ["Drama"], "TV Dramas": ["Drama"],
    "Comedies": ["Comedy"], "TV Comedies": ["Comedy"], "Stand-Up Comedy": ["Comedy"],
    "Stand-Up Comedy & Talk Shows": ["Comedy", "Talk"],
    "Documentaries": ["Documentary"], "Docuseries": ["Documentary"],
    "Science & Nature TV": ["Documentary"],
    "Action & Adventure": ["Action & Adventure"], "TV Action & Adventure": ["Action & Adventure"],
    "Children & Family Movies": ["Family"], "Kids' TV": ["Kids"],
    "Romantic Movies": ["Romance"], "Romantic TV Shows": ["Romance"],
    "Thrillers": ["Thriller"], "TV Thrillers": ["Thriller"],
    "Crime TV Shows": ["Crime"], "TV Mysteries": ["Mystery"],
    "Horror Movies": ["Horror"], "TV Horror": ["Horror"],
    "Music & Musicals": ["Music"], "Reality TV": ["Reality"],
    "Sci-Fi & Fantasy": ["Sci-Fi & Fantasy"], "TV Sci-Fi & Fantasy": ["Sci-Fi & Fantasy"],
    "Anime Series": ["Animation"], "Anime Features": ["Animation"],
    # origin / format labels, not genres
    "International Movies": [], "International TV Shows": [], "Independent Movies": [],
    "British TV Shows": [], "Spanish-Language TV Shows": [], "Korean TV Shows": [],
    "Classic Movies": [], "Cult Movies": [], "Classic & Cult TV": [], "LGBTQ Movies": [],
    "Teen TV Shows": [], "Sports Movies": [], "Faith & Spirituality": [],
    "Movies": [], "TV Shows": [],
}


def map_kaggle_genres(genres: List[str]) -> List[str]:
    """Translate Kaggle categories to TMDB genres (unknown names are kept, so the
    validator still flags them). Duplicates are removed, order is preserved."""
    out: List[str] = []
    for g in genres:
        for mapped in KAGGLE_GENRE_MAP.get(g, [g]):
            if mapped not in out:
                out.append(mapped)
    return out


class Title(BaseModel):
    """One title. Field(...) rules are the checks; a failing check becomes a rejection reason."""

    id: int = Field(gt=0)
    title: str = Field(min_length=1)
    media_type: Literal["movie", "tv"]
    release_date: Optional[date] = None           # null is allowed (proposal policy)
    release_year: Optional[int] = Field(default=None, ge=1880, le=2100)
    vote_average: Optional[float] = Field(default=None, ge=0, le=10)  # None = unrated
    vote_count: Optional[int] = Field(default=None, ge=0)   # optional (Kaggle has none)
    popularity: Optional[float] = Field(default=None, ge=0)  # optional (Kaggle has none)
    original_language: Optional[str] = Field(default=None, min_length=2, max_length=10)
    genres: List[str]
    countries: str = Field(min_length=1)
    runtime: Optional[float] = Field(default=None, gt=0)  # null allowed

    @field_validator("release_date")
    @classmethod
    def not_in_future(cls, value: Optional[date]) -> Optional[date]:
        if value is not None and value > date.today():
            raise ValueError(f"release_date {value} is in the future")
        return value

    @field_validator("genres")
    @classmethod
    def genres_are_recognised(cls, value: List[str]) -> List[str]:
        unknown = [g for g in value if g not in KNOWN_GENRES]
        if unknown:
            raise ValueError(f"unrecognised genre(s): {unknown}")
        return value
