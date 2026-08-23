"""
AskOFF P3 FINAL BLACK-BOX SEARCH QUALITY AUDIT - runner (READ-ONLY).

Runs a fixed 69-query suite against the LIVE OpenSearch index through the
normal SearchEngine path (same code path as the FastAPI app), captures:
  - NLP interpretation (intent, entities, constraints, quantities, clean term)
  - OpenSearch DSL summary (clauses, msm, fuzziness, filters, function score)
  - TOP 6 products with score, nutrition, flags, ingredients, quality metadata
  - independent constraint-compliance checks (mirrors SearchDocumentBuilder)
  - fuzzy/synonym pair comparisons

Writes:
  backend/evaluation/black_box_results.json   (machine readable)
  backend/evaluation/black_box_digest.txt     (compact human review digest)

This script performs NO writes to the index and NO code changes.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.audit_harness import build_engine  # loads dictionaries like API startup

OUT_JSON = Path(__file__).parent / "black_box_results.json"
OUT_DIGEST = Path(__file__).parent / "black_box_digest.txt"

SUITE = [
    ("A_normal", "milk"), ("A_normal", "bread"), ("A_normal", "butter"),
    ("A_normal", "coffee"), ("A_normal", "chips"), ("A_normal", "peanut butter"),
    ("A_normal", "tomato sauce"), ("A_normal", "olive oil"),

    ("B_multiword", "chocolate cookies"), ("B_multiword", "almond milk"),
    ("B_multiword", "extra virgin olive oil"), ("B_multiword", "salted butter"),
    ("B_multiword", "tomato pasta sauce"), ("B_multiword", "whole wheat bread"),

    ("C_brand", "Compliments peanut butter"), ("C_brand", "Compliments soy sauce"),
    ("C_brand", "Compliments strawberry cereal bars"), ("C_brand", "Silk almond milk"),
    ("C_brand", "President butter"), ("C_brand", "Kellogg's cereal"),

    ("D_ingredient", "blueberries"), ("D_ingredient", "rolled oats"),
    ("D_ingredient", "almonds"), ("D_ingredient", "chickpeas"),
    ("D_ingredient", "black beans"),

    ("E_recipe", "500 mL frozen blueberries"), ("E_recipe", "2 tbsp salted butter"),
    ("E_recipe", "1 cup rolled oats"), ("E_recipe", "250g fresh tomatoes"),
    ("E_recipe", "half cup almond milk"), ("E_recipe", "200 g canned black beans"),

    ("F_fuzzy", "peanute butter"), ("F_fuzzy", "tomatos sauce"),
    ("F_fuzzy", "choclate cookies"), ("F_fuzzy", "yogourt"), ("F_fuzzy", "soya sauce"),

    ("G_synonym", "soy sauce"), ("G_synonym", "soya sauce"), ("G_synonym", "yogurt"),
    ("G_synonym", "yoghurt"), ("G_synonym", "frozen vegetables"),

    ("H_nutrition", "no sugar cereal"), ("H_nutrition", "low sugar cereal"),
    ("H_nutrition", "high protein snacks"),
    ("H_nutrition", "products with at least 20g protein"),
    ("H_nutrition", "low calorie snacks"), ("H_nutrition", "snacks under 200 calories"),
    ("H_nutrition", "low sodium soup"), ("H_nutrition", "lactose free milk"),

    ("I_exclusion", "no palm oil peanut butter"), ("I_exclusion", "palm oil free peanut butter"),
    ("I_exclusion", "dairy free cookies"), ("I_exclusion", "gluten free bread"),
    ("I_exclusion", "vegan cookies"), ("I_exclusion", "lactose free milk"),

    ("J_best", "best peanut butter"), ("J_best", "healthiest cereal"),
    ("J_best", "best low sugar cereal"), ("J_best", "healthiest high protein snack"),
    ("J_best", "best olive oil"),

    ("K_category", "frozen vegetables"), ("K_category", "breakfast cereal"),
    ("K_category", "protein bars"), ("K_category", "canned beans"),
    ("K_category", "plant based milk"),

    ("L_numeric", "2% milk"), ("L_numeric", "7up"), ("L_numeric", "3.25% milk"),
    ("L_numeric", "0% yogurt"),
]

# Independent constraint checkers.
# System thresholds mirror SearchDocumentBuilder exactly (reported in audit):
#   is_high_protein : proteins >= 10 g/100g  (or category says "high protein")
#   is_low_sugar    : 0 <= sugars <= 5 g/100g (or category phrases)
#   is_low_sodium   : 0 <= sodium <= 0.12 g/100g (or category phrases)
#   is_lactose_free : category phrases only ("lactose free","dairy free","sans lactose")
#   is_gluten_free  : category phrases only ("gluten free","gluten-free","sans gluten")
#   is_vegan        : "vegan" in categories or ingredients
#   is_palm_oil_free: "palm oil" not in ingredients

DAIRY_TOKENS = ["milk", "dairy", "lactose", "cream", "whey", "casein", "butter",
                "yogurt", "yoghurt", "cheese", "milk ingredients", "skim milk powder"]
GLUTEN_TOKENS = ["wheat", "barley", "rye", "spelt", "kamut", "gluten", "farina", "semolina"]
ANIMAL_TOKENS = ["milk", "egg", "honey", "butter", "whey", "casein", "gelatin",
                 "cheese", "yogurt", "yoghurt", "cream", "chicken", "beef", "pork",
                 "fish", "turkey", "lard", "tallow", "albumen", "egg white"]


def nut(doc, key):
    n = (doc.attributes or {}).get("nutrition", {}) or {}
    e = n.get(key)
    if isinstance(e, dict):
        v = e.get("per_100g")
        return float(v) if v is not None else None
    return None


def ing_lower(doc):
    return str(doc.ingredients or "").lower()


def cat_lower(doc):
    return str(doc.category or "").lower()


def flag(doc, name):
    return (doc.attributes or {}).get("flags", {}).get(name)


def check(hit_doc, kind):
    """Return dict(system=..., independent=..., verdict=PASS/FAIL/UNKNOWN)."""
    d = hit_doc
    p, s, na, so = nut(d, "proteins"), nut(d, "sugars"), nut(d, "energy-kcal"), nut(d, "sodium")
    ing = ing_lower(d)

    def verdict(sysv, indv):
        if sysv is False or indv is False:
            return "FAIL"
        if sysv is True and indv is True:
            return "PASS"
        if sysv is None and indv is None:
            return "UNKNOWN"
        return "PARTIAL"

    if kind == "high_protein":
        sysv = flag(d, "is_high_protein")
        ind = p if p is None else p >= 10.0
        return {"metric": f"protein={p}g", "system_flag": sysv, "independent": ind,
                "verdict": verdict(True if sysv else ind, ind)}
    if kind == "low_sugar":
        sysv = flag(d, "is_low_sugar")
        ind = s if s is None else (0 <= s <= 5.0)
        return {"metric": f"sugar={s}g", "system_flag": sysv, "independent": ind,
                "verdict": verdict(True if sysv else ind, ind)}
    if kind == "no_sugar_strict":
        sysv = flag(d, "is_low_sugar")
        ind = s if s is None else (s == 0.0)
        v = "FAIL" if (s is not None and s > 0) else ("UNKNOWN" if s is None else "PASS")
        return {"metric": f"sugar={s}g", "system_flag": sysv, "independent": ind, "verdict": v}
    if kind == "low_sodium":
        sysv = flag(d, "is_low_sodium")
        ind = so if so is None else (0 <= so <= 0.12)
        return {"metric": f"sodium={so}g", "system_flag": sysv, "independent": ind,
                "verdict": verdict(True if sysv else ind, ind)}
    if kind == "kcal_le_200":
        ind = na if na is None else na <= 200.0
        return {"metric": f"kcal={na}", "system_flag": None, "independent": ind,
                "verdict": "UNKNOWN" if ind is None else ("PASS" if ind else "FAIL")}
    if kind == "protein_gte_20":
        ind = p if p is None else p >= 20.0
        return {"metric": f"protein={p}g", "system_flag": None, "independent": ind,
                "verdict": "UNKNOWN" if ind is None else ("PASS" if ind else "FAIL")}
    if kind == "kcal_low_calorie":
        return {"metric": f"kcal={na}", "system_flag": None, "independent": None,
                "verdict": "UNKNOWN"}
    if kind == "lactose_free":
        sysv = flag(d, "is_lactose_free")
        hits = [t for t in DAIRY_TOKENS if t in ing] if ing else None
        ind = None if not ing else (len(hits) == 0)
        return {"metric": f"dairy_tokens={hits}", "system_flag": sysv, "independent": ind,
                "verdict": verdict(True if sysv else ind, ind)}
    if kind == "gluten_free":
        sysv = flag(d, "is_gluten_free")
        hits = [t for t in GLUTEN_TOKENS if t in ing] if ing else None
        ind = None if not ing else (len(hits) == 0)
        return {"metric": f"gluten_tokens={hits}", "system_flag": sysv, "independent": ind,
                "verdict": verdict(True if sysv else ind, ind)}
    if kind == "vegan":
        sysv = flag(d, "is_vegan")
        hits = [t for t in ANIMAL_TOKENS if t in ing] if ing else None
        ind = None if not ing else (len(hits) == 0)
        return {"metric": f"animal_tokens={hits}", "system_flag": sysv, "independent": ind,
                "verdict": verdict(True if sysv else ind, ind)}
    if kind == "palm_oil_free":
        sysv = flag(d, "is_palm_oil_free")
        has_palm = "palm" in ing if ing else None
        ind = None if has_palm is None else (not has_palm)
        return {"metric": f"palm_in_ingredients={has_palm}", "system_flag": sysv,
                "independent": ind, "verdict": verdict(sysv, ind)}
    return {"metric": None, "system_flag": None, "independent": None, "verdict": "N/A"}


CHECKERS = {
    "no sugar cereal": "no_sugar_strict",
    "low sugar cereal": "low_sugar",
    "high protein snacks": "high_protein",
    "products with at least 20g protein": "protein_gte_20",
    "low calorie snacks": "kcal_low_calorie",
    "snacks under 200 calories": "kcal_le_200",
    "low sodium soup": "low_sodium",
    "lactose free milk": "lactose_free",
    "no palm oil peanut butter": "palm_oil_free",
    "palm oil free peanut butter": "palm_oil_free",
    "dairy free cookies": "lactose_free",
    "gluten free bread": "gluten_free",
    "vegan cookies": "vegan",
}


def dsl_summary(oq):
    """Summarize the meaningful retrieval logic from the function_score DSL."""
    try:
        b = oq["query"]["function_score"]["query"]["bool"]
        fs = oq["query"]["function_score"]
    except Exception:
        return {"error": "unexpected DSL shape"}
    out = {"must": [], "should": [], "must_not_count": len(b.get("must_not", [])),
           "bool_msm": b.get("minimum_should_match")}
    for c in b.get("must", []):
        if "multi_match" in c:
            mm = c["multi_match"]
            out["must"].append({"type": "multi_match", "query": mm.get("query"),
                                "boost": mm.get("boost"), "op": mm.get("operator")})
        elif "match" in c:
            mv = c["match"]
            k, v = next(iter(mv.items()))
            out["must"].append({"type": "match", "field": k, "value": v})
        elif "term" in c:
            tv = c["term"]
            k, v = next(iter(tv.items()))
            out["must"].append({"type": "filter_term", "field": k, "value": v})
        elif "range" in c:
            rv = c["range"]
            k, v = next(iter(rv.items()))
            out["must"].append({"type": "range", "field": k, "clause": v})
        elif "match_all" in c:
            out["must"].append({"type": "match_all"})
        elif "bool" in c:
            inner = c["bool"]
            kinds = []
            for cc in inner.get("should", []):
                if "multi_match" in cc:
                    m2 = cc["multi_match"]
                    kinds.append({"type": "mm_or", "q": m2.get("query"),
                                  "msm": m2.get("minimum_should_match"),
                                  "fuzz": m2.get("fuzziness"), "boost": m2.get("boost")})
                elif "term" in cc:
                    tv = cc["term"]
                    k, v = next(iter(tv.items()))
                    kinds.append({"type": "term_should", "field": k, "value": v})
            out["must"].append({"type": "inner_bool", "children": kinds,
                                "inner_msm": inner.get("minimum_should_match")})
    for c in b.get("should", []):
        if "multi_match" in c:
            mm = c["multi_match"]
            out["should"].append({"type": "mm_or", "q": mm.get("query"),
                                  "msm": mm.get("minimum_should_match"),
                                  "fuzz": mm.get("fuzziness"), "boost": mm.get("boost"),
                                  "op": mm.get("operator")})
        elif "term" in c:
            tv = c["term"]
            k, v = next(iter(tv.items()))
            out["should"].append({"type": "term_should", "field": k, "value": v})
    out["functions"] = [list(f.keys()) for f in fs.get("functions", [])]
    out["boost_mode"] = fs.get("boost_mode")
    return out


def run():
    engine = build_engine("opensearch")
    results = []
    cache = {}
    lines = []

    for cat, q in SUITE:
        if q in cache:
            base = json.loads(json.dumps(cache[q]))
            base["suite_category"] = cat
            results.append(base)
            continue
        t0 = time.time()
        resp = engine.search(q, size=6, explain=True)
        lat = (time.time() - t0) * 1000
        sq = resp.search_query or {}
        rec = {
            "suite_category": cat,
            "query": q,
            "latency_ms": round(lat, 1),
            "total_hits": resp.total,
            "nlp": {
                "normalized_query": sq.get("normalized_query"),
                "intent": sq.get("intent"),
                "entities": sq.get("extracted_entities"),
                "constraints": sq.get("constraints"),
                "numeric_filters": sq.get("numeric_filters"),
                "modifiers": sq.get("modifiers"),
                "recipe_quantities": sq.get("recipe_quantities"),
                "ranking_preferences": sq.get("ranking_preferences"),
                "clean_search_term": sq.get("parsed_query"),
            },
            "dsl": dsl_summary(sq.get("opensearch_query", {})),
            "hits": [],
        }
        for i, h in enumerate(resp.hits[:6], 1):
            d = h.product
            md = d.metadata or {}
            fl = (d.attributes or {}).get("flags", {})
            ck = CHECKERS.get(q)
            rec["hits"].append({
                "rank": i,
                "score": round(float(h.score), 4),
                "id": d.id,
                "product_name": d.product_name,
                "brand": d.brand,
                "category": d.category,
                "ingredients": (str(d.ingredients)[:400] if d.ingredients else None),
                "contains_palm": ("palm" in ing_lower(d)) if d.ingredients else None,
                "flags": fl,
                "nutrition_per_100g": {
                    "energy-kcal": nut(d, "energy-kcal"),
                    "proteins": nut(d, "proteins"),
                    "sugars": nut(d, "sugars"),
                    "sodium": nut(d, "sodium"),
                    "salt": nut(d, "salt"),
                    "fiber": nut(d, "fiber"),
                },
                "metadata": {
                    "nutriscore_grade": md.get("nutriscore_grade"),
                    "nova_group": md.get("nova_group"),
                    "completeness": md.get("completeness"),
                },
                "constraint_check": check(d, ck) if ck else None,
            })
        results.append(rec)
        cache[q] = json.loads(json.dumps(rec))

    # ---- pair comparisons ----
    by_q = {}
    for r in results:
        by_q.setdefault(r["query"], r)

    def ids(r):
        return [h["id"] for h in r["hits"]] if r else []

    def names(r):
        return [h["product_name"] for h in r["hits"]] if r else []

    pairs = {
        "fuzzy_pairs": [
            ("peanut butter", "peanute butter"),
            ("tomato sauce", "tomatos sauce"),
            ("chocolate cookies", "choclate cookies"),
            ("yogurt", "yogourt"),
        ],
        "synonym_pairs": [
            ("soy sauce", "soya sauce"),
            ("yogurt", "yoghurt"),
        ],
    }
    comparisons = {}
    for group, plist in pairs.items():
        comparisons[group] = []
        for a, b in plist:
            ra, rb = by_q.get(a), by_q.get(b)
            ia, ib = set(ids(ra)), set(ids(rb))
            ov = len(ia & ib)
            union = len(ia | ib) or 1
            comparisons[group].append({
                "correct": a, "variant": b,
                "top6_overlap_pct": round(100 * ov / max(union, 6), 1),
                "overlap_union": round(100 * ov / union, 1),
                "top1_correct": names(ra)[0] if ra and ra["hits"] else None,
                "top1_variant": names(rb)[0] if rb and rb["hits"] else None,
                "top1_consistent": bool(ia and ib and ids(ra)[0] == ids(rb)[0]),
                "only_in_correct": list(ia - ib),
                "only_in_variant": list(ib - ia),
            })

    # ---- nutrition compliance rollups ----
    rollups = {}
    for q, kind in CHECKERS.items():
        r = by_q.get(q)
        if not r:
            continue
        vs = [h["constraint_check"]["verdict"] for h in r["hits"]]
        n = len(vs)
        rollups[q] = {
            "checker": kind,
            "pass": vs.count("PASS"),
            "fail": vs.count("FAIL"),
            "partial": vs.count("PARTIAL"),
            "unknown": vs.count("UNKNOWN"),
            "compliance_rate": round((vs.count("PASS")) / n, 3) if n else None,
        }

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "index": "askoff_products",
            "engine_path": "SearchEngine -> OpenSearchSearchRepository (live)",
            "queries_run": len(results),
            "note": "READ-ONLY audit; no index/code changes.",
        },
        "results": results,
        "comparisons": comparisons,
        "constraint_rollups": rollups,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- digest ----
    for r in results:
        nlp = r["nlp"]
        lines.append("=" * 100)
        lines.append(f"[{r['suite_category']}] QUERY: {r['query']!r}  total={r['total_hits']} latency={r['latency_ms']}ms")
        lines.append(f"  intent={nlp['intent']} term={nlp['clean_search_term']!r}")
        ents = nlp["entities"] or {}
        br = [e["value"] for e in ents.get("brands", [])]
        ca = [e["value"] for e in ents.get("categories", [])]
        ing = [e["value"] for e in ents.get("ingredients", [])]
        cons = {k: v for k, v in (nlp["constraints"] or {}).items() if v is not None}
        lines.append(f"  brands={br} categories={ca} ingredients={ing}")
        lines.append(f"  constraints={cons} numeric={nlp['numeric_filters']} modifiers={nlp['modifiers']} qty={nlp['recipe_quantities']} rank_prefs={nlp['ranking_preferences']}")
        d = r["dsl"]
        mm_or = None
        for m in d.get("must", []):
            if m.get("type") == "inner_bool":
                mm_or = m
        should = d.get("should", [])
        orinfo = (mm_or or {}).get("children") or should
        filt = [m for m in d.get("must", []) if m.get("type") in ("filter_term", "range")]
        lines.append(f"  DSL: must_types={[m.get('type') for m in d['must']]} filters={filt} must_not={d['must_not_count']} fn={d.get('functions')} boost={d.get('boost_mode')}")
        for o in orinfo:
            if isinstance(o, dict) and o.get("type") == "mm_or":
                lines.append(f"       OR-mm: q={o.get('q')!r} msm={o.get('msm')} fuzz={o.get('fuzz')} boost={o.get('boost')}")
        for h in r["hits"]:
            nn = h["nutrition_per_100g"]
            md = h["metadata"]
            cc = h["constraint_check"]
            ccs = f" CHECK[{cc['verdict']} {cc['metric']}]" if cc else ""
            lines.append(f"   #{h['rank']} [{h['score']:>7}] {(h['product_name'] or '')[:52]!r:<54} brand={(h['brand'] or '')[:18]!r:<20} ns={md['nutriscore_grade']} nova={md['nova_group']}")
            lines.append(f"        kcal={nn['energy-kcal']} P={nn['proteins']} sug={nn['sugars']} Na={nn['sodium']} salt={nn['salt']} fib={nn['fiber']} palm={h['contains_palm']}{ccs}")
            if cc and cc.get("verdict") in ("FAIL", "PARTIAL"):
                lines.append(f"        ING: {(h['ingredients'] or '')[:180]}")
    OUT_DIGEST.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_DIGEST} ({len(lines)} lines)")
    print(f"queries: {len(results)} unique")


if __name__ == "__main__":
    run()
