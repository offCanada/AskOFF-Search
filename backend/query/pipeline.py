import time

from query.constraint_extractor import ConstraintExtractor
from query.entity_extractor import EntityExtractor
from query.intent_detector import IntentDetector
from query.normalizer import QueryNormalizer
from query.search_query import SearchQuery
from search.synonyms_ca import canonicalize


class SearchQueryPipeline:
    @staticmethod
    def process(
        raw_query: str,
        size: int = 20,
        from_: int = 0
    ) -> SearchQuery:
        start_time = time.time()

        normalized = QueryNormalizer.normalize(raw_query)
        normalized = canonicalize(normalized)
        constraints = ConstraintExtractor.extract(normalized)
        cleaned = constraints["cleaned_query"]

        intent = IntentDetector.detect(cleaned)
        entities = EntityExtractor.extract(cleaned, intent=intent)

        took_ms = int((time.time() - start_time) * 1000)

        metadata = {
            "took_ms": took_ms,
            "constraint_explanations": constraints["explanations"],
            "normalization_steps": ["lowercase", "punctuation_removal", "whitespace_collapse", "synonym_canonicalization"]
        }

        search_query = SearchQuery(
            original_query=raw_query,
            normalized_query=normalized,
            text_term=cleaned,
            intent=intent,
            entities=entities,
            filters=constraints["filters"],
            numeric_filters=constraints.get("numeric_filters", []),
            modifiers=constraints.get("modifiers", []),
            recipe_quantities=constraints.get("recipe_quantities", []),
            ranking_preferences=constraints.get("ranking_preferences", {}),
            pagination={"size": size, "from": from_},
            metadata=metadata
        )

        return search_query
