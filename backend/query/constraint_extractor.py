import re
from typing import Any, Dict, List


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

        numeric_filters: List[Dict[str, Any]] = []
        modifiers: List[str] = []
        recipe_quantities: List[Dict[str, Any]] = []
        ranking_preferences: Dict[str, Any] = {}
        explanations: List[Dict[str, Any]] = []

        cleaned_query = normalized_query

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

        # 2. Extract Directional Ranking Preferences (e.g. "lowest sugar", "highest protein", "lowest calorie")
        pref_patterns = [
            (r"\b(?:lowest|least)\s+(?:amount of\s+)?(?:sugar|sugars)\b", "sugars", "asc", "Rank by lowest sugar content"),
            (r"\b(?:highest|most|maximum|max)\s+(?:amount of\s+)?(?:protein|proteins)\b", "proteins", "desc", "Rank by highest protein content"),
            (r"\b(?:lowest|least|minimum|min)\s+(?:amount of\s+)?(?:calories?|kcal|energy)\b", "energy-kcal", "asc", "Rank by lowest calorie/energy density"),
            (r"\b(?:lowest|least)\s+(?:amount of\s+)?(?:sodium|salt)\b", "sodium", "asc", "Rank by lowest sodium content"),
        ]
        for pattern, nutrient, order, explanation in pref_patterns:
            match = re.search(pattern, cleaned_query)
            if match:
                ranking_preferences["sort_nutrient"] = nutrient
                ranking_preferences["order"] = order
                explanations.append({"field": "ranking_preference", "explanation": explanation})
                cleaned_query = re.sub(pattern, " ", cleaned_query)

        # 3. Extract Nutrition Numeric Constraints
        nutrient_aliases = {
            "protein": "protein", "proteins": "proteins",
            "sugar": "sugar", "sugars": "sugars",
            "fat": "fat", "fats": "fat", "carb": "carbs", "carbs": "carbs",
            "carbohydrate": "carbohydrates", "carbohydrates": "carbohydrates",
            "fiber": "fiber", "fibre": "fiber",
            "sodium": "sodium", "salt": "salt",
            "calorie": "calories", "calories": "calories",
            "kcal": "kcal", "energy": "energy",
        }
        operator_aliases = {
            "under": "lte", "below": "lt", "less than": "lt", "fewer than": "lt",
            "at most": "lte", "maximum": "lte", "max": "lte", "no more than": "lte",
            "<": "lt", "<=": "lte",
            "above": "gt", "over": "gt", "more than": "gt", "greater than": "gt",
            "at least": "gte", "minimum": "gte", "min": "gte",
            ">": "gt", ">=": "gte",
            "exactly": "eq", "with exactly": "eq", "==": "eq", "=": "eq"
        }

        nutrient_pattern = "|".join(sorted(nutrient_aliases.keys(), key=len, reverse=True))
        operator_pattern = "|".join(re.escape(k) for k in sorted(operator_aliases.keys(), key=len, reverse=True))
        number_pattern = r"\d+(?:\.\d+)?"

        numeric_patterns = [
            # Pattern A: "with 200 calories or less" / "with 20g protein or more"
            rf"(?:^|\s)(?:with\s+)?(?P<value>{number_pattern})\s*(?P<unit>mg|g|kcal|calories?)?\s*(?P<nutrient>{nutrient_pattern})\s*(?:or|and)\s*(?P<trailing_op>less|fewer|under|more|greater|above)(?=\s|$)",
            # Pattern B: "under 200 calories", "with less than 3g sugar", "<= 300 kcal", "under 120mg sodium"
            rf"(?:^|\s)(?:with\s+)?(?P<operator>{operator_pattern})\s*(?P<value>{number_pattern})\s*(?P<unit>mg|g|kcal|calories?)?(?:\s*(?P<nutrient>{nutrient_pattern}))?(?=\s|$)",
            # Pattern C: "protein >= 20g", "calories <= 300", "sugar < 5g"
            rf"(?:^|\s)(?P<nutrient>{nutrient_pattern})\s*(?:with\s+)?(?P<operator>{operator_pattern})\s*(?P<value>{number_pattern})\s*(?P<unit>mg|g|kcal|calories?)?(?=\s|$)",
            # Pattern D: "with exactly 0g sugar" / "exactly 0 calories"
            rf"(?:^|\s)(?:with\s+)?(?P<operator>exactly|with exactly)\s*(?P<value>{number_pattern})\s*(?P<unit>mg|g|kcal|calories?)?(?:\s*(?P<nutrient>{nutrient_pattern}))?(?=\s|$)",
        ]

        consumed_spans = []
        for pattern in numeric_patterns:
            for match in re.finditer(pattern, cleaned_query):
                if any(match.start() < end and match.end() > start for start, end in consumed_spans):
                    continue

                gd = match.groupdict()
                nutrient_raw = gd.get("nutrient")
                unit_raw = gd.get("unit")
                value = float(gd["value"])

                if not nutrient_raw and unit_raw and unit_raw.lower() in {"kcal", "calories", "calorie", "energy"}:
                    nutrient_raw = unit_raw.lower()

                if not nutrient_raw:
                    continue

                nutrient = nutrient_aliases.get(nutrient_raw, nutrient_raw)

                # Determine operator
                if "trailing_op" in gd and gd["trailing_op"]:
                    top = gd["trailing_op"].lower()
                    op = "lte" if top in {"less", "fewer", "under"} else "gte"
                else:
                    op_raw = gd.get("operator")
                    op = operator_aliases.get(op_raw, "lte")

                is_energy = nutrient in {"calories", "calorie", "kcal", "energy"}
                if is_energy:
                    if unit_raw and unit_raw.lower() not in {"calorie", "calories", "kcal", "energy"}:
                        continue
                    unit = unit_raw or ("kcal" if nutrient == "kcal" else "calories")
                else:
                    unit = (unit_raw or "g").lower()
                    if unit not in {"g", "mg"}:
                        continue
                    if unit == "mg":
                        value /= 1000.0
                        unit = "g"

                # If "sugar eq 0" or "sugar <= 0"
                if nutrient in {"sugar", "sugars"} and value == 0.0 and op in {"lte", "lt", "eq"}:
                    op = "lte"
                    value = 0.5  # standard Canadian tolerance

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

        # 4. Extract Recipe Quantities (e.g. '500 ml', '2 cups', '1/2 cup', '2 tbsp')
        recipe_qty_patterns = [
            r"\b(\d+(?:\.\d+)?|\d+/\d+)\s*(ml|milliliters?|millilitres?|l|liters?|litres?|cups?|tbsp|tablespoons?|tsp|teaspoons?|grams?|g|kg|kilograms?|oz|ounces?|lbs?|pounds?|cloves?|slices?|cans?|pkgs?|packages?|pinch)\b"
        ]
        for pattern in recipe_qty_patterns:
            matches = list(re.finditer(pattern, cleaned_query))
            for match in matches:
                val_str = match.group(1)
                unit_str = match.group(2)

                trailing_text = cleaned_query[match.end():]
                if re.match(
                    r"\s*(?:protein|proteins|sugar|sugars|fat|carbs?|carbohydrates|fiber|sodium|salt|calories?|kcal|energy)\b",
                    trailing_text,
                ):
                    continue

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
                    "explanation": f"Extracted recipe quantity: {match.group(0)}"
                })
                cleaned_query = cleaned_query.replace(match.group(0), " ").strip()

        # 5. Extract Dietary & Certification Filters
        dietary_patterns = [
            (r"\b(?:organic|bio)\b", "organic", True, "Matched 'organic' keyword"),
            (r"\bvegan\b", "vegan", True, "Matched 'vegan' keyword"),
            (r"\b(?:vegetarian|veggie)\b", "vegetarian", True, "Matched 'vegetarian' keyword"),
            (r"\b(?:no[- ]palm[- ]oil|palm[- ]oil[- ]free|without[- ]palm[- ]oil|free[- ]of[- ]palm[- ]oil)\b", "palm_oil", False, "Matched palm oil exclusion"),
            (r"\b(?:palm[- ]oil)\b", "palm_oil", True, "Matched 'palm oil' keyword"),
            (r"\b(?:high[- ]protein|protein[- ]rich|rich[- ]in[- ]protein|extra[- ]protein)\b", "high_protein", True, "Matched high protein requirement (>= 10g/100g)"),
            (r"\b(?:low[- ]sugar|less[- ]sugar|reduced[- ]sugar)\b", "low_sugar", True, "Matched low sugar requirement (<= 5.0g/100g)"),
            (r"\b(?:low[- ]sodium|sodium[- ]free|salt[- ]free|no[- ]salt|low[- ]salt|no[- ]sodium|without[- ]sodium|less[- ]sodium)\b", "low_sodium", True, "Matched low sodium requirement"),
            (r"\b(?:gluten[- ]free|no[- ]gluten|without[- ]gluten|free[- ]of[- ]gluten)\b", "gluten_free", True, "Matched gluten-free requirement"),
            (r"\b(?:lactose[- ]free|dairy[- ]free|no[- ]lactose|without[- ]lactose|free[- ]of[- ]lactose)\b", "lactose_free", True, "Matched lactose-free requirement")
        ]

        # Extract zero-sugar numeric filter if "zero sugar" / "sugar free" was present
        zero_sugar_pattern = r"\b(?:zero[- ]sugar|0[- ]sugar|0g[- ]sugar|no[- ]sugar|without[- ]sugar|sugar[- ]free|0%[- ]sugar|no[- ]added[- ]sugar|sans[- ]sucre)\b"
        if re.search(zero_sugar_pattern, normalized_query):
            if not any(nf.get("nutrient") in {"sugar", "sugars"} for nf in numeric_filters):
                numeric_filters.append({
                    "nutrient": "sugar",
                    "operator": "lte",
                    "value": 0.5,
                    "unit": "g",
                    "comparison_basis": "per_100g",
                    "is_zero_constraint": True
                })
                explanations.append({
                    "field": "numeric_filters",
                    "explanation": "Matched zero sugar requirement (<= 0.5g/100g)"
                })
            temp = re.sub(zero_sugar_pattern, " ", cleaned_query).strip()
            if temp:
                cleaned_query = temp

        for pattern, key, value, explanation in dietary_patterns:
            if filters[key] is not None:
                continue
            if re.search(pattern, cleaned_query):
                filters[key] = value
                explanations.append({"field": key, "explanation": explanation})
                temp = re.sub(pattern, " ", cleaned_query).strip()
                if temp:
                    cleaned_query = temp

        # 6. Clean up leftover connective/filler tokens like "with", "having", "containing", "in", "best", "healthiest"
        cleaned_query = re.sub(r"\b(?:with|having|containing|in|and|or)\b", " ", cleaned_query)
        cleaned_query = re.sub(r"\b(?:healthiest|healthy)\b", " ", cleaned_query)
        cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()

        return {
            "filters": filters,
            "numeric_filters": numeric_filters,
            "modifiers": modifiers,
            "recipe_quantities": recipe_quantities,
            "ranking_preferences": ranking_preferences,
            "explanations": explanations,
            "cleaned_query": cleaned_query
        }
