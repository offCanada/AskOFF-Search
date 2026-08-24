import json
import logging
import math
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def parse_multilingual_field(raw: Any) -> list[dict[str, str]]:
    if not raw or raw == "[]":
        return []

    if isinstance(raw, list):
        results = []
        for item in raw:
            if isinstance(item, dict):
                lang = item.get("lang") or "main"
                text = item.get("text")
                if text:
                    results.append({"lang": str(lang), "text": str(text).strip()})
        return results

    if not isinstance(raw, str):
        return []

    blocks = re.findall(r'\{([^{}]+)\}', raw)
    results = []
    for block in blocks:
        lang_match = re.search(r"['\"]lang['\"]\s*:\s*['\"]([^'\"]*)['\"]", block)
        text_match = re.search(r"['\"]text['\"]\s*:\s*(['\"])(.*?)\1\s*(?:,|$)", block, re.DOTALL)
        if not text_match:
            text_match = re.search(r"['\"]text['\"]\s*:\s*'(.*)'\s*$", block, re.DOTALL)
            if not text_match:
                text_match = re.search(r"['\"]text['\"]\s*:\s*\"(.*)\"\s*$", block, re.DOTALL)

        if lang_match and text_match:
            results.append({
                "lang": lang_match.group(1),
                "text": text_match.group(2).strip()
            })

    if not results and raw.strip() and not raw.startswith("["):
        results.append({"lang": "main", "text": raw.strip()})

    return results


def sanitize_product_text(text: str) -> str:
    """
    Sanitize literal unescaped/escaped newlines, carriage returns, tabs, and duplicate spaces.
    Preserves legitimate text content without altering product names unnecessarily.
    Example: 'cake\\ncake' or 'cake\\ncake' -> 'cake cake'.
    """
    if not text or not isinstance(text, str):
        return ""
    t = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    t = t.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", t).strip()


def extract_text_by_language(
    entries: list[dict[str, str]],
    preferred_langs: tuple[str, ...] = ("en", "main", "fr"),
) -> str:
    if not entries:
        return ""
    for pref in preferred_langs:
        for entry in entries:
            if isinstance(entry, dict) and entry.get("lang") == pref:
                text = entry.get("text", "")
                if text:
                    return sanitize_product_text(text)
    for entry in entries:
        if isinstance(entry, dict):
            text = entry.get("text", "")
            if text:
                return sanitize_product_text(text)
    return ""


def parse_product_name(raw: Any) -> str:
    if not raw or raw == "[]":
        return ""
    entries = parse_multilingual_field(raw)
    extracted = extract_text_by_language(entries)
    if not extracted and isinstance(raw, str) and raw != "[]":
        extracted = raw
    return sanitize_product_text(extracted)


def parse_ingredients_text(raw: Any) -> str:
    if not raw or raw == "[]":
        return ""
    entries = parse_multilingual_field(raw)
    extracted = extract_text_by_language(entries)
    if not extracted and isinstance(raw, str) and raw != "[]":
        extracted = raw
    return sanitize_product_text(extracted)


def _coerce_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _normalize_nutriment_object(obj: dict) -> dict[str, dict]:
    """Normalize a JSON-style nutriment object into {name: {value, per_100g, unit}}."""
    result = {}
    for name, entry in obj.items():
        if not isinstance(name, str):
            continue
        if isinstance(entry, dict):
            value = _coerce_float(entry.get("value"))
            per_100g = _coerce_float(entry.get("per_100g", entry.get("100g")))
            unit = entry.get("unit")
            if unit is not None and not isinstance(unit, str):
                unit = str(unit) if not isinstance(unit, float) or not math.isnan(unit) else None
        elif isinstance(entry, (int, float)) and not isinstance(entry, bool):
            value = _coerce_float(entry)
            per_100g = value
            unit = None
        else:
            continue
        result[name] = {
            "value": value,
            "per_100g": per_100g,
            "unit": unit if isinstance(unit, str) and unit else None,
        }

    # Handle flat key patterns like 'proteins_100g', 'sugars_100g', 'energy-kcal_100g'
    for name, entry in list(obj.items()):
        if isinstance(name, str) and name.endswith("_100g"):
            base_name = name[:-5]
            if base_name and base_name not in result:
                val = _coerce_float(entry)
                if val is not None:
                    result[base_name] = {
                        "value": val,
                        "per_100g": val,
                        "unit": None,
                    }

    # Bidirectional alias for energy <-> energy-kcal so all downstream lookups work
    if "energy" in result and "energy-kcal" not in result:
        result["energy-kcal"] = result["energy"]
    elif "energy-kcal" in result and "energy" not in result:
        result["energy"] = result["energy-kcal"]

    # Mutual derivation for sodium <-> salt (salt ~= sodium * 2.5) if one is missing
    if "sodium" in result and "salt" not in result:
        s_entry = result["sodium"]
        if s_entry.get("per_100g") is not None:
            result["salt"] = {
                "value": s_entry["value"] * 2.5 if s_entry.get("value") is not None else None,
                "per_100g": s_entry["per_100g"] * 2.5,
                "unit": s_entry.get("unit") or "g",
            }
    elif "salt" in result and "sodium" not in result:
        s_entry = result["salt"]
        if s_entry.get("per_100g") is not None:
            result["sodium"] = {
                "value": s_entry["value"] / 2.5 if s_entry.get("value") is not None else None,
                "per_100g": s_entry["per_100g"] / 2.5,
                "unit": s_entry.get("unit") or "g",
            }

    return result


