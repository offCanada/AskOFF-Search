import json

from builders.search_document_builder import SearchDocumentBuilder
from models.raw_product import RawProduct
from utils.off_parser import parse_nutriments

REALISTIC_JSON_NUTRIMENTS = json.dumps(
    {
        "energy": {"value": 400.0, "per_100g": 1600.0, "unit": "kcal"},
        "fat": {"value": 20.0, "per_100g": 20.0, "unit": "g"},
        "saturated-fat": {"value": 10.0, "per_100g": 10.0, "unit": "g"},
        "carbohydrates": {"value": 60.0, "per_100g": 60.0, "unit": "g"},
        "sugars": {"value": 4.0, "per_100g": 4.0, "unit": "g"},
        "fiber": {"value": 8.0, "per_100g": 8.0, "unit": "g"},
        "proteins": {"value": 25.0, "per_100g": 25.0, "unit": "g"},
        "salt": {"value": 0.1, "per_100g": 0.1, "unit": "g"},
        "sodium": {"value": 0.04, "per_100g": 0.04, "unit": "g"},
    }
)


class TestParseNutrimentsJson:
    def test_json_object_parses_to_non_empty_result(self):
        """REGRESSION: JSON-style parquet nutriments must not produce an empty object."""
        result = parse_nutriments(REALISTIC_JSON_NUTRIMENTS)
        assert result, "JSON nutriments must produce non-empty nutrition"
        assert result["sugars"]["per_100g"] == 4.0
        assert result["proteins"]["per_100g"] == 25.0
        assert result["sodium"]["per_100g"] == 0.04
        assert result["fat"]["per_100g"] == 20.0

    def test_energy_alias_added(self):
        result = parse_nutriments(REALISTIC_JSON_NUTRIMENTS)
        assert "energy" in result
        # alias so NUTRIENT_FIELD_MAP lookups (calories -> energy-kcal) work
        assert result["energy-kcal"]["per_100g"] == 1600.0

    def test_null_values_handled(self):
        raw = json.dumps(
            {
                "nova-group": {"value": None, "per_100g": 2.0, "unit": None},
                "sugars": {"value": 3.0, "per_100g": 3.0, "unit": "g"},
            }
        )
        result = parse_nutriments(raw)
        assert result["nova-group"]["value"] is None
        assert result["sugars"]["per_100g"] == 3.0

    def test_malformed_json_never_crashes(self):
        assert parse_nutriments("{not valid json") == {}
        assert parse_nutriments("") == {}
        assert parse_nutriments("[]") == {}
        assert parse_nutriments(None) == {}
        assert parse_nutriments(12345) == {}

    def test_dict_input_supported(self):
        result = parse_nutriments({"sugars": {"value": 5.0, "per_100g": 5.0, "unit": "g"}})
        assert result["sugars"]["per_100g"] == 5.0

    def test_legacy_list_style_still_parses(self):
        raw = "[{'name': 'energy', 'value': 333.0, '100g': 1393.0, 'unit': 'kcal'}]"
        result = parse_nutriments(raw)
        assert result["energy"]["per_100g"] == 1393.0

    def test_scalar_values_supported(self):
        raw = json.dumps(
            {"sugars": 12.0, "proteins": {"value": 8.0, "per_100g": 8.0, "unit": "g"}}
        )
        result = parse_nutriments(raw)
        assert result["sugars"]["value"] == 12.0
        assert result["sugars"]["per_100g"] == 12.0
        assert result["proteins"]["per_100g"] == 8.0


    def test_energy_kcal_to_energy_alias(self):
        raw = json.dumps({"energy-kcal": {"value": 250.0, "per_100g": 250.0, "unit": "kcal"}})
        result = parse_nutriments(raw)
        assert "energy-kcal" in result
        assert "energy" in result
        assert result["energy"]["per_100g"] == 250.0

    def test_sodium_and_salt_mutual_derivation(self):
        # When only sodium is present, salt should be derived
        raw_sodium_only = json.dumps({"sodium": {"value": 0.4, "per_100g": 0.4, "unit": "g"}})
        result1 = parse_nutriments(raw_sodium_only)
        assert "sodium" in result1
        assert "salt" in result1
        assert result1["salt"]["per_100g"] == 1.0

        # When only salt is present, sodium should be derived
        raw_salt_only = json.dumps({"salt": {"value": 2.5, "per_100g": 2.5, "unit": "g"}})
        result2 = parse_nutriments(raw_salt_only)
        assert "salt" in result2
        assert "sodium" in result2
        assert result2["sodium"]["per_100g"] == 1.0

    def test_flat_key_100g_parsing(self):
        raw = json.dumps({
            "proteins_100g": 18.5,
            "sugars_100g": 2.0,
            "energy-kcal_100g": 320.0
        })
        result = parse_nutriments(raw)
        assert result["proteins"]["per_100g"] == 18.5
        assert result["sugars"]["per_100g"] == 2.0
        assert result["energy-kcal"]["per_100g"] == 320.0
        assert result["energy"]["per_100g"] == 320.0


