import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BRANDS = set()
CATEGORIES = set()
INGREDIENTS = set()

# Allergens and nutrition and sustainability are usually static sets
ALLERGENS = {
    "gluten", "lactose", "peanuts", "nuts", "soy", "eggs", "dairy", "milk", "wheat"
}

SUSTAINABILITY_LABELS = {
    "organic", "bio", "fair trade", "rainforest alliance", "non-gmo", "green"
}

NUTRITION = {
    "protein", "sugar", "sodium", "salt", "fat", "carbs", "carbohydrates", "energy", "calories"
}

STATIC_DICTIONARIES_PATH = Path(__file__).resolve().parents[1] / "data" / "dictionaries.json"


def load_static_dictionaries() -> bool:
    """Load pre-generated dictionaries from the static JSON file, if present."""
    if not STATIC_DICTIONARIES_PATH.exists():
        return False
    try:
        with open(STATIC_DICTIONARIES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        br = {str(b).lower() for b in data.get("brands", [])}
        ca = {str(c).lower() for c in data.get("categories", [])}
        ing = {str(i).lower() for i in data.get("ingredients", [])}
        BRANDS.clear()
        BRANDS.update(br)
        CATEGORIES.clear()
        CATEGORIES.update(ca)
        INGREDIENTS.clear()
        INGREDIENTS.update(ing)
        logger.info(
            "Loaded static dictionaries: %d brands, %d categories, %d ingredients",
            len(BRANDS), len(CATEGORIES), len(INGREDIENTS),
        )
        return True
    except Exception as e:
        logger.error("Failed to load static dictionaries from %s: %s", STATIC_DICTIONARIES_PATH, e)
        return False


def load_dynamic_dictionaries() -> bool:
    logger.info("Loading entity dictionaries...")
    if load_static_dictionaries():
        return True
    logger.info("Static dictionaries unavailable, falling back to OpenSearch aggregation...")
    try:
        from config.settings import settings
        from search.client import get_client

        client = get_client()
        if not client.indices.exists(index=settings.opensearch_index):
            logger.warning("Index does not exist. Cannot load dynamic dictionaries.")
            return False

        body = {
            "size": 0,
            "aggs": {
                "brands": {"terms": {"field": "brand.keyword", "size": 10000}},
                "categories": {"terms": {"field": "category.keyword", "size": 10000}},
                "ingredients": {"terms": {"field": "ingredients.keyword", "size": 10000}}
            }
        }
        res = client.search(index=settings.opensearch_index, body=body)

        aggs = res.get("aggregations", {})

        if "brands" in aggs:
            for b in aggs["brands"]["buckets"]:
                for part in b["key"].split(","):
                    if part.strip():
                        BRANDS.add(part.strip().lower())
        if "categories" in aggs:
            for c in aggs["categories"]["buckets"]:
                for part in c["key"].split(","):
                    if part.strip():
                        CATEGORIES.add(part.strip().lower())
        if "ingredients" in aggs:
            for i in aggs["ingredients"]["buckets"]:
                for part in i["key"].split(","):
                    if part.strip():
                        INGREDIENTS.add(part.strip().lower())

        logger.info(
            "Loaded %d brands, %d categories, %d ingredients.",
            len(BRANDS), len(CATEGORIES), len(INGREDIENTS),
        )
        return True
    except Exception as e:
        logger.error(f"Failed to load dynamic dictionaries: {e}")
        return False
