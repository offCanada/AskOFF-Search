from models.raw_product import RawProduct
from models.search_document import SearchDocument


class SearchDocumentBuilder:
    @staticmethod
    def build(raw: RawProduct) -> SearchDocument:
        nutrition_dict = raw.nutriments or {}

        categories_lower = raw.categories.lower()
        ingredients_lower = raw.ingredients_text.lower()

        is_organic = (
            "organic" in categories_lower
            or "organic" in ingredients_lower
            or "bio" in categories_lower
            or "bio" in ingredients_lower
        )
        is_vegan = "vegan" in categories_lower or "vegan" in ingredients_lower
        is_vegetarian = "vegetarian" in categories_lower or "vegetarian" in ingredients_lower or is_vegan

        is_palm_oil_free = "palm oil" not in ingredients_lower

        def get_nutrient_per_100g(key: str) -> float:
            val = nutrition_dict.get(key)
            if isinstance(val, dict):
                p = val.get("per_100g")
                if p is not None:
                    return float(p)
            return -1.0

        proteins_100g = get_nutrient_per_100g("proteins")
        sugars_100g = get_nutrient_per_100g("sugars")
        sodium_100g = get_nutrient_per_100g("sodium")

        is_high_protein = "high protein" in categories_lower or (proteins_100g >= 10.0)
        is_low_sugar = "low sugar" in categories_lower or "sugar free" in categories_lower or "no sugar" in categories_lower or (0 <= sugars_100g <= 5.0)
        is_low_sodium = "low sodium" in categories_lower or "low salt" in categories_lower or (0 <= sodium_100g <= 0.12)
        is_gluten_free = "gluten free" in categories_lower or "gluten-free" in categories_lower or "sans gluten" in categories_lower
        is_lactose_free = "lactose free" in categories_lower or "dairy free" in categories_lower or "sans lactose" in categories_lower

        attributes = {
            "nutrition": nutrition_dict,
            "flags": {
                "is_organic": is_organic,
                "is_vegan": is_vegan,
                "is_vegetarian": is_vegetarian,
                "is_palm_oil_free": is_palm_oil_free,
                "is_high_protein": is_high_protein,
                "is_low_sugar": is_low_sugar,
                "is_low_sodium": is_low_sodium,
                "is_gluten_free": is_gluten_free,
                "is_lactose_free": is_lactose_free
            }
        }

        metadata = {
            "nutriscore_grade": raw.nutriscore_grade,
            "nova_group": raw.nova_group,
            "ecoscore_grade": raw.ecoscore_grade,
            "completeness": raw.completeness,
            "image_url": getattr(raw, "image_url", None),
            "front_image_url": getattr(raw, "image_url", None),
        }

        parts = [
            p
            for p in [
                raw.product_name,
                raw.brands,
                raw.categories,
                raw.ingredients_text,
            ]
            if p
        ]
        search_text = " ".join(parts)

        sem_parts = []
        if raw.product_name:
            sem_parts.append(f"Product: {raw.product_name}")
        if raw.brands:
            sem_parts.append(f"Brand: {raw.brands}")
        if raw.categories:
            sem_parts.append(f"Category: {raw.categories}")
        if raw.ingredients_text:
            sem_parts.append(f"Ingredients:\n{raw.ingredients_text}")
        semantic_document = "\n\n".join(sem_parts)

        return SearchDocument(
            id=raw.code,
            dataset_id="openfoodfacts",
            core_product_id=None,
            variant_id=None,
            product_name=raw.product_name,
            brand=raw.brands if raw.brands else None,
            category=raw.categories if raw.categories else None,
            ingredients=raw.ingredients_text if raw.ingredients_text else None,
            attributes=attributes,
            metadata=metadata,
            search_text=search_text,
            semantic_document=semantic_document
        )
