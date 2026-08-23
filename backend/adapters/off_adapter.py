import logging
from pathlib import Path
from typing import Iterable

import duckdb

from adapters.base import BaseAdapter
from config.settings import settings
from models.raw_product import RawProduct
from utils.off_parser import (
    parse_ingredients_text,
    parse_nutriments,
    parse_product_name,
    safe_float,
    safe_int,
    safe_str,
)

logger = logging.getLogger(__name__)

class OFFAdapter(BaseAdapter):
    def __init__(self, data_path: str | None = None) -> None:
        self.data_path = data_path or str(settings.raw_data_path)
        # If the default raw path doesn't exist, check local 114k parquet or fallback paths
        if not Path(self.data_path).exists():
            candidates = [
                Path("data/raw/normalized.parquet"),
                Path("backend/data/processed/normalized.parquet"),
                Path("data/processed/normalized.parquet"),
                Path("data/raw/open_food_facts_canada_all_columns.csv"),
                Path("backend/data/raw/open_food_facts_canada_all_columns.csv"),
            ]
            for cand in candidates:
                if cand.exists():
                    self.data_path = str(cand)
                    break

    def extract_raw_products(self, limit: int | None = None) -> Iterable[RawProduct]:
        path = Path(self.data_path)
        if not path.exists():
            raise FileNotFoundError(f"Data file not found at {self.data_path}")

        con = duckdb.connect()
        try:
            is_parquet = path.suffix.lower() == ".parquet"
            if is_parquet:
                # Detect available columns in parquet
                schema = con.execute(f"DESCRIBE SELECT * FROM '{self.data_path}'").fetchall()
                col_names = {c[0].lower() for c in schema}

                name_col = "product_name_clean" if "product_name_clean" in col_names else "product_name"
                brand_col = "brands_clean" if "brands_clean" in col_names else ("brands" if "brands" in col_names else "brand")
                cat_col = "categories_clean" if "categories_clean" in col_names else ("categories" if "categories" in col_names else "category")
                ing_col = "ingredients_clean" if "ingredients_clean" in col_names else ("ingredients_text" if "ingredients_text" in col_names else "ingredients")
                code_col = "code" if "code" in col_names else "id"
                nut_col = "nutriments" if "nutriments" in col_names else ("attributes" if "attributes" in col_names else "NULL as nutriments")
                ns_col = "nutriscore_grade" if "nutriscore_grade" in col_names else "NULL as nutriscore_grade"
                nova_col = "nova_group" if "nova_group" in col_names else "NULL as nova_group"
                eco_col = "ecoscore_grade" if "ecoscore_grade" in col_names else "NULL as ecoscore_grade"
                comp_col = "completeness" if "completeness" in col_names else "NULL as completeness"

                query = f"""
                    SELECT
                        {code_col} as code,
                        {name_col} as product_name,
                        {brand_col} as brands,
                        {cat_col} as categories,
                        {ing_col} as ingredients_text,
                        {nut_col} as nutriments,
                        {ns_col} as nutriscore_grade,
                        {nova_col} as nova_group,
                        {eco_col} as ecoscore_grade,
                        {comp_col} as completeness
                    FROM '{self.data_path}'
                """
            else:
                cols = [
                    "code",
                    "product_name",
                    "brands",
                    "categories",
                    "ingredients_text",
                    "nutriments",
                    "nutriscore_grade",
                    "nova_group",
                    "ecoscore_grade",
                    "completeness",
                ]
                cols_str = ", ".join(cols)
                query = f"SELECT {cols_str} FROM read_csv_auto('{self.data_path}')"

            if limit is not None:
                query += f" LIMIT {limit}"

            res = con.execute(query)

            while True:
                chunk = res.fetchmany(settings.pipeline_batch_size)
                if not chunk:
                    break
                for row in chunk:
                    code = safe_str(row[0])
                    raw_product_name = safe_str(row[1])
                    raw_brands = safe_str(row[2])
                    raw_categories = safe_str(row[3])
                    raw_ingredients = safe_str(row[4])
                    raw_nutriments = safe_str(row[5])

                    product_name = parse_product_name(raw_product_name)
                    if not product_name:
                        product_name = raw_product_name.strip()

                    ingredients_text = parse_ingredients_text(raw_ingredients)
                    if not ingredients_text:
                        ingredients_text = raw_ingredients.strip()

                    nutriments = parse_nutriments(raw_nutriments)

                    yield RawProduct(
                        code=code,
                        product_name=product_name,
                        brands=raw_brands.strip(),
                        categories=raw_categories.strip(),
                        ingredients_text=ingredients_text,
                        nutriments=nutriments,
                        nutriscore_grade=safe_str(row[6]) if row[6] is not None else None,
                        nova_group=safe_int(row[7]),
                        ecoscore_grade=safe_str(row[8]) if row[8] is not None else None,
                        completeness=safe_float(row[9])
                    )
        finally:
            con.close()

