"""Build and atomically promote a new index for a clean deployment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.off_adapter import OFFAdapter
from builders.search_document_builder import SearchDocumentBuilder
from config.settings import settings
from search.client import get_client
from search.index_lifecycle import (
    create_index,
    new_versioned_index_name,
    promote_index,
    validate_index,
)
from search.indexer import index_products


def main() -> None:
    client = get_client()
    target_index = new_versioned_index_name()
    create_index(client, target_index)
    builder = SearchDocumentBuilder()
    batch = []
    attempted = indexed = 0
    for raw in OFFAdapter().extract_raw_products():
        batch.append(builder.build(raw))
        attempted += 1
        if len(batch) >= settings.pipeline_batch_size:
            indexed += index_products(batch, client=client, index_name=target_index)
            batch = []
    if batch:
        indexed += index_products(batch, client=client, index_name=target_index)
    validation = validate_index(client, target_index, expected_count=attempted)
    promote_index(client, target_index)
    print(
        f"promoted={target_index} attempted={attempted} indexed={indexed} "
        f"health={validation['health']}"
    )


if __name__ == "__main__":
    main()
