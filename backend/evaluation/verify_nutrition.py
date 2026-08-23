"""
Phase 6: Nutrition constraint verification (A-D).

Verifies returned documents actually satisfy the *indexed* constraint
semantics (the same rules SearchDocumentBuilder uses at index time), since
the DuckDB eval path uses looser flag inference than the live index.

Evidence written to audit_evidence/nutrition_verification.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.audit_harness import build_engine  # noqa: E402


def _nut_per_100g(entry):
    if isinstance(entry, dict):
        p = entry.get("per_100g")
        if p is not None:
            return float(p)
    return None


def _flag(p, name):
    return bool(p.attributes.get("flags", {}).get(name))


def check_high_protein(p, nutrition):
    if _flag(p, "is_high_protein"):
        return True, "is_high_protein=True"
    proteins = _nut_per_100g(nutrition.get("proteins"))
    if proteins is not None and proteins >= 10.0:
        return True, f"proteins={proteins}>=10"
    return False, f"proteins={proteins}"


def check_low_sugar(p, nutrition):
    if _flag(p, "is_low_sugar"):
        return True, "is_low_sugar=True"
    sugars = _nut_per_100g(nutrition.get("sugars"))
    if sugars is not None and 0 <= sugars <= 5.0:
        return True, f"sugars={sugars}<=5"
    return False, f"sugars={sugars}"


def check_min_protein(p, nutrition):
    proteins = _nut_per_100g(nutrition.get("proteins"))
    if proteins is not None and proteins >= 20.0:
        return True, f"proteins={proteins}>=20"
    return False, f"proteins={proteins}"


def check_max_calories(p, nutrition):
    kcal = _nut_per_100g(nutrition.get("energy-kcal"))
    if kcal is None:
        kcal = _nut_per_100g(nutrition.get("calories"))
    if kcal is not None and kcal <= 200.0:
        return True, f"kcal={kcal}<=200"
    return False, f"kcal={kcal}"


def verify_constraint(engine, label, query, checker, also_contains=None):
    """Run query and check each returned hit satisfies the constraint."""
    res = engine.search(query, size=10)
    row = {
        "id": label,
        "query": query,
        "total": res.total,
        "sample_size": len(res.hits),
        "checked": [],
        "passed": True,
    }
    for hit in res.hits:
        p = hit.product
        nutrition = (p.attributes or {}).get("nutrition", {})

        def _cat_hit(item):
            hay = " ".join(
                str(x or "")
                for x in (
                    item.product_name,
                    (item.attributes or {}).get("category"),
                    item.category,
                    item.search_text,
                )
            ).lower()
            return any(needle in hay for needle in also_contains) if also_contains else True

        ok_cat = _cat_hit(p)
        ok_constraint, reason = checker(p, nutrition)
        ok = ok_cat and ok_constraint if also_contains else ok_constraint
        row["checked"].append({
            "product_name": p.product_name,
            "category_ok": ok_cat,
            "constraint": reason,
            "ok": ok,
        })
        row["passed"] = row["passed"] and ok
    return row


def main():
    engine = build_engine("duckdb")
    cases = [
        ("A", "products with at least 20g protein", check_min_protein, None),
        ("B", "snacks under 200 calories", check_max_calories, None),
        ("C", "low sugar cereal", check_low_sugar, ["cereal"]),
        ("D", "high protein snacks", check_high_protein, ["snack"]),
    ]
    out = []
    for label, query, checker, contains in cases:
        row = verify_constraint(engine, label, query, checker, contains)
        out.append(row)
        print(f"[{label}] {query:<32} total={row['total']} passed={row['passed']}")

    out_dir = Path(__file__).parent / "audit_evidence"
    out_dir.mkdir(exist_ok=True, parents=True)
    p = out_dir / "nutrition_verification.json"
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {p}")
    return all(r["passed"] for r in out)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
