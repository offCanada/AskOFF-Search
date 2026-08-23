"""
AskOFF P3 reusable forensic search harness.

Captures machine-readable per-query evidence against the real engine:
NLP parse (normalized query, constraints, intent, modifiers, numeric filters,
recipe quantities, entities), the exact retrieval DSL, per-hit ranking score,
structured + classic relevance grades, reasons, and latency.

Usage (from backend/):
    python evaluation/audit_harness.py --repo opensearch --benchmark benchmark_queries.json
    python evaluation/audit_harness.py --repo duckdb    --benchmark benchmark_queries.json --out audit_evidence/pre.json

Evidence is written to backend/evaluation/audit_evidence/<name>.json
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grading import grade_item, knapsack_metrics

from query.pipeline import SearchQueryPipeline


def _attrs_hit(hit) -> Dict[str, Any]:
    p = hit.product
    return {
        "rank": None,
"score": round(float(getattr(hit, "score", None) or 0.0), 4),
        "id": p.id,
        "product_name": p.product_name,
        "brand": p.brand,
        "category": p.category,
        "flags": (p.attributes or {}).get("flags", {}),
        "nutrition": (p.attributes or {}).get("nutrition", {}),
    }


def build_engine(repo_name: str, **kwargs):
    # Mirror the API startup path so entity dictionaries are populated before
    # parsing (otherwise brand/category/ingredient extraction comes back empty).
    try:
        from query.dictionaries import load_dynamic_dictionaries
        load_dynamic_dictionaries()
    except Exception:
        pass
    if repo_name == "opensearch":
        from repositories.opensearch_repository import OpenSearchSearchRepository
        from retrieval.search_engine import SearchEngine

        repo = OpenSearchSearchRepository(**kwargs)
        return SearchEngine(repository=repo)
    from evaluation.evaluate import DuckDBSearchRepository
    from retrieval.search_engine import SearchEngine

    parquet = kwargs.pop("parquet", None)
    repo = DuckDBSearchRepository(parquet_path=parquet) if parquet else DuckDBSearchRepository()
    return SearchEngine(repository=repo)


def capture_query(
    engine,
    query: str,
    item: Optional[Dict[str, Any]] = None,
    size: int = 10,
    gate: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one query end-to-end and return a full evidence record."""
    item = item or {"query": query, "type": "generic_search"}
    parses = {"query": query}
    final_sq = None
    try:
        final_sq = SearchQueryPipeline.process(query, size=size)
        parses.update(
            {
                "original_query": final_sq.original_query,
                "normalized_query": final_sq.normalized_query,
                "text_term": final_sq.text_term,
                "intent": final_sq.intent,
                "entities": final_sq.entities,
                "filters": final_sq.filters,
                "numeric_filters": final_sq.numeric_filters,
                "modifiers": final_sq.modifiers,
                "recipe_quantities": final_sq.recipe_quantities,
            }
        )
    except Exception as exc:  # noqa: BLE001
        parses["pipeline_error"] = f"{type(exc).__name__}: {exc}"

    start = time.time()
    try:
        res = engine.search(query, size=size, explain=True)
        latency_ms = (time.time() - start) * 1000
        if final_sq is not None and gate:
            final_sq.filters = getattr(final_sq, "filters", {})
    except Exception as exc:  # noqa: BLE001
        if gate == "engine_only":
            raise
        return {
            **parses,
            "search_error": f"{type(exc).__name__}: {exc}",
            "latency_ms": (time.time() - start) * 1000,
            "total": 0,
            "hits": [],
            "covered": False,
        }

    hits = [{"score": round(float(hit.score or 0.0), 4), "product": hit.product} for hit in res.hits]

    dsl = None
    if res.search_query and isinstance(res.search_query, dict):
        dsl = res.search_query.get("opensearch_query")
        if dsl is None and gate == "engine_only":
            dsl = getattr(res.search_query, "metadata", {}).get("opensearch_query")

    evidence_hits = []
    relevances_structured = []
    relevances_classic = []
    reasons_dump = []
    for rank, entry in enumerate(hits, 1):
        p = entry["product"]
        graded = grade_item(p, item, mode="structured")
        classic = grade_item(p, item, mode="classic")
        relevances_structured.append(graded["rel"])
        relevances_classic.append(classic["rel"])
        reasons_dump.append({"rank": rank, "structured": graded["reasons"], "classic_rel": classic["rel"], "classic_reasons": classic.get("reasons")})
        evidence_hits.append(
            {
                "rank": rank,
                "score": entry["score"],
                **{k: _attrs_hit(type("H", (), {"product": p}))[k] for k in ("id", "product_name", "brand", "category", "flags")},
                "structured_rel": graded["rel"],
                "classic_rel": classic["rel"],
                "structured_reasons": graded["reasons"],
                "matched_groups": graded.get("matched_groups"),
            }
        )

    metrics_struct = knapsack_metrics(relevances_structured, k=10)
    metrics_classic = knapsack_metrics(relevances_classic, k=10)

    def _round_dict(d):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}

    return {
        **parses,
        "total": res.total,
        "took_ms": res.took_ms,
        "latency_ms": round(latency_ms, 2),
        "dsl": dsl,
        "hits": evidence_hits,
        "metrics_structured": _round_dict(metrics_struct),
        "metrics_classic": _round_dict(metrics_classic),
    }


