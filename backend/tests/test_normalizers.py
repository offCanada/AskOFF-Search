from adapters.off_adapter import (
    parse_ingredients_text,
    parse_nutriments,
    parse_product_name,
)
from builders.search_document_builder import SearchDocumentBuilder
from models.raw_product import RawProduct


class TestOFFAdapterParsing:
    def test_parses_multilingual_name_with_escaped_quotes(self, sample_raw_product_name):
        text = parse_product_name(sample_raw_product_name)
        assert text == "Organic Vermont Maple Syrup"

    def test_parses_multilingual_ingredients(self, sample_raw_ingredients):
        text = parse_ingredients_text(sample_raw_ingredients)
        assert text == "Pure organic maple syrup"

    def test_parses_native_struct_multilingual_fields(self):
        struct_name = [
            {"lang": "fr", "text": "Sirop d'érable pur"},
            {"lang": "en", "text": "Pure Maple Syrup"},
        ]
        assert parse_product_name(struct_name) == "Pure Maple Syrup"

    def test_parses_native_struct_nutriments(self):
        struct_nutriments = [
            {"name": "proteins", "value": None, "100g": 12.5, "unit": "g"},
            {"name": "sugars", "value": 2.0, "100g": 0.4, "unit": "g"},
        ]
        result = parse_nutriments(struct_nutriments)
        assert "proteins" in result
        assert result["proteins"]["per_100g"] == 12.5
        assert result["sugars"]["per_100g"] == 0.4

    def test_parses_nutriments_with_values(self, sample_raw_nutriments):
        result = parse_nutriments(sample_raw_nutriments)
        assert "energy" in result
        assert result["energy"]["value"] == 333.0
        assert result["energy"]["per_100g"] == 1393.0
        assert result["energy"]["unit"] == "kcal"

    def test_handles_empty_fields(self):
        assert parse_product_name("") == ""
        assert parse_ingredients_text("[]") == ""
        assert parse_nutriments("") == {}

    def test_extract_off_image_url_direct_and_derived(self):
        from utils.off_parser import extract_off_image_url

        # Direct valid URL
        direct = "https://images.openfoodfacts.org/images/products/0008577002786/1.jpg"
        assert extract_off_image_url("0008577002786", front_image_url=direct) == direct

        # Derived from front_en imgid
        imgs = [
            {"key": "1", "imgid": None},
            {"key": "front_en", "imgid": 25},
        ]
        url = extract_off_image_url("0009800800056", front_image_url=None, images_raw=imgs)
        assert url == "https://images.openfoodfacts.org/images/products/0009800800056/25.jpg"

        # Derived from fallback key '1'
        imgs_fallback = [{"key": "1", "imgid": None}]
        url_fb = extract_off_image_url("0011110020758", front_image_url=None, images_raw=imgs_fallback)
        assert url_fb == "https://images.openfoodfacts.org/images/products/0011110020758/1.jpg"

        # Missing images returns None
        assert extract_off_image_url("123", front_image_url=None, images_raw=None) is None


class TestSearchDocumentBuilder:
    def test_builder_maps_fields_and_computes_flags(self):
        raw = RawProduct(
            code="12345",
            product_name="Bio Organic Granola",
            brands="Whole Foods",
            categories="Breakfast cereals, Granola",
            ingredients_text="Organic rolled oats, organic sugar, almonds, vegan cocoa",
            nutriments={
                "energy": {"value": 450.0, "per_100g": 450.0, "unit": "kcal"},
                "fat": {"value": 15.0, "per_100g": 15.0, "unit": "g"},
            },
            nutriscore_grade="a",
            nova_group=3,
            ecoscore_grade="b",
            completeness=0.88,
            image_url="https://images.openfoodfacts.org/images/products/12345/1.jpg",
        )

        doc = SearchDocumentBuilder.build(raw)

        # Basic properties
        assert doc.id == "12345"
        assert doc.product_name == "Bio Organic Granola"
        assert doc.brand == "Whole Foods"
        assert doc.category == "Breakfast cereals, Granola"
        assert doc.ingredients == "Organic rolled oats, organic sugar, almonds, vegan cocoa"

        # Nutrition dict
        assert doc.attributes["nutrition"]["energy"]["value"] == 450.0
        assert doc.attributes["nutrition"]["fat"]["value"] == 15.0
        assert "saturates" not in doc.attributes["nutrition"]

        # Flags auto-derived by builder
        assert doc.attributes["flags"]["is_organic"] is True
        assert doc.attributes["flags"]["is_vegan"] is True
        assert doc.attributes["flags"]["is_vegetarian"] is True

        # Metadata map & image URLs
        assert doc.metadata["nutriscore_grade"] == "a"
        assert doc.metadata["nova_group"] == 3
        assert doc.metadata["completeness"] == 0.88
        assert doc.metadata["image_url"] == "https://images.openfoodfacts.org/images/products/12345/1.jpg"
        assert doc.metadata["front_image_url"] == "https://images.openfoodfacts.org/images/products/12345/1.jpg"

        # Text concatenation
        assert "Bio Organic Granola" in doc.search_text
        assert "Whole Foods" in doc.search_text
        assert "Ingredients:\nOrganic rolled oats" in doc.semantic_document


