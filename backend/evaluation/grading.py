"""
Structured relevance grading for the AskOFF benchmark (P3).

Replaces keyword-count conjunction semantics with intent-shaped conditions:

  relevance:
    required_any:     [ [terms...], ... ]   # product must satisfy at least ONE group (all its terms)
    required_all:     [ terms... ]          # every listed term must be present
    optional:         [ terms... ]          # soft signals, not graded (analysis only)
    excluded:         [ {term, scope} ... ] # scope "name" = product_name only; "all" = name+search_text
    required_flags:   { flag: bool }        # must equal attributes.flags
    nutrition:        { nutrient, operator, value }  # validated against attributes.nutrition.<field>.per_100g
    brand:            "compliments"         # brand must appear in brand or product_name
    group_scope:      "anywhere" | "name"   # where required groups must be satisfied (default anywhere)

Scoring:
  3  highly relevant: hard conditions pass and required group satisfied inside product_name
  2  relevant:        hard conditions pass and required groups/nutrition satisfied anywhere
  1  partially relevant:  hard conditions pass (flags/brand) but required group only partially matched
  0  irrelevant:       excluded / flag fail / brand fail / no satisfied group / numeric fail

The original (pre-fix) grader is preserved in evaluation.evaluate.evaluate_product for baseline
reproduction. This module is the "structured" grader used by the fixed benchmark.
"""

import re as _re
from typing import Any, Dict, List, Optional


