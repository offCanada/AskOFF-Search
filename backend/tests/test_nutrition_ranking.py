from query.pipeline import SearchQueryPipeline


class TestNutritionConstraintExtraction:
    def test_zero_sugar_distinct_from_low_sugar(self):
        sq_zero = SearchQueryPipeline.process("zero sugar chocolate")
        assert any(
            nf.get("nutrient") in {"sugar", "sugars"} and nf.get("value") <= 0.5
            for nf in sq_zero.numeric_filters
        )
        assert sq_zero.filters.get("low_sugar") is None  # Does NOT pollute boolean filter
        assert "chocolate" in sq_zero.text_term

        sq_free = SearchQueryPipeline.process("sugar-free chocolate")
        assert any(
            nf.get("nutrient") in {"sugar", "sugars"} and nf.get("value") <= 0.5
            for nf in sq_free.numeric_filters
        )

        sq_low = SearchQueryPipeline.process("low sugar chocolate")
        assert sq_low.filters.get("low_sugar") is True
        assert not any(nf.get("is_zero_constraint") for nf in sq_low.numeric_filters)

    def test_zero_sugar_vs_low_sugar_filtering_behavior(self):
        from typing import List, Optional, Tuple

        from models.search_document import SearchDocument
        from retrieval.repository import SearchRepository
        from retrieval.search_engine import SearchEngine

        # Mock documents with varying sugar levels
        docs = [
            SearchDocument(id="1", dataset_id="off", product_name="Pure Dark Zero", search_text="Pure Dark Zero", semantic_document="Product: Pure Dark Zero", attributes={"nutrition": {"sugars": {"per_100g": 0.0}}, "flags": {"is_low_sugar": True}}),
            SearchDocument(id="2", dataset_id="off", product_name="Raspberry Dark Zero", search_text="Raspberry Dark Zero", semantic_document="Product: Raspberry Dark Zero", attributes={"nutrition": {"sugars": {"per_100g": 0.4}}, "flags": {"is_low_sugar": True}}),
            SearchDocument(id="3", dataset_id="off", product_name="Low Sugar Milk Bar", search_text="Low Sugar Milk Bar", semantic_document="Product: Low Sugar Milk Bar", attributes={"nutrition": {"sugars": {"per_100g": 3.2}}, "flags": {"is_low_sugar": True}}),
            SearchDocument(id="4", dataset_id="off", product_name="Reduced Sugar Chocolate", search_text="Reduced Sugar Chocolate", semantic_document="Product: Reduced Sugar Chocolate", attributes={"nutrition": {"sugars": {"per_100g": 4.9}}, "flags": {"is_low_sugar": True}}),
            SearchDocument(id="5", dataset_id="off", product_name="Standard Sweet Chocolate", search_text="Standard Sweet Chocolate", semantic_document="Product: Standard Sweet Chocolate", attributes={"nutrition": {"sugars": {"per_100g": 45.0}}, "flags": {"is_low_sugar": False}}),
        ]

        class MockRepo(SearchRepository):
            def search(self, query: str, filters: Optional[dict] = None, numeric_filters: Optional[List[dict]] = None, modifiers: Optional[List[str]] = None, ranking_preferences: Optional[dict] = None, size: int = 20, from_: int = 0, explain: bool = False) -> Tuple[int, List[Tuple[float, SearchDocument]], dict]:
                matched = []
                for d in docs:
                    sugar = d.attributes.get("nutrition", {}).get("sugars", {}).get("per_100g", 999.0)
                    if filters and filters.get("is_low_sugar") and not d.attributes.get("flags", {}).get("is_low_sugar"):
                        continue
                    if numeric_filters:
                        viol = False
                        for nf in numeric_filters:
                            if nf.get("nutrient") in {"sugar", "sugars"} and nf.get("operator") == "lte":
                                if sugar > nf.get("value", 0.5):
                                    viol = True
                        if viol:
                            continue
                    matched.append((1.0, d))
                return len(matched), matched, {}

            def get_by_id(self, doc_id: str) -> Optional[SearchDocument]:
                return None
            def get_autocomplete(self, query: str, size: int = 5) -> List[str]:
                return []

        engine = SearchEngine(repository=MockRepo())

        # 1. Zero sugar search: MUST only return products <= 0.5g sugar
        res_zero = engine.search("zero sugar chocolate")
        zero_sugars = [
            h.product.attributes["nutrition"]["sugars"]["per_100g"]
            for h in res_zero.hits
        ]
        assert len(zero_sugars) == 2
        assert all(s <= 0.5 for s in zero_sugars), f"Violation in zero sugar: {zero_sugars}"

        # 2. Low sugar search: May return products up to 5.0g sugar
        res_low = engine.search("low sugar chocolate")
        low_sugars = [
            h.product.attributes["nutrition"]["sugars"]["per_100g"]
            for h in res_low.hits
        ]
        assert len(low_sugars) == 4
        assert any(s > 0.5 for s in low_sugars), "Low sugar should include products > 0.5g and <= 5.0g"
        assert all(s <= 5.0 for s in low_sugars), f"Violation in low sugar: {low_sugars}"

    def test_numeric_operator_synonyms(self):
        # below / under
        sq1 = SearchQueryPipeline.process("drinks below 300 kcal")
        assert any(nf.get("nutrient") in {"calories", "kcal", "energy"} and nf.get("operator") == "lt" and nf.get("value") == 300.0 for nf in sq1.numeric_filters)

        # <= operator
        sq2 = SearchQueryPipeline.process("drinks <= 300 kcal")
        assert any(nf.get("nutrient") in {"calories", "kcal", "energy"} and nf.get("operator") == "lte" and nf.get("value") == 300.0 for nf in sq2.numeric_filters)

        # above / over
        sq3 = SearchQueryPipeline.process("snacks above 15g protein")
        assert any(nf.get("nutrient") in {"protein", "proteins"} and nf.get("operator") == "gt" and nf.get("value") == 15.0 for nf in sq3.numeric_filters)

        # at least
        sq4 = SearchQueryPipeline.process("snacks with at least 20g protein")
        assert any(nf.get("nutrient") in {"protein", "proteins"} and nf.get("operator") == "gte" and nf.get("value") == 20.0 for nf in sq4.numeric_filters)

    def test_multi_constraint_conjunction(self):
        sq = SearchQueryPipeline.process("zero sugar high protein bar")
        assert any(nf.get("nutrient") in {"sugar", "sugars"} and nf.get("value") <= 0.5 for nf in sq.numeric_filters)
        assert sq.filters.get("high_protein") is True
        assert "bar" in sq.text_term

    def test_directional_ranking_preference_extraction(self):
        sq_sugar = SearchQueryPipeline.process("lowest sugar chocolate")
        assert sq_sugar.ranking_preferences.get("sort_nutrient") == "sugars"
        assert sq_sugar.ranking_preferences.get("order") == "asc"
        assert "chocolate" in sq_sugar.text_term

        sq_protein = SearchQueryPipeline.process("highest protein snacks")
        assert sq_protein.ranking_preferences.get("sort_nutrient") == "proteins"
        assert sq_protein.ranking_preferences.get("order") == "desc"
        assert "snacks" in sq_protein.text_term

        sq_cals = SearchQueryPipeline.process("lowest calorie drinks")
        assert sq_cals.ranking_preferences.get("sort_nutrient") == "energy-kcal"
        assert sq_cals.ranking_preferences.get("order") == "asc"
        assert "drinks" in sq_cals.text_term

    def test_typo_resilience_in_nutrition_constraints(self):
        sq_prot = SearchQueryPipeline.process("high protien snacks")
        assert sq_prot.filters.get("high_protein") is True
        assert "snacks" in sq_prot.text_term

        sq_sug = SearchQueryPipeline.process("zero sugur chocolate")
        assert any(nf.get("nutrient") in {"sugar", "sugars"} and nf.get("value") <= 0.5 for nf in sq_sug.numeric_filters)
        assert "chocolate" in sq_sug.text_term
