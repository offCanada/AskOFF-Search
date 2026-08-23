"""
Canonical index verification script for AskOFF P3.

Reports:
- Source dataset path
- Source row count (from DuckDB / Parquet)
- OpenSearch host & cluster health
- OpenSearch target index name
- OpenSearch indexed document count
- Nutrition coverage count in OpenSearch
- Verification timestamp
"""

import sys
import time
from pathlib import Path

# Ensure backend root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from config.settings import settings
from search.client import get_client


def verify_canonical_index() -> dict:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())

    # 1. Source Parquet Dataset Verification
    source_path = settings.raw_data_path
    if not source_path.exists():
        candidates = [
            Path("data/raw/normalized.parquet"),
            Path("backend/data/processed/normalized.parquet"),
            Path("data/processed/normalized.parquet"),
        ]
        for c in candidates:
            if c.exists():
                source_path = c
                break

    source_exists = source_path.exists()
    source_row_count = 0
    if source_exists:
        con = duckdb.connect()
        try:
            source_row_count = con.execute(
                f"SELECT COUNT(*) FROM '{source_path}'"
            ).fetchone()[0]
        finally:
            con.close()

    # 2. OpenSearch Cluster & Index Verification
    client = get_client()
    index_name = settings.opensearch_index

    cluster_health = "unknown"
    index_exists = False
    index_doc_count = 0
    nutrition_doc_count = 0
    store_size_bytes = 0

    try:
        health_res = client.cluster.health()
        cluster_health = health_res.get("status", "unknown")
        index_exists = client.indices.exists(index=index_name)

        if index_exists:
            count_res = client.count(index=index_name)
            index_doc_count = count_res.get("count", 0)

            # Count documents with populated nutrition
            nut_count_res = client.count(
                index=index_name,
                body={
                    "query": {
                        "exists": {
                            "field": "attributes.nutrition.proteins.per_100g"
                        }
                    }
                },
            )
            nutrition_doc_count = nut_count_res.get("count", 0)

            stats_res = client.indices.stats(index=index_name)
            store_size_bytes = (
                stats_res.get("indices", {})
                .get(index_name, {})
                .get("total", {})
                .get("store", {})
                .get("size_in_bytes", 0)
            )
    except Exception as e:
        print(f"Warning: OpenSearch query error: {e}", file=sys.stderr)

    report = {
        "timestamp": timestamp,
        "source_dataset_path": str(source_path),
        "source_dataset_exists": source_exists,
        "source_row_count": source_row_count,
        "opensearch_hosts": settings.opensearch_hosts,
        "opensearch_cluster_health": cluster_health,
        "opensearch_index_name": index_name,
        "opensearch_index_exists": index_exists,
        "opensearch_indexed_doc_count": index_doc_count,
        "opensearch_nutrition_doc_count": nutrition_doc_count,
        "opensearch_store_size_mb": round(store_size_bytes / (1024 * 1024), 2),
        "is_canonical_114k": (index_doc_count == source_row_count and source_row_count >= 100000),
    }

    print("=" * 60)
    print("AskOFF P3 Canonical Index Verification Report")
    print("=" * 60)
    print(f"Timestamp:                    {report['timestamp']}")
    print(f"Source Dataset:               {report['source_dataset_path']}")
    print(f"Source Row Count:             {report['source_row_count']:,}")
    print(f"OpenSearch Host:              {', '.join(report['opensearch_hosts'])}")
    print(f"OpenSearch Cluster Health:    {report['opensearch_cluster_health']}")
    print(f"OpenSearch Index Name:        {report['opensearch_index_name']}")
    print(f"Indexed Document Count:       {report['opensearch_indexed_doc_count']:,}")
    print(f"Docs With Nutrition (prot):   {report['opensearch_nutrition_doc_count']:,}")
    print(f"Index Store Size:             {report['opensearch_store_size_mb']} MiB")
    print(f"Status:                       {'CANONICAL 114K VERIFIED' if report['is_canonical_114k'] else 'MISMATCH / INCOMPLETE'}")
    print("=" * 60)

    return report


if __name__ == "__main__":
    verify_canonical_index()
