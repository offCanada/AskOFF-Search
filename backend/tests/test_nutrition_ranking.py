from query.pipeline import SearchQueryPipeline


class TestNutritionConstraintExtraction:
    def test_zero_sugar_distinct_from_low_sugar(self):
        sq_zero = SearchQueryPipeline.process("zero sugar chocolate")
        assert any(
            nf.get("nutrient") in {"sugar", "sugars"} and nf.get("value") <= 0.5
            for nf in sq_zero.numeric_filters
        )
        assert "chocolate" in sq_zero.text_term

        sq_low = SearchQueryPipeline.process("low sugar chocolate")
        assert sq_low.filters.get("low_sugar") is True

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
