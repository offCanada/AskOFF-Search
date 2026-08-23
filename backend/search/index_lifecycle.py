"""Safe physical-index and alias operations for the serving search index."""

import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from opensearchpy import OpenSearch

from config.settings import settings
from search.mappings import PRODUCT_INDEX_MAPPING

_INDEX_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_index_name(index_name: str) -> str:
    if not _INDEX_NAME_RE.fullmatch(index_name):
        raise ValueError(f"Invalid OpenSearch index name: {index_name!r}")
    return index_name


def new_versioned_index_name(alias: str | None = None) -> str:
    alias = _validate_index_name(alias or settings.opensearch_index)
    return f"{alias}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def create_index(client: OpenSearch, index_name: str) -> None:
    index_name = _validate_index_name(index_name)
    if client.indices.exists(index=index_name):
        raise ValueError(f"Target index already exists: {index_name}")
    client.indices.create(index=index_name, body=deepcopy(PRODUCT_INDEX_MAPPING))


def validate_index(
    client: OpenSearch, index_name: str, expected_count: int | None = None
) -> dict[str, Any]:
    index_name = _validate_index_name(index_name)
    if not client.indices.exists(index=index_name):
        raise ValueError(f"Index does not exist: {index_name}")
    client.indices.refresh(index=index_name)
    count = int(client.count(index=index_name).get("count", 0))
    if count == 0:
        raise ValueError(f"Index is empty: {index_name}")
    if expected_count is not None and count != expected_count:
        raise ValueError(f"Index count {count} does not match expected count {expected_count}")
    sample = client.search(
        index=index_name,
        body={
            "size": 1,
            "query": {"exists": {"field": "product_name"}},
            "_source": ["id", "product_name"],
        },
    )
    if not sample.get("hits", {}).get("hits", []):
        raise ValueError(f"Index has no searchable product-name document: {index_name}")
    health = client.cluster.health(index=index_name).get("status", "unknown")
    if health == "red":
        raise ValueError(f"Index health is red: {index_name}")
    return {"index": index_name, "count": count, "health": health}


def promote_index(client: OpenSearch, index_name: str, alias: str | None = None) -> None:
    index_name = _validate_index_name(index_name)
    alias = _validate_index_name(alias or settings.opensearch_index)
    # ``indices.exists(index=alias)`` resolves an alias to its target index in
    # OpenSearch. Determine alias ownership from the alias API first, otherwise
    # every subsequent promotion is misclassified as a legacy concrete index.
    alias_response = client.indices.get_alias(name=alias, ignore=[404])
    # OpenSearch-Py returns {"error": ..., "status": 404} for an ignored
    # missing alias. Retain only actual index entries that own this alias.
    current = {
        index: metadata
        for index, metadata in alias_response.items()
        if isinstance(metadata, dict) and alias in metadata.get("aliases", {})
    }
    alias_exists = bool(current)
    if not alias_exists and client.indices.exists(index=alias):
        raise ValueError(
            f"Serving name {alias!r} is a concrete index, not an alias. "
            "Migrate it explicitly before promotion."
        )
    if not client.indices.exists(index=index_name):
        raise ValueError(f"Target index does not exist: {index_name}")
    actions = [{"remove": {"index": old_index, "alias": alias}} for old_index in current]
    actions.append({"add": {"index": index_name, "alias": alias}})
    client.indices.update_aliases(body={"actions": actions})


def rollback_index(client: OpenSearch, target_index: str, alias: str | None = None) -> None:
    promote_index(client, target_index, alias)
