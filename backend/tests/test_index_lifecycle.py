from unittest.mock import MagicMock

import pytest

from search.index_lifecycle import create_index, promote_index, validate_index


def test_create_index_does_not_overwrite_an_existing_target():
    client = MagicMock()
    client.indices.exists.return_value = True
    with pytest.raises(ValueError, match="already exists"):
        create_index(client, "askoff_products_20260823")
    client.indices.create.assert_not_called()


def test_validate_index_rejects_empty_index():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.count.return_value = {"count": 0}
    with pytest.raises(ValueError, match="empty"):
        validate_index(client, "askoff_products_20260823")


def test_validate_index_rejects_red_health():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.count.return_value = {"count": 1}
    client.search.return_value = {"hits": {"hits": [{"_source": {"product_name": "Milk"}}]}}
    client.cluster.health.return_value = {"status": "red"}
    with pytest.raises(ValueError, match="red"):
        validate_index(client, "askoff_products_20260823")


def test_promote_switches_alias_atomically_without_deleting_old_index():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.indices.get_alias.return_value = {
        "askoff_products_20260822": {"aliases": {"askoff_products": {}}}
    }
    promote_index(client, "askoff_products_20260823")
    actions = client.indices.update_aliases.call_args.kwargs["body"]["actions"]
    assert {"remove": {"index": "askoff_products_20260822", "alias": "askoff_products"}} in actions
    assert {"add": {"index": "askoff_products_20260823", "alias": "askoff_products"}} in actions


def test_promote_does_not_misclassify_an_existing_alias_as_a_concrete_index():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.indices.get_alias.return_value = {
        "askoff_products_20260822": {"aliases": {"askoff_products": {}}}
    }

    promote_index(client, "askoff_products_20260823")

    client.indices.update_aliases.assert_called_once()


def test_promote_ignores_an_error_payload_for_a_missing_alias():
    client = MagicMock()
    client.indices.get_alias.return_value = {"error": "alias missing", "status": 404}
    client.indices.exists.side_effect = lambda *, index: index == "askoff_products_20260823"

    promote_index(client, "askoff_products_20260823")

    assert client.indices.update_aliases.call_args.kwargs["body"]["actions"] == [
        {"add": {"index": "askoff_products_20260823", "alias": "askoff_products"}}
    ]