def run_benchmark_evidence(
    repo_name: str = "opensearch",
    benchmark_path: Optional[str] = None,
    out_name: str = "evidence",
    size: int = 10,
    only_queries: Optional[List[str]] = None,
) -> Dict[str, Any]:
    engine = build_engine(repo_name)
    if benchmark_path is None:
        benchmark_path = Path(__file__).parent / "benchmark_queries.json"
    else:
        cand = Path(benchmark_path).resolve()
        if not cand.exists():
            cand = Path(__file__).parent / Path(benchmark_path).name
        benchmark_path = cand
    with open(benchmark_path, "r", encoding="utf-8") as f:
        benchmark = json.load(f)

    records = []
    for item in benchmark:
        q = item.get("query", "")
        if only_queries and q not in only_queries:
            continue
        record = capture_query(engine, q, item=item, size=size)
        record["benchmark_item"] = item
        records.append(record)

    out_dir = Path(__file__).parent / "audit_evidence"
    out_dir.mkdir(exist_ok=True, parents=True)
    out_path = out_dir / f"{out_name}.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote evidence: {out_path} ({len(records)} queries)")

    struct_metrics = knapsack_metrics_agg(records)
    classic_metrics = knapsack_metrics_agg_classic(records)
    return {"evidence_file": str(out_path), "records": records,
            "structured": struct_metrics, "classic": classic_metrics}


def knapsack_metrics_agg(records: List[Dict[str, Any]]) -> Dict[str, float]:

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    p5 = avg([r["metrics_structured"]["p5"] for r in records])
    p10 = avg([r["metrics_structured"]["p10"] for r in records])
    ndcg = avg([r["metrics_structured"]["ndcg"] for r in records])
    mrr = avg([r["metrics_structured"]["mrr"] for r in records])
    return {"p5": p5, "p10": p10, "ndcg": ndcg, "mrr": mrr}


def knapsack_metrics_agg_classic(records: List[Dict[str, Any]]) -> Dict[str, float]:
    def avg(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    p5 = avg([r["metrics_classic"]["p5"] for r in records])
    p10 = avg([r["metrics_classic"]["p10"] for r in records])
    ndcg = avg([r["metrics_classic"]["ndcg"] for r in records])
    mrr = avg([r["metrics_classic"]["mrr"] for r in records])
    return {"p5": p5, "p10": p10, "ndcg": ndcg, "mrr": mrr}


if __name__ == "__main__":
    argv = sys.argv[1:]
    repo = "opensearch"
    bench = None
    out = "evidence"
    size = 10
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    if "--benchmark" in argv:
        bench = argv[argv.index("--benchmark") + 1]
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    if "--size" in argv:
        size = int(argv[argv.index("--size") + 1])
    result = run_benchmark_evidence(repo_name=repo, benchmark_path=bench, out_name=out, size=size)
    print("STRUCTURED :", result["structured"])
    print("CLASSIC    :", result["classic"])
