from search.synonyms_ca import synonym_tokens

_SYNONYM_TOKENS = synonym_tokens()


def _build_settings() -> dict:
    analysis = {
        "analyzer": {
            "autocomplete_analyzer": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "autocomplete_filter"],
            }
        },
        "filter": {
            "autocomplete_filter": {
                "type": "edge_ngram",
                "min_gram": 2,
                "max_gram": 20,
            }
        },
    }
    if _SYNONYM_TOKENS:
        analysis["analyzer"]["synonym_analyzer"] = {
            "type": "custom",
            "tokenizer": "standard",
            "filter": ["lowercase", "synonym_ca_filter"],
        }
        analysis["filter"]["synonym_ca_filter"] = {
            "type": "synonym",
            "synonyms": _SYNONYM_TOKENS,
        }
    return analysis


PRODUCT_INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "analysis": _build_settings(),
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "dataset_id": {"type": "keyword"},
            "core_product_id": {"type": "keyword"},
            "variant_id": {"type": "keyword"},
            "product_name": {
                "type": "text",
                "analyzer": "synonym_analyzer",
                "fields": {
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "autocomplete_analyzer",
                        "search_analyzer": "standard",
                    }
                },
            },
            "brand": {
                "type": "text",
                "analyzer": "standard",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256}
                }
            },
            "category": {
                "type": "text",
                "analyzer": "synonym_analyzer",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256}
                }
            },
            "ingredients": {
                "type": "text",
                "analyzer": "synonym_analyzer",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256}
                }
            },
            "attributes": {"type": "object", "dynamic": True},
            "metadata": {"type": "object", "dynamic": True},
            "search_text": {
                "type": "text",
                "analyzer": "synonym_analyzer",
                "fields": {
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "autocomplete_analyzer",
                        "search_analyzer": "standard",
                    }
                },
            },
            "semantic_document": {"type": "text", "analyzer": "synonym_analyzer"},
        }
    },
}
