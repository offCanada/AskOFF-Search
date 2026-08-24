import logging
from pathlib import Path
from typing import Iterable, Optional

import duckdb

from adapters.base import BaseAdapter
from config.settings import settings
from models.raw_product import RawProduct
from utils.off_parser import (
    parse_nutriments,
    parse_product_name,
    safe_str,
)

logger = logging.getLogger(__name__)


class ComplimentsAdapter(BaseAdapter):
    """Adapter for Ramya's Compliments product dataset (data/raw/compliments_products.parquet)."""

    def __init__(self, data_path: Optional[str] = None) -> None:
        self.data_path = data_path or "data/raw/compliments_products.parquet"
        # If relative path does not exist, look up common candidate locations
        if not Path(self.data_path).exists():
            candidates = [
                Path("data/raw/compliments_products.parquet"),
                Path("backend/data/raw/compliments_products.parquet"),
                Path("../data/raw/compliments_products.parquet"),
            ]
            for cand in candidates:
                if cand.exists():
                    self.data_path = str(cand)
                    break

    def extract_raw_products(self, limit: Optional[int] = None) -> Iterable[RawProduct]:
        path = Path(self.data_path)
        if not path.exists():
            raise FileNotFoundError(f"Compliments data file not found at {self.data_path}")

        con = duckdb.connect()
        try:
            query = f"""
                SELECT
                    code,
                    brand,
                    product_name,
                    nutriments,
                    nutriments_estimated,
                    quantity,
                    product_quantity,
                    product_quantity_unit
                FROM '{self.data_path}'
            """
            if limit is not None:
                query += f" LIMIT {limit}"

            res = con.execute(query)

            while True:
                chunk = res.fetchmany(settings.pipeline_batch_size)
                if not chunk:
                    break
                for row in chunk:
                    code = safe_str(row[0])
                    raw_brand = safe_str(row[1])
                    raw_product_name = safe_str(row[2])
                    raw_nutriments = safe_str(row[3])
                    # row[4]: nutriments_estimated, row[5]: quantity, row[6]: product_quantity, row[7]: product_quantity_unit

                    product_name = parse_product_name(raw_product_name)
                    if not product_name:
                        product_name = raw_product_name.strip()

                    nutriments = parse_nutriments(raw_nutriments)

                    yield RawProduct(
                        code=code,
                        product_name=product_name,
                        brands=raw_brand.strip(),
                        categories="",
                        ingredients_text="",
                        nutriments=nutriments,
                        nutriscore_grade=None,
                        nova_group=None,
                        ecoscore_grade=None,
                        completeness=0.0,
                    )
        finally:
            con.close()
