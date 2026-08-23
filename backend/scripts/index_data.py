"""Index the configured source dataset into an existing physical index."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.off_adapter import OFFAdapter
from builders.search_document_builder import SearchDocumentBuilder
from config.settings import settings
from search.client import get_client
from search.indexer import index_products


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    client = get_client()
    builder = SearchDocumentBuilder()
    batch = []
    attempted = indexed = 0
    for raw in OFFAdapter().extract_raw_products(limit=args.limit):
        batch.append(builder.build(raw))
        attempted += 1
        if len(batch) >= settings.pipeline_batch_size:
            indexed += index_products(batch, client=client, index_name=args.index)
            batch = []
    if batch:
        indexed += index_products(batch, client=client, index_name=args.index)
    print(f"attempted={attempted} indexed={indexed} index={args.index}")


if __name__ == "__main__":
    main()
