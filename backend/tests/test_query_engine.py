from query import dictionaries
from query.constraint_extractor import ConstraintExtractor
from query.entity_extractor import EntityExtractor
from query.intent_detector import IntentDetector
from query.normalizer import QueryNormalizer
from query.pipeline import SearchQueryPipeline
from query.search_query import SearchQuery
from query.tokenizer import QueryTokenizer

# Populate dictionaries for tests since they are now dynamically loaded
dictionaries.BRANDS.update({
    "kirkland", "silk almond", "nature honey", "ferrero", "butternut mountain farm", "nestle",
    "kellogg", "kraft", "cadbury", "hershey", "quaker", "butternut", "farm", "farmhouse"
})

dictionaries.CATEGORIES.update({
    "honey", "milk substitutes", "beverages", "sweeteners", "syrups", "cereal", "snacks",
    "chocolate", "yogurt", "maple syrup", "milk", "almond milk", "sweetener", "syrup"
})

dictionaries.INGREDIENTS.update({
    "honey", "almond", "water", "sugar", "cocoa", "salt", "milk", "oats", "wheat", "peanuts",
    "maple syrup", "palm oil", "calcium carbonate", "sea salt"
})


class TestTokenizer:
    def test_tokenize_splits_words(self):
        tokens = QueryTokenizer.tokenize("organic maple syrup")
        assert tokens == ["organic", "maple", "syrup"]

    def test_tokenize_empty_query(self):
        assert QueryTokenizer.tokenize("") == []

    def test_generate_ngrams_creates_combinations(self):
        tokens = ["organic", "maple", "syrup"]
        ngrams = QueryTokenizer.generate_ngrams(tokens, max_n=3)
        assert "organic" in ngrams
        assert "organic maple" in ngrams
        assert "maple syrup" in ngrams
        assert "organic maple syrup" in ngrams
        # Check order is length descending
        assert ngrams[0] == "organic maple syrup"


class TestNormalizer:
    def test_normalize_strips_punctuation_and_lowercases(self):
        res = QueryNormalizer.normalize("  Kirkland, Maple Syrup! (Organic?)  ")
        assert res == "kirkland maple syrup organic"

    def test_normalize_preserves_hyphens(self):
        res = QueryNormalizer.normalize("Gluten-Free, Sugar-Free!")
        assert res == "gluten-free sugar-free"

    def test_normalize_pure_punctuation_behavior(self):
        res = QueryNormalizer.normalize("!@#$^&*()+{}[]|:;'\"?,/")
        assert res == ""

    def test_normalize_empty_and_whitespace(self):
        assert QueryNormalizer.normalize("") == ""
        assert QueryNormalizer.normalize("     ") == ""


class TestIntentDetector:
    def test_detect_brand_intent(self):
        assert IntentDetector.detect("by brand kirkland") == "brand_search"
        assert IntentDetector.detect("brands available") == "brand_search"

    def test_detect_category_intent(self):
        assert IntentDetector.detect("under category sweeteners") == "category_browse"

    def test_detect_generic_intent(self):
        assert IntentDetector.detect("sweet honey") == "generic_search"


class TestEntityExtractor:
    def test_extract_simple_entities(self):
        entities = EntityExtractor.extract("kirkland honey")
        assert len(entities["brands"]) == 1
        assert entities["brands"][0]["value"] == "kirkland"
        assert "brands lookup dictionary" in entities["brands"][0]["explanation"]

        assert len(entities["categories"]) == 1
        assert entities["categories"][0]["value"] == "honey"

    def test_extract_multiword_prevents_overlap(self):
        # "silk almond" is a multiword brand in dictionaries, "almond" is an ingredient.
        # It should match "silk almond" as a brand but NOT "almond" as ingredient.
        entities = EntityExtractor.extract("silk almond milk")
        assert len(entities["brands"]) == 1
        assert entities["brands"][0]["value"] == "silk almond"
        assert len(entities["ingredients"]) == 0 # blocked by overlap mapping

    def test_extract_countries(self):
        entities = EntityExtractor.extract("maple syrup from vermont")
        assert len(entities["countries"]) == 1
        assert entities["countries"][0]["value"] == "vermont"


class TestConstraintExtractor:
    def test_extract_all_constraints(self):
        query = (
            "organic vegan vegetarian palm oil free high protein sugar free "
            "low salt gluten free lactose free"
        )
        res = ConstraintExtractor.extract(query)
        filters = res["filters"]

        assert filters["organic"] is True
        assert filters["vegan"] is True
        assert filters["vegetarian"] is True
        assert filters["palm_oil"] is False
        assert filters["high_protein"] is True
        assert filters["low_sugar"] is True
        assert filters["low_sodium"] is True
        assert filters["gluten_free"] is True
        assert filters["lactose_free"] is True

        # Verify explanations trace
        exps = res["explanations"]
        assert len(exps) == 9
        assert exps[0]["field"] == "organic"

    def test_extract_conflicting_constraints_safe(self):
        query = "vegan with palm oil"
        res = ConstraintExtractor.extract(query)
        assert res["filters"]["vegan"] is True
        assert res["filters"]["palm_oil"] is True


class TestSearchQueryPipeline:
    def test_pipeline_orchestrates_full_flow(self):
        q = "organic sugar-free syrup from butternut mountain farm"
        sq = SearchQueryPipeline.process(q)

        assert isinstance(sq, SearchQuery)
        assert sq.original_query == q
        assert sq.normalized_query == "organic sugar-free syrup from butternut mountain farm"
        assert sq.filters["organic"] is True
        assert sq.filters["low_sugar"] is True

        # Check brand entity extracted
        assert len(sq.entities["brands"]) == 1
        assert sq.entities["brands"][0]["value"] == "butternut mountain farm"

        # Metadata check
        assert sq.metadata["took_ms"] >= 0
        assert len(sq.metadata["constraint_explanations"]) == 2

    def test_pipeline_handles_empty_query(self):
        sq = SearchQueryPipeline.process("")
        assert sq.original_query == ""
        assert sq.text_term == ""
        assert sq.intent == "generic_search"