def _parse_nutriments_list_style(raw: str) -> dict[str, dict]:
    """Parse the OFF CSV-export list-of-dicts style (legacy format)."""
    blocks = re.findall(r'\{([^{}]+)\}', raw)
    result = {}
    for block in blocks:
        name_match = re.search(r"['\"]name['\"]\s*:\s*['\"]([^'\"]*)['\"]", block)
        if not name_match:
            continue
        name = name_match.group(1)

        value_match = re.search(r"['\"]value['\"]\s*:\s*([^\s,}]+)", block)
        value = None
        if value_match:
            val_str = value_match.group(1).strip("'\"")
            if val_str.lower() not in ('nan', 'none', 'null'):
                try:
                    value = float(val_str)
                except ValueError:
                    pass

        per_100g_match = re.search(r"['\"]100g['\"]\s*:\s*([^\s,}]+)", block)
        per_100g = None
        if per_100g_match:
            val_str = per_100g_match.group(1).strip("'\"")
            if val_str.lower() not in ('nan', 'none', 'null'):
                try:
                    per_100g = float(val_str)
                except ValueError:
                    pass

        unit_match = re.search(r"['\"]unit['\"]\s*:\s*['\"]([^'\"]*)['\"]", block)
        unit = None
        if unit_match:
            unit = unit_match.group(1)

        result[name] = {
            "value": value,
            "per_100g": per_100g,
            "unit": unit
        }
    return result


def parse_nutriments(raw: Any) -> dict[str, dict]:
    """
    Parse a nutriments field into {name: {"value", "per_100g", "unit"}}.

    Supports:
    - JSON-style objects:  {"energy": {"value": 333.0, "per_100g": 1393.0, "unit": "kcal"}}
    - Native DuckDB list of structs: [{"name": "sugars", "100g": 0.5, "unit": "g"}]
    - Legacy OF-list-style strings from the OFF CSV export format
    - dict inputs (already parsed JSON)

    Never raises on malformed input; returns {} for empty/unparseable values.
    """
    if not raw or raw == "[]":
        return {}

    if isinstance(raw, dict):
        return _normalize_nutriment_object(raw)

    if isinstance(raw, list):
        obj = {}
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name and isinstance(name, str):
                    obj[name] = item
        return _normalize_nutriment_object(obj)

    if not isinstance(raw, str):
        return {}

    text = raw.strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return {}
        if not isinstance(obj, dict):
            return {}
        return _normalize_nutriment_object(obj)

    return _parse_nutriments_list_style(text)


def format_off_barcode_path(barcode: str) -> str:
    clean = str(barcode).strip()
    if len(clean) <= 8:
        return clean
    m = re.match(r"^(\d{3})(\d{3})(\d{3})(.*)$", clean)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    return clean


def extract_off_image_url(barcode: str, front_image_url: Any = None, images_raw: Any = None) -> Optional[str]:
    """
    Extract or derive a canonical Open Food Facts CDN image URL.
    Does NOT download image files.
    Returns None if no reliable image metadata is present.
    """
    if front_image_url and isinstance(front_image_url, str) and front_image_url.strip():
        url = front_image_url.strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url

    if not barcode or not images_raw or not isinstance(images_raw, list):
        return None

    clean_code = str(barcode).strip()
    if not clean_code:
        return None

    img_map = {
        item["key"]: item
        for item in images_raw
        if isinstance(item, dict) and item.get("key")
    }

    front_keys = ["front_en", "front_fr", "front"]
    target_id = None

    for fk in front_keys:
        if fk in img_map and img_map[fk].get("imgid"):
            target_id = str(img_map[fk]["imgid"])
            break

    if not target_id:
        for k, v in img_map.items():
            if k.startswith("front") and v.get("imgid"):
                target_id = str(v["imgid"])
                break

    if not target_id and "1" in img_map:
        target_id = "1"

    if target_id:
        return f"https://images.openfoodfacts.org/images/products/{clean_code}/{target_id}.jpg"

    return None


def safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return sanitize_product_text(str(val))

def safe_float(val: Any) -> float:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def safe_int(val: Any) -> Optional[int]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None
