"""
Shared data contract for the whole team.

Every stage passes data in THIS shape. If you need to rename, add or remove a
column, tell the group first: changing it breaks the other three stages.

Primary key note: TMDB movie IDs and TV IDs come from separate counters, so the
same number can be both a movie and a show. A title is uniquely identified by
(id, media_type), never by id alone.
"""

# Columns produced by extract.py, in this order.
CONTRACT_COLUMNS = [
    "id",                 # int    TMDB id (or numeric part of Kaggle show_id)
    "media_type",         # str    "movie" or "tv"
    "title",              # str    non-empty
    "release_date",       # str    "YYYY-MM-DD" or None
    "release_year",       # int    or None
    "vote_average",       # float  0-10 or None (Kaggle has no ratings)
    "vote_count",         # int    >= 0 or None
    "popularity",         # float  >= 0 or None
    "original_language",  # str    ISO 639-1 code, e.g. "en", or None
    "genres",             # str    pipe-separated genre names, e.g. "Drama|Crime"
    "countries",          # str    pipe-separated, e.g. "US|GB", or None
    "runtime",            # int    minutes (movies) / avg episode minutes (tv), or None
    "content_rating",     # str    e.g. "PG-13", "TV-MA" (Kaggle only), or None
    "overview",           # str    description, or None
    "source",             # str    "tmdb" or "kaggle"
    "extracted_at",       # str    ISO timestamp of the extract run
]

# Separator used for multi-valued fields (genres, countries).
MULTI_SEP = "|"

# Stable path the next stage (transform.py) reads from.
LATEST_EXTRACT_PATH = "data/raw/extracted_latest.csv"
