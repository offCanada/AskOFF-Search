from typing import Any, Dict, List, Optional, Tuple

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from config.settings import settings
from models.search_document import SearchDocument
from retrieval.ranking import RankingManager
from retrieval.repository import SearchRepository
from search.client import get_client

NUTRIENT_FIELD_MAP = {
    "protein": "proteins",
    "proteins": "proteins",
    "sugar": "sugars",
    "sugars": "sugars",
    "fat": "fat",
    "fats": "fat",
    "calories": "energy-kcal",
    "calorie": "energy-kcal",
    "kcal": "energy-kcal",
    "energy": "energy-kcal",
    "energy-kcal": "energy-kcal",
    "sodium": "sodium",
    "salt": "salt",
    "carbs": "carbohydrates",
    "carbohydrate": "carbohydrates",
    "carbohydrates": "carbohydrates",
    "fiber": "fiber",
    "fibre": "fiber",
    "saturated fat": "saturated-fat",
    "saturated-fat": "saturated-fat",
}


class OpenSearchSearchRepository(SearchRepository):
    def __init__(
        self,
        client: Optional[OpenSearch] = None,
        ranking_manager: Optional[RankingManager] = None,
        index: Optional[str] = None,
    ) -> None:
        self.client = client or get_client()
        self.index = index or settings.opensearch_index
        self.ranking_manager = ranking_manager or RankingManager()

    @staticmethod
    def _tiered_minimum_should_match(query: str) -> int:
        """
        Tiered matching: ensure multi-token queries don't let single incidental tokens dominate.
        """
        import re

        n = len(re.findall(r"[^\s]+", query.strip()))
        if n <= 1:
            return 1
        if n == 2:
            return 2
        return max(2, n // 2 + 1)

    def search(
        self,
        query: str,
        filters: Optional[dict] = None,
        numeric_filters: Optional[List[dict]] = None,
        modifiers: Optional[List[str]] = None,
        ranking_preferences: Optional[dict] = None,
        size: int = 20,
        from_: int = 0,
        explain: bool = False
    ) -> Tuple[int, List[Tuple[float, SearchDocument]], dict]:

        must_clauses: List[Dict[str, Any]] = []
        should_clauses: List[Dict[str, Any]] = []
        must_not_clauses: List[Dict[str, Any]] = []

        fields = self.ranking_manager.get_search_fields()

        if query and query != "*":
            should_clauses.append({
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": fields,
                                "type": "phrase",
                                "boost": self.ranking_manager.phrase_boost
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": fields,
                                "operator": "and",
                                "boost": self.ranking_manager.and_match_boost
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": fields,
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                                "operator": "or",
                                "boost": self.ranking_manager.fuzzy_boost,
                                "minimum_should_match": self._tiered_minimum_should_match(query)
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            })
        elif query == "*":
            must_clauses.append({"match_all": {}})

        if modifiers:
            for mod in modifiers:
                should_clauses.append({
                    "match": {
                        "product_name": {
                            "query": mod,
                            "boost": self.ranking_manager.modifier_boost
                        }
                    }
                })

        if filters:
            for k, v in filters.items():
                if k == "brand" and v:
                    must_clauses.append({"match": {"brand": {"query": v, "operator": "and"}}})
                elif k == "category" and v:
                    must_clauses.append({"match": {"category": {"query": v, "operator": "and"}}})
                elif k == "ingredients" and v:
                    must_clauses.append({"match": {"ingredients": {"query": v, "operator": "and"}}})
                elif k == "is_palm_oil_free":
                    if v is True:
                        should_clauses.append({"term": {"attributes.flags.is_palm_oil_free": {"value": True, "boost": 2.0}}})
                        must_not_clauses.append({"match": {"ingredients": "palm oil"}})
                    elif v is False:
                        must_clauses.append({"match": {"ingredients": "palm oil"}})
                elif k.startswith("is_") and v is not None:
                    must_clauses.append({"term": {f"attributes.flags.{k}": v}})

        if numeric_filters:
            for nf in numeric_filters:
                nutrient = nf.get("nutrient", "")
                op = nf.get("operator", "lte")
                val = nf.get("value", 0.0)
                basis = nf.get("comparison_basis", "per_100g")

                mapped_nutrient = NUTRIENT_FIELD_MAP.get(nutrient, nutrient)
                field_path = f"attributes.nutrition.{mapped_nutrient}.{basis}"

                if op == "eq":
                    must_clauses.append({
                        "range": {
                            field_path: {
                                "gte": max(0.0, val - 0.5),
                                "lte": val + 0.5
                            }
                        }
                    })
                elif op in {"lte", "lt"}:
                    must_clauses.append({
                        "range": {
                            field_path: {
                                op: val,
                                "gte": 0.0
                            }
                        }
                    })
                else:  # gte, gt
                    must_clauses.append({
                        "range": {
                            field_path: {
                                op: val
                            }
                        }
                    })

        # Directional ranking preference (e.g. "lowest sugar", "highest protein")
        sort_clauses: List[Any] = []
        if ranking_preferences and ranking_preferences.get("sort_nutrient"):
            sort_nutrient = ranking_preferences["sort_nutrient"]
            order = ranking_preferences.get("order", "asc")
            mapped_nutrient = NUTRIENT_FIELD_MAP.get(sort_nutrient, sort_nutrient)
            field_path = f"attributes.nutrition.{mapped_nutrient}.per_100g"

            # Filter out documents without this nutrient so empty values don't pollute
            must_clauses.append({
                "range": {
                    field_path: {
                        "gte": 0.0
                    }
                }
            })

            sort_clauses = [
                {
                    field_path: {
                        "order": order,
                        "missing": "_last",
                        "unmapped_type": "float"
                    }
                },
                "_score"
            ]

        if not must_clauses and not should_clauses:
            must_clauses.append({"match_all": {}})

        bool_query = {
            "bool": {
                "must": must_clauses,
                "should": should_clauses,
                "must_not": must_not_clauses,
                "minimum_should_match": 1 if (query and query != "*") else 0
            }
        }

        # Boost functions: completeness + bonus boost for exact zero sugar
        score_functions: List[Dict[str, Any]] = [
            {
                "field_value_factor": {
                    "field": "metadata.completeness",
                    "factor": self.ranking_manager.completeness_factor,
                    "missing": 0.0
                }
            }
        ]

        # If zero sugar was requested, give highest relevance score boost to true 0.0g products
        if numeric_filters and any(nf.get("is_zero_constraint") for nf in numeric_filters):
            score_functions.append({
                "filter": {
                    "range": {
                        "attributes.nutrition.sugars.per_100g": {
                            "lte": 0.05
                        }
                    }
                },
                "weight": 3.0
            })

        query_body: Dict[str, Any] = {
            "track_total_hits": True,
            "size": size,
            "from": from_,
            "query": {
                "function_score": {
                    "query": bool_query,
                    "functions": score_functions,
                    "boost_mode": "sum"
                }
            }
        }

        if sort_clauses:
            query_body["sort"] = sort_clauses

        response = self.client.search(index=self.index, body=query_body)

        hits = response["hits"]["hits"]
        total = response["hits"]["total"]["value"]

        results = []
        for h in hits:
            score = h["_score"] if h.get("_score") is not None else 1.0
            doc = SearchDocument(**h["_source"])
            results.append((score, doc))

        metadata = {}
        if explain:
            metadata["opensearch_query"] = query_body

        return total, results, metadata

    def get_by_id(self, doc_id: str) -> Optional[SearchDocument]:
        try:
            response = self.client.get(index=self.index, id=doc_id)
            return SearchDocument(**response["_source"])
        except NotFoundError:
            query_body = {
                "query": {
                    "term": {
                        "id": doc_id
                    }
                }
            }
            res = self.client.search(index=self.index, body=query_body)
            hits = res["hits"]["hits"]
            if hits:
                return SearchDocument(**hits[0]["_source"])
            return None

    def get_autocomplete(self, query: str, size: int = 5) -> List[str]:
        query_body = {
            "size": size,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "product_name.autocomplete",
                        "search_text.autocomplete",
                    ],
                    "type": "bool_prefix",
                }
            },
        }
        response = self.client.search(index=self.index, body=query_body)
        hits = response["hits"]["hits"]
        return [h["_source"].get("product_name", "") for h in hits]
