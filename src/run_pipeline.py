"""
run_pipeline.py  (Person 3)

Runs the whole pipeline:   extract -> transform + validate -> load
and writes one audit row in the etl_runs table.

How to run (from the main project folder):
    python src/run_pipeline.py --stand-in                  # test, no teammates' files
    python src/run_pipeline.py                             # real run (TMDB, else Kaggle)
    python src/run_pipeline.py --source kaggle             # force the Kaggle CSV
    python src/run_pipeline.py --source tmdb --region PK   # TMDB, Pakistan catalog

What it uses from the team:
    src/extract.py    extract(source, region, max_pages)
                      -> returns a table AND saves data/raw/extracted_latest.csv
    src/transform.py  transform()
                      -> reads that CSV, cleans it, validates every row (Pydantic),
                         and writes 3 files in data/processed/:
                         titles_clean.csv, rejected_records.csv, data_quality_summary.csv
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))            # lets teammates' "from src.x import" work
sys.path.insert(0, str(ROOT / "src"))    # lets "import load" work

import pandas as pd  # noqa: E402

import load  # noqa: E402

PROCESSED = ROOT / "data" / "processed"


def run_real(source, region, max_pages):
    """Use Person 1's extract and Person 2's transform."""
    from src.extract import extract
    from src.transform import transform

    t = time.time()
    raw = extract(source=source, region=region, max_pages=max_pages)
    print(f"[1/4] Extract   : {len(raw)} rows            ({time.time() - t:.1f}s)")

    t = time.time()
    summary = transform()          # also validates every row
    print(f"[2/4] Transform : {summary['extracted']} rows in, "
          f"{summary['exact_duplicates_removed'] + summary['same_key_duplicates_removed']} "
          f"duplicates removed   ({time.time() - t:.1f}s)")
    print(f"[3/4] Validate  : {summary['valid']} valid, {summary['rejected']} rejected")

    valid = pd.read_csv(PROCESSED / "titles_clean.csv")
    rejected = pd.read_csv(PROCESSED / "rejected_records.csv")
    # TMDB rows belong to the region we asked for (feeds the title_availability table).
    valid["regions"] = valid["source"].map(lambda s: region if s == "tmdb" else None)
    return len(raw), valid, rejected


def run_stand_in():
    """Fake steps, only for testing without the teammates' files."""
    import stand_in
    raw = stand_in.extract()
    print(f"[1/4] Extract   : {len(raw)} rows (stand-in)")
    clean = stand_in.transform(raw)
    print(f"[2/4] Transform : {len(clean)} rows (stand-in)")
    valid, rejected = stand_in.validate(clean)
    print(f"[3/4] Validate  : {len(valid)} valid, {len(rejected)} rejected (stand-in)")
    return len(raw), valid, rejected


def run(source="auto", region="US", max_pages=25, stand_in=False, db_path=load.DB_PATH):
    run_id = load.new_run_id()
    print(f"=== Pipeline run {run_id} ===")

    if stand_in:
        rows_extracted, valid, rejected = run_stand_in()
    else:
        rows_extracted, valid, rejected = run_real(source, region, max_pages)

    t = time.time()
    engine = load.get_engine(db_path)
    load.create_tables(engine)
    rows_loaded = load.load_titles(engine, valid)
    load.load_rejected(engine, rejected, run_id)
    load.log_run(engine, run_id, rows_extracted=rows_extracted,
                 rows_loaded=rows_loaded, rows_rejected=len(rejected))
    print(f"[4/4] Load      : {rows_loaded} rows saved       ({time.time() - t:.1f}s)")
    print(f"Done. Database: {db_path}")
    return run_id


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the Netflix ETL pipeline")
    ap.add_argument("--source", default="auto", choices=["auto", "tmdb", "kaggle"])
    ap.add_argument("--region", default="US", help="TMDB region code, e.g. US or PK")
    ap.add_argument("--max-pages", type=int, default=25, help="TMDB pages per media type")
    ap.add_argument("--stand-in", action="store_true",
                    help="use fake steps and the Kaggle CSV (for testing)")
    args = ap.parse_args()
    try:
        run(source=args.source, region=args.region.upper(),
            max_pages=args.max_pages, stand_in=args.stand_in)
    except Exception as err:
        print(f"\nPIPELINE FAILED: {type(err).__name__}: {err}")
        sys.exit(1)