def _term_regex(term: str) -> "_re.Pattern":
    """Word-boundary-aware pattern with plural tolerance. 'oat' never matches 'goat' or 'oatmeal'."""
    base = term.lower()
    variants = {base}
    if base.endswith("y"):
        variants.add(base[:-1] + "ies")
    if not base.endswith("s"):
        variants.add(base + "s")
    alt = "|".join(_re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return _re.compile(r"(?<![a-z0-9])(?:" + alt + r")(?![a-z0-9])")


def _term_present(lower_hay: str, term: str) -> bool:
    if not term:
        return False
    return bool(_term_regex(term).search(lower_hay))


NUTRIENT_FIELD_MAP = {
    "protein": "proteins",
    "proteins": "proteins",
    "sugar": "sugars",
    "sugars": "sugars",
    "fat": "fat",
    "calories": "energy-kcal",
    "kcal": "energy-kcal",
    "energy": "energy-kcal",
    "sodium": "sodium",
    "salt": "salt",
    "carbs": "carbohydrates",
    "carbohydrates": "carbohydrates",
    "fiber": "fiber",
    "saturated fat": "saturated-fat",
}


def _flags(product) -> Dict[str, Any]:
    attrs = product.attributes or {}
    return attrs.get("flags", {}) or {}


def _nutrition(product) -> Dict[str, Any]:
    attrs = product.attributes or {}
    return attrs.get("nutrition", {}) or {}


def _per_100g(product, nutrient: str) -> Optional[float]:
    field = NUTRIENT_FIELD_MAP.get(nutrient, nutrient)
    entry = _nutrition(product).get(field, {})
    if isinstance(entry, dict):
        val = entry.get("per_100g")
        if val is None:
            val = entry.get("value")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
    return None


def _hard_failures(product, relevance: Dict[str, Any]) -> List[str]:
    reasons = []
    scope_default = relevance.get("excluded_scope", "all")

    for ex in relevance.get("excluded", []):
        if isinstance(ex, str):
            term, scope = ex, scope_default
        else:
            term, scope = ex.get("term", ""), ex.get("scope", scope_default)
        name = (product.product_name or "").lower()
        if term and _term_present(name, term):
            reasons.append(f"excluded_in_name:{term}")
            continue
        if scope != "name":
            text = (product.search_text or "").lower()
            if term and _term_present(text, term):
                reasons.append(f"excluded_in_text:{term}")

    if reasons:
        return reasons

    for flag, want in (relevance.get("required_flags", {}) or {}).items():
        got = _flags(product).get(flag)
        want_bool = bool(want)
        if got is not want_bool:
            reasons.append(f"flag:{flag}=expected_{want_bool}_got_{got}")
            return reasons

    rel_brand = relevance.get("brand")
    if rel_brand:
        brand = (product.brand or "").lower()
        name = (product.product_name or "").lower()
        rb = rel_brand.lower()
        if not _term_present(brand, rb) and not _term_present(name, rb):
            reasons.append(f"brand_required:{rel_brand}")
            return reasons

    return reasons


def _group_satisfied(lower_hay, group: List[str]) -> bool:
    return all(_term_present(lower_hay, term) for term in group)


def _partial_group(lower_hay, group: List[str]) -> bool:
    return any(_term_present(lower_hay, term) for term in group)


def evaluate_structured(product, item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Grade one product against a benchmark item with structured 'relevance'.
    Returns {rel, reasons, matched_groups, partial_groups, nutrition_ok}
    """
    rel = 0
    reasons: List[str] = []
    rel_def = item.get("relevance", {}) or {}

    hard = _hard_failures(product, rel_def)
    if hard:
        reasons = hard
        return {"rel": 0, "reasons": reasons, "matched_groups": [], "partial_groups": [], "nutrition_ok": None}

    name = (product.product_name or "").lower()
    text = (product.search_text or "").lower()
    scope = rel_def.get("group_scope", "anywhere")
    groups_any = rel_def.get("required_any", [])
    groups_all = rel_def.get("required_all", [])

    matched_in_name = []
    matched_anywhere = []
    partial_in_name = []
    partial_anywhere = []

    for grp in groups_any:
        pair = (name, text) if scope == "anywhere" else (name, name)
        if _group_satisfied(pair[0], grp):
            matched_in_name.append(grp)
        if _group_satisfied(pair[1], grp):
            matched_anywhere.append(grp)
        if _partial_group(pair[0], grp):
            partial_in_name.append(grp)
        if _partial_group(pair[1], grp):
            partial_anywhere.append(grp)

    all_ok = groups_all and _group_satisfied(text if scope != "name" else name, groups_all)
    if groups_all and all_ok:
        matched_anywhere.append(("all", groups_all))

    nutrition_rel = rel_def.get("nutrition")
    nutrition_ok = None
    if nutrition_rel:
        val = _per_100g(product, nutrition_rel.get("nutrient", ""))
        op = nutrition_rel.get("operator", "gte")
        target = nutrition_rel.get("value", 0.0)
        if val is None:
            nutrition_ok = False
            reasons.append("numeric_missing")
        elif op == "gte":
            nutrition_ok = val >= target
            reasons.append(f"numeric_{nutrition_rel['nutrient']}={val:.1f}_{op}_{target}"
                           if nutrition_ok else f"numeric_fail_{nutrition_rel['nutrient']}={val:.1f}{op}{target}")
            if not nutrition_ok:
                reasons = [r for r in reasons if not r.startswith("numeric_")]
                reasons.append(f"numeric_fail:{nutrition_rel['nutrient']}={val:.1f}{op}{target}")
        elif op == "lte":
            nutrition_ok = val <= target
            reasons.append(f"numeric_{nutrition_rel['nutrient']}={val:.1f}_{op}_{target}"
                           if nutrition_ok else f"numeric_fail:{nutrition_rel['nutrient']}={val:.1f}{op}{target}")
        else:
            nutrition_ok = False
            reasons.append(f"unsupported_op:{op}")

        if not nutrition_ok:
            return {"rel": 0, "reasons": reasons, "matched_groups": [g for g in matched_anywhere],
                    "partial_groups": [g for g in partial_anywhere], "nutrition_ok": False}

    has_keyword_condition = bool(groups_any or groups_all)
    if has_keyword_condition:
        if matched_in_name:
            rel = 3
            reasons.append(f"group_in_name:{matched_in_name[0]}")
        elif matched_anywhere:
            rel = 2
            reasons.append(f"group_anywhere:{matched_anywhere[0]}")
        elif partial_anywhere:
            rel = 1
            reasons.append(f"partial_brand_or_terms:{[g for g in partial_anywhere][0]}")
        else:
            reasons.append("no_group_match")
            rel = 0
    else:
        relative_ok = (nutrition_ok is True) or bool(rel_def.get("required_flags"))
        if relative_ok:
            if matched_in_name or rel_def.get("optional"):
                rel = 3 if rel_def.get("optional") and all(
                    _group_satisfied(name, [o]) for o in rel_def.get("optional", [])
                ) else 2
            else:
                rel = 2
            reasons.append("hard_condition_only" if matched_in_name else "constraint_only")
        else:
            rel = 2
            reasons.append("no_conditions")

    return {"rel": rel, "reasons": reasons,
            "matched_groups": [g for g in matched_anywhere],
            "partial_groups": [g for g in partial_anywhere], "nutrition_ok": nutrition_ok}


def grade_item(product, item: Dict[str, Any], mode: str = "structured") -> Dict[str, Any]:
    """Dispatch to structured or classic grader. Classic route preserved for baseline reproduction."""
    if mode == "structured":
        if not item.get("relevance"):
            return {"rel": None, "reasons": ["unscored:no_relevance_definition"], "matched_groups": [],
                    "partial_groups": [], "nutrition_ok": None}
        return evaluate_structured(product, item)
    from evaluation.evaluate import evaluate_product  # classic (pre-fix) grader

    return {"rel": evaluate_product(product, item), "reasons": ["classic_grader"], "mode": "classic"}


def knapsack_metrics(relevances: List[int], k: int = 10):
    """Compute result-set P@5/P@10, graded NDCG@k, and binary MRR.

    ``relevances`` contains only the retrieved, programmatically graded hits.
    Consequently NDCG is normalized against the ideal ordering of this result
    set, not a complete corpus qrels pool. It is useful for regression, but it
    is not a corpus-level effectiveness claim until independent qrels exist.
    """
    import math

    clean = [r for r in relevances if r is not None]
    if not clean:
        return {"p5": None, "p10": None, "ndcg": None, "mrr": None}
    graded = clean[:k] + [0] * (k - min(len(clean), k))
    binary = [1 if relevance >= 2 else 0 for relevance in graded]
    p5 = sum(binary[:5]) / 5.0
    p10 = sum(binary[:10]) / 10.0
    gains = [(2**relevance) - 1 for relevance in graded]
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains) if gain)
    ideal_gains = sorted(gains, reverse=True)
    idcg = sum(
        gain / math.log2(rank + 2) for rank, gain in enumerate(ideal_gains) if gain
    )
    ndcg = dcg / idcg if idcg else 0.0
    mrr = next((1.0 / rank for rank, relevance in enumerate(binary, 1) if relevance), 0.0)
    return {"p5": p5, "p10": p10, "ndcg": ndcg, "mrr": mrr}
