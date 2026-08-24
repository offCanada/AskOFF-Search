import inspect
import time
from typing import Any, Dict, List, Optional, Union

from models.search import SearchHit, SearchResponse
from models.search_document import SearchDocument
from query.dictionaries import CATEGORIES, INGREDIENTS
from query.pipeline import SearchQueryPipeline
from query.search_query import SearchQuery
from retrieval.filters import FiltersManager
from retrieval.query_parser import QueryParser
from retrieval.repository import SearchRepository


def _is_brand_only(value: str) -> bool:
    """A brand value that is also a category/ingredient word (e.g. 'chips', 'soy')
    is ambiguous and must not be promoted to a hard filter."""
    v = value.lower()
    return v not in CATEGORIES and v not in INGREDIENTS


def _strip_brand_from_text(text: str, brand: str) -> str:
    """Remove the brand phrase from query text, keeping the remaining product terms."""
    import re

    stripped = re.sub(
        r"(?<![a-z0-9])" + re.escape(brand.lower()) + r"(?![a-z0-9])",
        " ",
        text.lower(),
    )
    return re.sub(r"\s+", " ", stripped).strip()


class SearchEngine:
    def __init__(
        self,
        repository: SearchRepository,
    ) -> None:
        self.repository = repository

    def search(
        self,
        query: Union[str, SearchQuery],
        filters: Optional[Dict[str, Any]] = None,
        size: int = 20,
        from_: int = 0,
        explain: bool = False
    ) -> SearchResponse:

        start_time = time.time()
        api_filters = filters or {}

        if isinstance(query, str):
            search_query = SearchQueryPipeline.process(query, size=size, from_=from_)

            # Merge explicit API filters into the search query
            entity_key_map = {
                "brand": "brands",
                "category": "categories",
                "ingredients": "ingredients",
            }
            for k, val in api_filters.items():
                if val is not None:
                    if k in entity_key_map:
                        entity_key = entity_key_map[k]
                        search_query.entities.setdefault(entity_key, []).append({
                            "value": val,
                            "explanation": "Manual override from API parameter"
                        })
                    else:
                        search_query.filters[k] = val
        else:
            search_query = query

        # Build retrieval filters from entities and constraints
        retrieval_filters: Dict[str, Any] = {}

        def is_explicit_override(entity_list: List[Dict]) -> bool:
            if not entity_list:
                return False
            for e in entity_list:
                if "Manual override" in e.get("explanation", ""):
                    return True
            return False

        brand_entities = search_query.entities.get("brands", [])
        category_entities = search_query.entities.get("categories", [])
        ingredient_entities = search_query.entities.get("ingredients", [])

        if search_query.intent == "brand_search" or is_explicit_override(brand_entities):
            if brand_entities:
                retrieval_filters["brand"] = brand_entities[0]["value"]

        # Promotes a recognized unambiguous brand (e.g. Compliments, Silk, Kraft)
        # to a hard brand filter when product terms remain in the query text.
        elif brand_entities and _is_brand_only(brand_entities[0]["value"]) and search_query.text_term:
            brand_value = brand_entities[0]["value"]
            remaining = _strip_brand_from_text(search_query.text_term, brand_value)
            if remaining:
                retrieval_filters["brand"] = brand_value
                search_query.text_term = remaining

        if search_query.intent == "category_browse" or is_explicit_override(category_entities):
            if category_entities:
                retrieval_filters["category"] = category_entities[0]["value"]

        if search_query.intent == "ingredient_search" or is_explicit_override(ingredient_entities):
            if ingredient_entities:
                retrieval_filters["ingredients"] = ingredient_entities[0]["value"]

        # Map constraint filters to retrieval filters
        palm_oil_filter = search_query.filters.get("palm_oil")
        if palm_oil_filter is not None:
            retrieval_filters["is_palm_oil_free"] = not palm_oil_filter

        constraint_to_filter = {
            "organic": "is_organic",
            "vegan": "is_vegan",
            "vegetarian": "is_vegetarian",
            "high_protein": "is_high_protein",
            "low_sugar": "is_low_sugar",
            "low_sodium": "is_low_sodium",
            "gluten_free": "is_gluten_free",
            "lactose_free": "is_lactose_free",
        }
        for constraint_key, filter_key in constraint_to_filter.items():
            val = search_query.filters.get(constraint_key)
            if val is not None:
                retrieval_filters[filter_key] = val

        final_filters = FiltersManager.build_filters(retrieval_filters)

        text_term = search_query.text_term

        if search_query.intent in ("brand_search", "category_browse", "ingredient_search"):
            text_term = ""

        q_size = search_query.pagination.get("size", size)
        q_from = search_query.pagination.get("from", from_)

        # Collect additional context for the repository layer
        numeric_filters = getattr(search_query, "numeric_filters", [])
        modifiers = getattr(search_query, "modifiers", [])
        ranking_preferences = getattr(search_query, "ranking_preferences", {})

        repo_kwargs: Dict[str, Any] = {
            "query": text_term,
            "filters": final_filters,
            "numeric_filters": numeric_filters,
            "modifiers": modifiers,
            "size": q_size,
            "from_": q_from,
            "explain": explain,
        }

        try:
            sig = inspect.signature(self.repository.search)
            if "ranking_preferences" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                repo_kwargs["ranking_preferences"] = ranking_preferences
        except (ValueError, TypeError):
            pass

        total, hits, repo_metadata = self.repository.search(**repo_kwargs)

        took_ms = int((time.time() - start_time) * 1000)

        search_hits = [
            SearchHit(score=score, product=doc)
            for score, doc in hits
        ]

        explain_data = None
        if explain:
            explain_data = {
                "original_query": getattr(
                    search_query, "original_query", query if isinstance(query, str) else ""
                ),
                "normalized_query": getattr(search_query, "normalized_query", ""),
                "intent": search_query.intent,
                "parsed_query": search_query.text_term,
                "extracted_entities": search_query.entities,
                "constraints": search_query.filters,
                "filters": search_query.filters,
                "numeric_filters": numeric_filters,
                "modifiers": getattr(search_query, "modifiers", []),
                "recipe_quantities": getattr(search_query, "recipe_quantities", []),
                "ranking_preferences": ranking_preferences,
                "pagination": {
                    "size": q_size,
                    "from": q_from,
                    "page": (q_from // q_size) + 1 if q_size > 0 else 1,
                },
                "metadata": search_query.metadata,
                "opensearch_query": repo_metadata.get("opensearch_query", {}),
                "total_results": total,
                "page": (q_from // q_size) + 1 if q_size > 0 else 1,
                "size": q_size,
            }

        return SearchResponse(
            total=total,
            hits=search_hits,
            query=query if isinstance(query, str) else query.original_query,
            took_ms=took_ms,
            search_query=explain_data
        )

    def get_product(self, barcode: str) -> Optional[SearchDocument]:
        return self.repository.get_by_id(barcode)

    def autocomplete(self, query: str, size: int = 5) -> List[str]:
        parsed = QueryParser.parse(query)
        if not parsed:
            return []
        return self.repository.get_autocomplete(parsed, size=size)
