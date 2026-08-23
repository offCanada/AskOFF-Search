import re
from typing import Any, Dict


class ConstraintExtractor:
    @staticmethod
    def extract(normalized_query: str) -> Dict[str, Any]:
        filters = {
            "organic": None,
            "vegan": None,
            "vegetarian": None,
            "palm_oil": None,
            "high_protein": None,
            "low_sugar": None,
            "low_sodium": None,
            "gluten_free": None,
            "lactose_free": None
        }

        numeric_filters = []
        modifiers = []
        recipe_quantities = []

        cleaned_query = normalized_query
        explanations = []

        # 1. Extract Modifiers (e.g. fresh, frozen, raw, pure, natural, wild, farmed, salted, unsalted)
        modifier_patterns = [
            r"\b(?:fresh|frozen|raw|pure|natural|wild|farmed|salted|unsalted)\b"
        ]
        for pattern in modifier_patterns:
            for match in re.finditer(pattern, cleaned_query):
                mod = match.group(0)
                if mod not in modifiers:
                    modifiers.append(mod)
                    explanations.append({"field": "modifiers", "explanation": f"Extracted modifier '{mod}'"})

        # 2. Extract nutrition constraints. Values in the index are per 100g:
        # mass nutrients are stored in grams and energy is stored in kcal.  Reject
        # incompatible units instead of silently comparing unlike quantities.
        nutrient_aliases = {
            "protein": "protein", "proteins": "proteins",
            "sugar": "sugar", "sugars": "sugars",
            "fat": "fat", "carb": "carbs", "carbs": "carbs",
            "carbohydrate": "carbohydrates", "carbohydrates": "carbohydrates",
            "fiber": "fiber", "sodium": "sodium", "salt": "salt",
            "calorie": "calories", "calories": "calories", "kcal": "kcal",
            "energy": "energy",
        }
        operator_aliases = {
            "under": "lte", "less than": "lt", "at most": "lte", "no more than": "lte",
            "<": "lt", "<=": "lte", "at least": "gte", "more than": "gt",
            "over": "gt", ">": "gt", ">=": "gte",
        }
        nutrient_pattern = "|".join(sorted(nutrient_aliases, key=len, reverse=True))
        operator_pattern = "|".join(re.escape(value) for value in sorted(operator_aliases, key=len, reverse=True))
        number_pattern = r"\d+(?:\.\d+)?"

        numeric_patterns = [
            # "at least 20g protein" and "under 200 calories"
            rf"\b(?P<operator>{operator_pattern})\s*(?P<value>{number_pattern})\s*(?P<unit>mg|g|kcal|calories)?\s*(?P<nutrient>{nutrient_pattern})\b",
            # "protein >= 20g"
            rf"\b(?P<nutrient>{nutrient_pattern})\s*(?P<operator>{operator_pattern})\s*(?P<value>{number_pattern})\s*(?P<unit>mg|g|kcal|calories)\b",
        ]
        consumed_spans = []
        for pattern in numeric_patterns:
            for match in re.finditer(pattern, cleaned_query):
                if any(match.start() < end and match.end() > start for start, end in consumed_spans):
                    continue
                nutrient = nutrient_aliases[match.group("nutrient")]
                unit = (match.group("unit") or nutrient).lower()
                value = float(match.group("value"))

                is_energy = nutrient in {"calories", "kcal", "energy"}
                if is_energy:
                    if unit not in {"calorie", "calories", "kcal", "energy"}:
                        continue
                else:
                    if unit not in {"g", "mg"}:
                        continue
                    if unit == "mg":
                        value /= 1000.0
                        unit = "g"

                op = operator_aliases[match.group("operator")]
                numeric_filters.append({
                    "nutrient": nutrient,
                    "operator": op,
                    "value": value,
                    "unit": unit,
                    "comparison_basis": "per_100g",
                })
                explanations.append({
                    "field": "numeric",
                    "explanation": f"Numeric constraint: {nutrient} {op} {value}{unit} per 100g",
                })
                consumed_spans.append(match.span())

        for start, end in sorted(consumed_spans, reverse=True):
            cleaned_query = cleaned_query[:start] + " " + cleaned_query[end:]
        cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()

        # 3. Extract Recipe Quantities (e.g. '500 ml', '2 cups', '1/2 cup', '2 tbsp', '100g')
        # Guard: do not strip fat percentages like '2% milk' or '1% milk' or single product codes/brands like '7up'
        recipe_qty_patterns = [
            r"\b(\d+(?:\.\d+)?|\d+/\d+)\s*(ml|milliliters?|millilitres?|l|liters?|litres?|cups?|tbsp|tablespoons?|tsp|teaspoons?|grams?|g|kg|kilograms?|oz|ounces?|lbs?|pounds?|cloves?|slices?|cans?|pkgs?|packages?|pinch)\b"
        ]
        for pattern in recipe_qty_patterns:
            matches = list(re.finditer(pattern, cleaned_query))
            for match in matches:
                val_str = match.group(1)
                unit_str = match.group(2)

                # A mass immediately followed by a nutrition noun belongs to an
                # invalid nutrition expression (for example "20g calories"), not
                # a recipe quantity. Leave it intact rather than changing intent.
                trailing_text = cleaned_query[match.end():]
                if re.match(
                    r"\s*(?:protein|proteins|sugar|sugars|fat|carbs?|carbohydrates|fiber|sodium|salt|calories?|kcal|energy)\b",
                    trailing_text,
                ):
                    continue

                # Check fraction
                if "/" in val_str:
                    num, denom = val_str.split("/")
                    val = float(num) / float(denom) if float(denom) != 0 else 0.0
                else:
                    val = float(val_str)

                recipe_quantities.append({
                    "raw": match.group(0),
                    "value": val,
                    "unit": unit_str
                })
                explanations.append({
                    "field": "recipe_quantity",
                    "explanation": f"Extracted recipe quantity: {match.group(0)} (separated from product retrieval term)"
                })
                # Remove recipe quantity token from search text
                cleaned_query = cleaned_query.replace(match.group(0), " ").strip()

        # 4. Extract Dietary & Certification Filters
        patterns = [
            (r"\b(?:organic|bio)\b", "organic", True, "Matched 'organic' or 'bio' keyword indicating organic certification"),
            (r"\bvegan\b", "vegan", True, "Matched 'vegan' keyword indicating vegan requirement"),
            (r"\b(?:vegetarian|veggie)\b", "vegetarian", True, "Matched 'vegetarian' or 'veggie' keyword indicating vegetarian requirement"),
            (r"\b(?:no[- ]palm[- ]oil|palm[- ]oil[- ]free|without[- ]palm[- ]oil|free[- ]of[- ]palm[- ]oil)\b", "palm_oil", False, "Matched phrase indicating palm oil exclusion"),
            (r"\b(?:palm[- ]oil)\b", "palm_oil", True, "Matched 'palm oil' keyword"),
            (r"\b(?:high[- ]protein|protein[- ]rich|rich[- ]in[- ]protein|extra[- ]protein)\b", "high_protein", True, "Matched phrase indicating high protein requirement"),
            (r"\b(?:low[- ]sugar|sugar[- ]free|zero[- ]sugar|no[- ]sugar|without[- ]sugar|less[- ]sugar)\b", "low_sugar", True, "Matched phrase indicating low or zero sugar requirement"),
            (r"\b(?:low[- ]sodium|sodium[- ]free|salt[- ]free|no[- ]salt|low[- ]salt|no[- ]sodium|without[- ]sodium|less[- ]sodium)\b", "low_sodium", True, "Matched phrase indicating low or zero sodium/salt requirement"),
            (r"\b(?:gluten[- ]free|no[- ]gluten|without[- ]gluten|free[- ]of[- ]gluten)\b", "gluten_free", True, "Matched phrase indicating gluten-free requirement"),
            (r"\b(?:lactose[- ]free|dairy[- ]free|no[- ]lactose|without[- ]lactose|free[- ]of[- ]lactose)\b", "lactose_free", True, "Matched phrase indicating lactose-free requirement")
        ]

        for pattern, key, value, explanation in patterns:
            if filters[key] is not None:
                continue
            if re.search(pattern, cleaned_query):
                filters[key] = value
                explanations.append({"field": key, "explanation": explanation})
                temp = re.sub(pattern, "", cleaned_query).strip()
                if temp:
                    cleaned_query = temp

        cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()

        return {
            "filters": filters,
            "numeric_filters": numeric_filters,
            "modifiers": modifiers,
            "recipe_quantities": recipe_quantities,
            "explanations": explanations,
            "cleaned_query": cleaned_query
        }