class TestSearchDocumentBuilderNutrition:
    def _build(self, nutriments: dict) -> RawProduct:
        raw = RawProduct(
            code="1000000000000",
            product_name="Test Cereal",
            brands="Test Brand",
            categories="Breakfast cereals",
            ingredients_text="oats, sugar",
            nutriments=nutriments,
            nutriscore_grade="c",
            nova_group=3,
            ecoscore_grade=None,
            completeness=100.0,
            search_text="Test Cereal breakfast cereals oats sugar",
        )
        return raw

    def test_json_nutriments_flow_into_document(self):
        parsed = parse_nutriments(REALISTIC_JSON_NUTRIMENTS)
        doc = SearchDocumentBuilder().build(self._build(parsed))
        attrs = doc.attributes or {}
        assert attrs["nutrition"]["sugars"]["per_100g"] == 4.0
        assert attrs["nutrition"]["proteins"]["per_100g"] == 25.0
        assert attrs["nutrition"]["energy-kcal"]["per_100g"] == 1600.0

    def test_flags_derived_from_json_nutrition(self):
        parsed = parse_nutriments(REALISTIC_JSON_NUTRIMENTS)
        doc = SearchDocumentBuilder().build(self._build(parsed))
        attrs = doc.attributes or {}
        assert attrs["flags"]["is_low_sugar"] is True
        assert attrs["flags"]["is_high_protein"] is True

    def test_flags_negative_case(self):
        high_sugar_json = json.dumps(
            {"sugars": {"value": 40.0, "per_100g": 40.0, "unit": "g"}}
        )
        doc = SearchDocumentBuilder().build(self._build(parse_nutriments(high_sugar_json)))
        attrs = doc.attributes or {}
        assert attrs["flags"]["is_low_sugar"] is False

    def test_missing_nutrients_do_not_set_threshold_flags(self):
        doc = SearchDocumentBuilder().build(self._build({}))
        attrs = doc.attributes or {}
        assert attrs["flags"]["is_low_sugar"] is False
        assert attrs["flags"]["is_high_protein"] is False
        assert attrs["flags"]["is_low_sodium"] is False

    def test_zero_sugar_low_sugar_flag(self):
        zero_sugar_json = json.dumps(
            {"sugars": {"value": 0.0, "per_100g": 0.0, "unit": "g"}}
        )
        doc = SearchDocumentBuilder().build(self._build(parse_nutriments(zero_sugar_json)))
        attrs = doc.attributes or {}
        assert attrs["flags"]["is_low_sugar"] is True

    def test_low_sodium_derived_flag_from_salt(self):
        # 0.25g salt -> 0.10g sodium <= 0.12 threshold -> is_low_sodium = True
        salt_json = json.dumps({"salt": {"value": 0.25, "per_100g": 0.25, "unit": "g"}})
        doc = SearchDocumentBuilder().build(self._build(parse_nutriments(salt_json)))
        attrs = doc.attributes or {}
        assert attrs["flags"]["is_low_sodium"] is True
