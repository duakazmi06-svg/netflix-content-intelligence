# Netflix Content Intelligence Pipeline

An end-to-end ETL + EDA project: extract Netflix titles from the TMDB API, clean them with pandas, validate every record with Pydantic, load them into a normalized SQLite database, analyze them with 12 visualizations, and publish the results on Render.

**Programming for AI — Project 1 (ETL + EDA Pipeline)**

| Member | Roll no. | Owns |
|---|---|---|
| Dua Raza Kazmi | 2025-AI-200 | Extract + repo (`src/extract.py`, README) |
| _TBD_ | | Transform + validate (`src/transform.py`, `src/models.py`, tests) |
| _TBD_ | | Load + pipeline (`src/load.py`, `src/run_pipeline.py`) |
| _TBD_ | | Deploy + report (`app/`, final `eda.ipynb`, PDF report) |

## Architecture

```
TMDB API ─┐
          ├─► extract.py ─► transform.py ─► models.py ─► load.py ─► netflix_analysis.db ─► EDA + app/
Kaggle CSV┘   raw snapshot   clean DataFrame  valid rows   upserts                          (Render)
              (data/raw/)                     + rejection log
```

| Stage | File | Output |
|---|---|---|
| 1. Extract | `src/extract.py` | `data/raw/extracted_latest.csv` + timestamped JSON snapshot |
| 2. Transform | `src/transform.py` | clean DataFrame |
| 3. Validate | `src/models.py` | valid records + `rejected_records` |
| 4. Load | `src/load.py` | `netflix_analysis.db` |
| 5. Analyze | `notebooks/eda.ipynb` | 12 charts + findings |
| 6. Deploy | `app/` | live Render URL |

The column format every stage passes along is defined in **`src/contract.py`**. Change it only after telling the whole group.

> **Primary key:** TMDB movie and TV IDs overlap, so a title is identified by **(`id`, `media_type`)**, not `id` alone.

## Setup

```bash
git clone <repo-url>
cd netflix-content-intelligence
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your TMDB key into .env
```

Get a free TMDB key at https://www.themoviedb.org/settings/api.

**Kaggle fallback:** download "Netflix Movies and TV Shows" from Kaggle and save it as `data/raw/netflix_titles.csv`. Used automatically when no TMDB key is set or the API fails.

## Running the extract stage

```bash
python -m src.extract                              # TMDB if key set, otherwise Kaggle
python -m src.extract --source tmdb --region PK    # Netflix Pakistan catalog
python -m src.extract --max-pages 50 --details     # more titles + runtime/countries (slower)
python -m src.extract --source kaggle              # offline
```

Each run writes `data/raw/extracted_latest.csv` (read by the transform stage) and a timestamped raw snapshot so any run can be audited or replayed.

## Tests

```bash
python -m pytest -q
```

## Team workflow

- Work on your own branch (`extract`, `transform`, `load`, `deploy`) and only edit your own files.
- Each person keeps their charts in their own notebook (`notebooks/eda_<name>.ipynb`); they are merged into `eda.ipynb` at the end.
- Open a pull request to `main` when your part works. One teammate reviews, then merge.
- Until the upstream stage is ready, use the Kaggle CSV as your input.

## Repository structure

```
netflix-content-intelligence/
├── src/
│   ├── contract.py        # shared column format
│   ├── extract.py
│   ├── models.py          # Pydantic schemas
│   ├── transform.py
│   ├── load.py
│   └── run_pipeline.py
├── notebooks/eda.ipynb
├── data/raw/  data/processed/
├── app/                   # Streamlit app for Render
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```
