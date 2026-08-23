import pytest

from models.search_document import SearchDocument
from retrieval.search_engine import SearchEngine, _is_brand_only


class CapturingRepository:
    """Probe repository that records the filters/numeric filters it receives."""

    def __init__(self):
        self.last_filters = None
        self.last_numeric_filters = None
        self.last_text = None

    def search(self, query, filters=None, numeric_filters=None, modifiers=None,
               size=20, from_=0, explain=False):
        self.last_text = query
        self.last_filters = filters or {}
        self.last_numeric_filters = numeric_filters or []
        doc = SearchDocument(
            id="1",
            product_name="Maple Syrup",
            search_text="Maple Syrup",
            semantic_document="Maple Syrup",
        )
        return 1, [(1.0, doc)], {}

    def get_by_id(self, doc_id):
        return None

    def get_autocomplete(self, query, size=5):
        return []


@pytest.fixture
def capturing_engine():
    repo = CapturingRepository()
    return SearchEngine(repository=repo), repo


def test_category_api_filter_maps_to_categories_entity(capturing_engine):
    engine, repo = capturing_engine
    engine.search("", filters={"category": "Maple syrups"}, size=5)
    assert repo.last_filters.get("category") == "Maple syrups", (
        "Category override must become a retrieval filter "
        "(regression: 'categorys' typo previously dropped it)"
    )


def test_brand_api_filter_maps_to_brands_entity(capturing_engine):
    engine, repo = capturing_engine
    engine.search("", filters={"brand": "Kroger"}, size=5)
    assert repo.last_filters.get("brand") == "Kroger"


def test_plain_string_query_has_no_override_filters(capturing_engine):
    engine, repo = capturing_engine
    engine.search("maple syrup", size=5)
    assert repo.last_filters == {}
    assert repo.last_text != ""


def test_non_entity_api_filters_pass_through(capturing_engine):
    engine, repo = capturing_engine
    engine.search("cookies", filters={"vegan": True}, size=5)
    assert repo.last_filters.get("is_vegan") is True


@pytest.fixture(scope="module", autouse=True)
def _load_dictionaries():
    import query.dictionaries as dictmod

    # Snapshot current dictionaries so we don't disturb other test modules
    # that seed BRANDS/CATEGORIES/INGREDIENTS at import time.
    snap = (set(dictmod.BRANDS), set(dictmod.CATEGORIES), set(dictmod.INGREDIENTS))
    from query.dictionaries import load_static_dictionaries

    load_static_dictionaries()
    yield
    dictmod.BRANDS.clear()
    dictmod.BRANDS.update(snap[0])
    dictmod.CATEGORIES.clear()
    dictmod.CATEGORIES.update(snap[1])
    dictmod.INGREDIENTS.clear()
    dictmod.INGREDIENTS.update(snap[2])


def test_generic_brand_product_promotes_brand_filter(capturing_engine):
    """D2 fix: 'Compliments soy sauce' under generic intent must become a brand filter
    plus the remaining product text, so Compliments soy sauces surface over lookalikes."""
    engine, repo = capturing_engine
    engine.search("Compliments soy sauce", size=5)
    assert repo.last_filters.get("brand") == "compliments"
    assert repo.last_text == "soy sauce"


def test_generic_brand_without_product_terms_stays_text(capturing_engine):
    """A single brand term with no remaining product text must NOT become a hard filter."""
    engine, repo = capturing_engine
    engine.search("Kroger", size=5)
    assert repo.last_filters.get("brand") is None
    assert repo.last_text != ""


def test_ambiguous_word_brand_is_not_promoted(capturing_engine):
    """'chips'/'soy' are brand-AND-category/ingredient terms; promoting them would
    wrongly hard-filter. They must stay lexical searches."""
    engine, repo = capturing_engine
    engine.search("chips", size=5)
    assert repo.last_filters.get("brand") is None

    engine.search("soy sauce", size=5)
    assert repo.last_filters.get("brand") is None


def test_brand_product_promotion_keeps_modifiers(capturing_engine):
    engine, repo = capturing_engine
    engine.search("Compliments frozen strawberries", size=5)
    assert repo.last_filters.get("brand") == "compliments"
    assert "frozen" in repo.last_text or "strawberries" in repo.last_text


def test_is_brand_only_guards_common_words():
    assert _is_brand_only("compliments") is True
    assert _is_brand_only("chips") is False  # also a category/ingredient word
