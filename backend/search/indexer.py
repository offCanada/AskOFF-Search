import json
import logging
import math
import time
from typing import Optional

from opensearchpy import OpenSearch, helpers

from config.settings import settings
from models.search_document import SearchDocument

from .client import get_client
from .mappings import PRODUCT_INDEX_MAPPING

logger = logging.getLogger(__name__)


def _sanitize(obj: object) -> object:
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class _NanSafeJSONEncoder(json.JSONEncoder):
    def default(self, obj: object) -> object:
        if isinstance(obj, float) and math.isnan(obj):
            return None
        return super().default(obj)


def ensure_index(client: OpenSearch, index_name: Optional[str] = None) -> None:
    index_name = index_name or settings.opensearch_index
    if client.indices.exists(index=index_name):
        logger.info("Index '%s' already exists", index_name)
        return
    client.indices.create(index=index_name, body=PRODUCT_INDEX_MAPPING)
    logger.info("Created index '%s'", index_name)


def delete_index(client: OpenSearch, index_name: Optional[str] = None) -> None:
    index_name = index_name or settings.opensearch_index
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
        logger.info("Deleted index '%s'", index_name)


def index_products(
    products: list[SearchDocument],
    max_retries: int = 3,
    *,
    client: Optional[OpenSearch] = None,
    index_name: Optional[str] = None,
) -> int:
    client = client or get_client()
    index_name = index_name or settings.opensearch_index
    ensure_index(client, index_name)

    actions = [
        {
            "_index": index_name,
            "_id": p.id,
            "_source": _sanitize(p.model_dump()),
        }
        for p in products
    ]

    for attempt in range(max_retries):
        try:
            success, errors = helpers.bulk(
                client,
                actions,
                raise_on_error=False,
                chunk_size=settings.pipeline_batch_size,
            )
            if errors:
                logger.error("Indexing errors (showing first 5): %s", errors[:5])
                for err in errors[:5]:
                    detail = err.get("index", {}).get("error", {})
                    logger.error("  Reason: %s", detail.get("reason", "unknown"))

                failed_path = settings.processed_dir / "failed_documents.jsonl"
                settings.processed_dir.mkdir(parents=True, exist_ok=True)
                with open(failed_path, "a", encoding="utf-8") as f:
                    for err in errors:
                        doc_id = err.get("index", {}).get("_id")
                        if doc_id:
                            f.write(json.dumps({"_id": doc_id, "error": err.get("index", {}).get("error")}) + "\n")

            logger.info("Indexed %d products (%d errors)", success, len(errors))
            return success

        except Exception as e:
            logger.warning("Bulk indexing failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error("Failed to index batch after %d attempts", max_retries)
                raise
    return 0
