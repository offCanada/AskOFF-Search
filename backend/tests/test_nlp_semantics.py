from query import dictionaries
from query.pipeline import SearchQueryPipeline

# Mock dictionaries so entity extraction works predictably for tests
dictionaries.BRANDS.update({"kirkland", "nature valley"})
dictionaries.CATEGORIES.update({"snacks", "cookies", "chips", "cereal", "chocolate", "meals"})
dictionaries.INGREDIENTS.update({"sugar", "peanut butter", "milk", "palm oil", "chocolate"})

def test_low_sugar_constraint_does_not_leak_into_text():
    sq = SearchQueryPipeline.process("low sugar peanut butter")
    assert sq.filters.get("low_sugar") is True
    assert "sugar" not in sq.text_term
    assert "low" not in sq.text_term
    assert "peanut butter" in sq.text_term

def test_high_protein_constraint_does_not_leak_into_text():
    sq = SearchQueryPipeline.process("high protein snacks")
    assert sq.filters.get("high_protein") is True
    assert "protein" not in sq.text_term
    assert "high" not in sq.text_term
    assert "snacks" in sq.text_term

def test_low_sodium_constraint_does_not_leak_into_text():
    sq = SearchQueryPipeline.process("low sodium chips")
    assert sq.filters.get("low_sodium") is True
    assert "sodium" not in sq.text_term
    assert "low" not in sq.text_term
    assert "chips" in sq.text_term

def test_gluten_free_constraint_does_not_leak_into_text():
    sq = SearchQueryPipeline.process("gluten free cookies")
    assert sq.filters.get("gluten_free") is True
    assert "gluten" not in sq.text_term
    assert "free" not in sq.text_term
    assert "cookies" in sq.text_term

def test_palm_oil_free_constraint_does_not_leak_into_text():
    sq = SearchQueryPipeline.process("palm oil free peanut butter")
    assert sq.filters.get("palm_oil") is False
    assert "palm" not in sq.text_term
    assert "oil" not in sq.text_term
    assert "free" not in sq.text_term
    assert "peanut butter" in sq.text_term

def test_vegan_constraint_does_not_leak_into_text():
    sq = SearchQueryPipeline.process("vegan chocolate")
    assert sq.filters.get("vegan") is True
    assert "vegan" not in sq.text_term
    assert "chocolate" in sq.text_term

def test_plain_sugar_query_remains_sugar():
    sq = SearchQueryPipeline.process("sugar")
    assert sq.text_term == "sugar"
    assert sq.filters.get("low_sugar") is None

def test_sugar_cookie_query_remains_valid():
    sq = SearchQueryPipeline.process("sugar cookies")
    assert "sugar" in sq.text_term
    assert "cookies" in sq.text_term
    assert sq.filters.get("low_sugar") is None

def test_explicit_brand_query_filters_brand():
    sq = SearchQueryPipeline.process("by brand kirkland")
    assert sq.intent == "brand_search"
    assert len(sq.entities.get("brands", [])) > 0
    assert sq.entities["brands"][0]["value"] == "kirkland"

def test_general_brand_query_does_not_overfilter():
    sq = SearchQueryPipeline.process("kirkland peanut butter")
    assert sq.intent == "generic_search"
    assert len(sq.entities.get("brands", [])) > 0
    assert sq.entities["brands"][0]["value"] == "kirkland"
    assert "kirkland" in sq.text_term
    # In SearchEngine, because intent is generic_search, it will NOT become a MUST filter,
    # but the pipeline should still extract it as an entity.

def test_numeric_constraint_extraction():
    sq = SearchQueryPipeline.process("snacks under 200 calories")
    assert "snacks" in sq.text_term
    assert "under 200" not in sq.text_term

    assert len(sq.numeric_filters) == 1
    nf = sq.numeric_filters[0]
    assert nf["nutrient"] == "calories"
    assert nf["operator"] == "lte"
    assert nf["value"] == 200.0
    assert nf["unit"] == "calories"
    assert nf["comparison_basis"] == "per_100g"

def test_modifier_extraction():
    sq = SearchQueryPipeline.process("fresh organic milk")
    assert sq.filters.get("organic") is True
    assert "fresh" in sq.modifiers
    # modifier should remain in text_term to boost phrase match
    assert "fresh" in sq.text_term

def test_multi_word_phrase_without_compound_protection():
    sq = SearchQueryPipeline.process("protein bar")
    assert sq.intent == "generic_search"
    # Even if "protein" and "bar" are extracted as entities,
    # the entire text_term should still contain them for exact phrase matching.
    assert "protein" in sq.text_term
    assert "bar" in sq.text_term

def test_recipe_quantity_extraction_blueberries():
    sq = SearchQueryPipeline.process("500 mL (2 cups) frozen blueberries")
    assert sq.text_term == "frozen blueberries"
    assert "frozen" in sq.modifiers
    assert len(sq.recipe_quantities) == 2
    assert sq.recipe_quantities[0]["value"] == 500.0
    assert sq.recipe_quantities[0]["unit"] == "ml"
    assert sq.recipe_quantities[1]["value"] == 2.0
    assert sq.recipe_quantities[1]["unit"] == "cups"

def test_recipe_quantity_extraction_butter():
    sq = SearchQueryPipeline.process("2 tbsp salted butter")
    assert sq.text_term == "salted butter"
    assert "salted" in sq.modifiers
    assert len(sq.recipe_quantities) == 1
    assert sq.recipe_quantities[0]["value"] == 2.0
    assert sq.recipe_quantities[0]["unit"] == "tbsp"

def test_recipe_quantity_extraction_oats():
    sq = SearchQueryPipeline.process("1 cup rolled oats")
    assert sq.text_term == "rolled oats"
    assert len(sq.recipe_quantities) == 1
    assert sq.recipe_quantities[0]["value"] == 1.0
    assert sq.recipe_quantities[0]["unit"] == "cup"

def test_recipe_quantity_extraction_tomatoes():
    sq = SearchQueryPipeline.process("250g fresh tomatoes")
    assert sq.text_term == "fresh tomatoes"
    assert "fresh" in sq.modifiers
    assert len(sq.recipe_quantities) == 1
    assert sq.recipe_quantities[0]["value"] == 250.0
    assert sq.recipe_quantities[0]["unit"] == "g"

def test_food_with_number_is_preserved():
    sq = SearchQueryPipeline.process("2% milk")
    assert "2% milk" in sq.text_term
    assert len(sq.recipe_quantities) == 0


def test_numeric_operator_and_mg_unit_are_normalized_for_per_100g_filtering():
    sq = SearchQueryPipeline.process("sodium <= 120mg soup")
    assert sq.text_term == "soup"
    assert sq.numeric_filters == [{
        "nutrient": "sodium",
        "operator": "lte",
        "value": 0.12,
        "unit": "g",
        "comparison_basis": "per_100g",
    }]


def test_strict_numeric_operator_is_preserved():
    sq = SearchQueryPipeline.process("protein > 20g bars")
    assert sq.text_term == "bars"
    assert sq.numeric_filters[0]["operator"] == "gt"
    assert sq.numeric_filters[0]["value"] == 20.0


def test_incompatible_nutrition_unit_is_not_converted_into_a_filter():
    sq = SearchQueryPipeline.process("under 20g calories cookies")
    assert sq.numeric_filters == []
    assert "20g calories" in sq.text_term


