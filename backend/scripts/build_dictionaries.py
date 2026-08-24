"""
Builds static entity dictionaries (brands, categories, ingredients) from the
local normalized dataset and writes them to backend/data/dictionaries.json.

This removes the circular dependency where NLP entity extraction depended on
whatever happened to be loaded in the OpenSearch index.

Usage:
    python scripts/build_dictionaries.py [--source data/raw/normalized.parquet]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import duckdb  # noqa: E402

from utils.off_parser import parse_ingredients_text  # noqa: E402


def _clean_piece(piece: str) -> str | None:
    piece = piece.strip().lower()
    # strip parenthetical annotation like "en:..." or trailing labels
    piece = re.sub(r"\s*\([^)]*\)", "", piece)
    piece = re.sub(r"\s*en:[a-z0-9\-]+", "", piece)
    piece = re.sub(r"[^a-z0-9\s\-%&']+", "", piece)
    piece = re.sub(r"\s+", " ", piece).strip()
    if not piece or len(piece) > 48:
        return None
    if piece in {"", "null", "none", "nan"}:
        return None
    return piece


def build(source: Path, top_brands: int, top_categories: int, top_ingredients: int) -> dict:
    con = duckdb.connect()
    try:
        cols = con.execute(f"DESCRIBE SELECT * FROM '{source}'").fetchall()
        col_names = {c[0].lower() for c in cols}
        brand_col = "brands_clean" if "brands_clean" in col_names else ("brands" if "brands" in col_names else "brand")
        cat_col = "categories_clean" if "categories_clean" in col_names else ("categories" if "categories" in col_names else "category")
        ing_col = "ingredients_clean" if "ingredients_clean" in col_names else ("ingredients_text" if "ingredients_text" in col_names else "ingredients")

        brand_counter: Counter = Counter()
        cat_counter: Counter = Counter()
        ing_counter: Counter = Counter()

        rows = con.execute(
            f"SELECT {brand_col}, {cat_col}, {ing_col} FROM '{source}'"
        ).fetchall()
        for brand_raw, cat_raw, ing_raw in rows:
            if brand_raw:
                for piece in str(brand_raw).split(","):
                    cleaned = _clean_piece(piece)
                    if cleaned:
                        brand_counter[cleaned] += 1
            if cat_raw:
                if isinstance(cat_raw, list):
                    for piece in cat_raw:
                        cleaned = _clean_piece(str(piece))
                        if cleaned:
                            cat_counter[cleaned] += 1
                else:
                    for piece in str(cat_raw).split(","):
                        cleaned = _clean_piece(piece)
                        if cleaned:
                            cat_counter[cleaned] += 1
            if ing_raw:
                ing_text = parse_ingredients_text(ing_raw) if (isinstance(ing_raw, list) or (isinstance(ing_raw, str) and "{" in ing_raw)) else str(ing_raw)
                if ing_text:
                    for piece in re.split(r"[,;()]", ing_text):
                        cleaned = _clean_piece(piece)
                        if cleaned:
                            ing_counter[cleaned] += 1
    finally:
        con.close()

    result = {
        "source": str(source),
        "brands": [b for b, _ in brand_counter.most_common(top_brands)],
        "categories": [c for c, _ in cat_counter.most_common(top_categories)],
        "ingredients": [i for i, _ in ing_counter.most_common(top_ingredients)],
    }

    # Guarantee common demo/recipe entities are present even if frequency
    # analysis missed them.
    always_include = {
        "blueberries": "ingredients",
        "milk": "ingredients",
        "butter": "ingredients",
        "oats": "ingredients",
        "bread": "ingredients",
        "coffee": "ingredients",
        "chips": "ingredients",
        "tomatoes": "ingredients",
        "peanut butter": "ingredients",
        "cheese": "ingredients",
        "honey": "ingredients",
        "sugar": "ingredients",
        "salt": "ingredients",
        "wheat": "ingredients",
        "soy": "ingredients",
        "almond": "ingredients",
    }
    for entity, bucket in always_include.items():
        if entity not in result[bucket]:
            result[bucket].append(entity)
    return result


def main() -> None:
    default_source = (
        "data/raw/off_canada_with_images.parquet"
        if Path("data/raw/off_canada_with_images.parquet").exists()
        else "data/raw/normalized.parquet"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=default_source)
    parser.add_argument("--output", default=str(BASE / "data" / "dictionaries.json"))
    parser.add_argument("--top-brands", type=int, default=12000)
    parser.add_argument("--top-categories", type=int, default=6000)
    parser.add_argument("--top-ingredients", type=int, default=15000)
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists() and not Path(f"{BASE}/{args.source}").exists():
        die = Path(f"{BASE}/{args.source}")
        if not die.exists():
            print(f"ERROR: source dataset not found at {source} or {die}", file=sys.stderr)
            sys.exit(1)
        source = die

    result = build(source, args.top_brands, args.top_categories, args.top_ingredients)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(
        f"Wrote {len(result['brands'])} brands, {len(result['categories'])} categories, "
        f"{len(result['ingredients'])} ingredients -> {out}"
    )


if __name__ == "__main__":
    main()
