"""
AskOFF P3 Search Evaluation Harness.
Computes Precision@5, Precision@10, NDCG@10, and MRR across the 35-query benchmark.
Supports both live OpenSearch clusters and the local 114k Parquet engine.
"""

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure backend modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from models.search_document import SearchDocument
from repositories.opensearch_repository import OpenSearchSearchRepository
from retrieval.search_engine import SearchEngine
from search.synonyms_ca import canonicalize


class DuckDBSearchRepository:
    """
    Local in-memory / Parquet search repository implementing the exact same
    tiered multi-match lexical scoring and filtering rules as OpenSearchSearchRepository.
    Used for local benchmarking on the 114k dataset when an external OpenSearch cluster is offline.
    """
    def __init__(self, parquet_path: str = "data/raw/normalized.parquet") -> None:
        self.parquet_path = parquet_path
        self.con = duckdb.connect()
        # Verify parquet exists
        if not Path(parquet_path).exists():
            fallbacks = [
                Path("backend/data/processed/normalized.parquet"),
                Path("data/processed/normalized.parquet"),
            ]
            for fallback in fallbacks:
                if fallback.exists():
                    self.parquet_path = str(fallback)
                    break

    def search(
        self,
        query: str,
        filters: Dict[str, Any] = None,
        numeric_filters: List[Dict[str, Any]] = None,
        modifiers: List[str] = None,
        size: int = 20,
        from_: int = 0,
        explain: bool = False
    ) -> Tuple[int, List[Tuple[float, SearchDocument]], dict]:
        filters = filters or {}
        numeric_filters = numeric_filters or []
        modifiers = modifiers or []

        # Load candidate rows matching query terms or filters
        tokens = [t.lower() for t in query.split() if len(t) > 1] if query else []

        # Build SQL where conditions for hard filters & candidate matching
        where_clauses = []

        if "brand" in filters and filters["brand"]:
            b_val = filters["brand"].replace("'", "''").lower()
            where_clauses.append(f"(lower(brands_clean) LIKE '%{b_val}%' OR lower(brands) LIKE '%{b_val}%')")
        if "category" in filters and filters["category"]:
            c_val = filters["category"].replace("'", "''").lower()
            where_clauses.append(f"(lower(categories_clean) LIKE '%{c_val}%' OR lower(categories) LIKE '%{c_val}%')")
        if "ingredients" in filters and filters["ingredients"]:
            i_val = filters["ingredients"].replace("'", "''").lower()
            where_clauses.append(f"(lower(ingredients_clean) LIKE '%{i_val}%' OR lower(ingredients_text) LIKE '%{i_val}%')")
        if filters.get("is_palm_oil_free") is True:
            where_clauses.append("(lower(ingredients_clean) NOT LIKE '%palm oil%' AND lower(ingredients_text) NOT LIKE '%palm oil%')")

        # If we have query tokens, candidates MUST match at least one token
        if tokens:
            token_conditions = []
            from search.synonyms_ca import synonym_variants
            for t in tokens:
                variants = synonym_variants(t)
                variant_clauses = []
                for v in variants:
                    v_escaped = v.replace("'", "''")
                    variant_clauses.append(
                        f"(lower(product_name_clean) LIKE '%{v_escaped}%' "
                        f"OR lower(brands_clean) LIKE '%{v_escaped}%' "
                        f"OR lower(categories_clean) LIKE '%{v_escaped}%' "
                        f"OR lower(ingredients_clean) LIKE '%{v_escaped}%' "
                        f"OR lower(search_text) LIKE '%{v_escaped}%')"
                    )
                token_conditions.append("(" + " OR ".join(variant_clauses) + ")")
            where_clauses.append("(" + " OR ".join(token_conditions) + ")")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Retrieve candidates from the 114k Parquet dataset
        fetch_limit = 2000
        sql = f"""
            SELECT code, product_name_clean, brands_clean, categories_clean, ingredients_clean,
                   nutriments, nutriscore_grade, nova_group, ecoscore_grade, completeness, search_text
            FROM '{self.parquet_path}'
            WHERE {where_sql}
            LIMIT {fetch_limit}
        """
        rows = self.con.execute(sql).fetchall()

        # Score candidates with BM25-like field weighting & tiered matching
        scored_docs = []
        for row in rows:
            code = str(row[0])
            name = str(row[1] or "")
            brand = str(row[2] or "")
            cat = str(row[3] or "")
            ing = str(row[4] or "")
            nut_raw = str(row[5] or "")
            ns = str(row[6]) if row[6] is not None else None
            nova = int(row[7]) if row[7] is not None else None
            eco = str(row[8]) if row[8] is not None else None
            comp = float(row[9] or 0.0)
            search_text = str(row[10] or "")

            name_lower = name.lower()
            brand_lower = brand.lower()
            cat_lower = cat.lower()
            ing_lower = ing.lower()
            search_lower = search_text.lower()

            # Canonicalize haystacks so synonymous spellings ('yoghurt') score same as 'yogurt'
            name_lower = canonicalize(name_lower)
            brand_lower = canonicalize(brand_lower)
            cat_lower = canonicalize(cat_lower)
            ing_lower = canonicalize(ing_lower)
            search_lower = canonicalize(search_lower)

            # Parse nutriments (mirrors SearchDocumentBuilder thresholds)
            from repositories.opensearch_repository import NUTRIENT_FIELD_MAP
            from utils.off_parser import parse_nutriments
            parsed_nutriments = parse_nutriments(nut_raw)

            def per_100g(key):
                entry = parsed_nutriments.get(key)
                if isinstance(entry, dict):
                    p = entry.get("per_100g")
                    if p is not None:
                        return float(p)
                return -1.0

            # Dietary flags inference (same rules as SearchDocumentBuilder)
            is_organic = "organic" in cat_lower or "organic" in ing_lower or "bio" in cat_lower or "bio" in ing_lower
            is_vegan = "vegan" in cat_lower or "vegan" in ing_lower
            is_vegetarian = "vegetarian" in cat_lower or "vegetarian" in ing_lower or is_vegan
            is_palm_oil_free = "palm oil" not in ing_lower
            is_high_protein = "high protein" in cat_lower or (per_100g("proteins") >= 10.0)
            is_low_sugar = (
                "low sugar" in cat_lower or "sugar free" in cat_lower or "no sugar" in cat_lower
                or (0 <= per_100g("sugars") <= 5.0)
            )
            is_gluten_free = "gluten free" in cat_lower or "gluten-free" in cat_lower or "sans gluten" in cat_lower
            is_low_sodium = (
                "low sodium" in cat_lower or "low salt" in cat_lower or "no salt" in cat_lower
                or (0 <= per_100g("sodium") <= 0.12)
            )
            is_lactose_free = (
                "lactose free" in cat_lower or "dairy free" in cat_lower or "sans lactose" in cat_lower
            )

            # Check boolean filter flags
            if filters.get("is_organic") is True and not is_organic:
                continue
            if filters.get("is_vegan") is True and not is_vegan:
                continue
            if filters.get("is_vegetarian") is True and not is_vegetarian:
                continue
            if filters.get("is_gluten_free") is True and not is_gluten_free:
                continue
            if filters.get("is_high_protein") is True and not is_high_protein:
                continue
            if filters.get("is_low_sugar") is True and not is_low_sugar:
                continue
            if filters.get("is_low_sodium") is True and not is_low_sodium:
                continue
            if filters.get("is_lactose_free") is True and not is_lactose_free:
                continue

            # Parse nutriments
            from utils.off_parser import parse_nutriments
            parsed_nutriments = parse_nutriments(nut_raw)

            # Check numeric nutrient filters (e.g. at least 20g protein, under 200 calories)
            if numeric_filters:
                matches_numeric = True
                for nf in numeric_filters:
                    nut_key = nf.get("nutrient", "")
                    mapped_key = NUTRIENT_FIELD_MAP.get(nut_key, nut_key)
                    op = nf.get("operator", "")
                    target_val = nf.get("value", 0.0)
                    basis = nf.get("comparison_basis", "per_100g")

                    nutrient_entry = parsed_nutriments.get(mapped_key, {})
                    actual_val = nutrient_entry.get("per_100g") if basis == "per_100g" else nutrient_entry.get("value")
                    if actual_val is None:
                        matches_numeric = False
                        break
                    if op == "gte" and actual_val < target_val:
                        matches_numeric = False
                        break
                    if op == "lte" and actual_val > target_val:
                        matches_numeric = False
                        break
                if not matches_numeric:
                    continue

            # Calculate score
            score = 0.0
            query_lower = query.lower() if query else ""

            if query_lower:
                # 1. Exact Phrase match (10.0)
                if query_lower in name_lower:
                    score += 10.0 * 3.0
                elif query_lower in brand_lower:
                    score += 10.0 * 2.0
                elif query_lower in cat_lower:
                    score += 10.0 * 1.5
                elif query_lower in search_lower:
                    score += 10.0 * 1.0

                # 2. Token matches across fields
                match_count = 0
                for t in tokens:
                    t_score = 0.0
                    if t in name_lower:
                        t_score = max(t_score, 3.0)
                    if t in brand_lower:
                        t_score = max(t_score, 2.0)
                    if t in cat_lower:
                        t_score = max(t_score, 1.5)
                    if t in ing_lower:
                        t_score = max(t_score, 1.2)
                    if t in search_lower:
                        t_score = max(t_score, 1.0)

                    if t_score > 0:
                        score += t_score * 2.0
                        match_count += 1

                # 3. AND Match boost (5.0 if all tokens matched)
                if tokens and match_count == len(tokens):
                    score += 5.0

                # If no tokens matched and no phrase match, skip unless query is empty
                if score <= 0:
                    continue
            else:
                # Filter-only query
                score = 1.0

            # 4. Modifiers boost (e.g. frozen, fresh, salted)
            if modifiers:
                for mod in modifiers:
                    if mod.lower() in name_lower:
                        score += 5.0

            # 5. Completeness boost
            score += comp * 0.15

            doc = SearchDocument(
                id=code,
                product_name=name,
                brand=brand if brand else None,
                category=cat if cat else None,
                ingredients=ing if ing else None,
                attributes={
                    "nutrition": parsed_nutriments,
                    "flags": {
                        "is_organic": is_organic,
                        "is_vegan": is_vegan,
                        "is_vegetarian": is_vegetarian,
                        "is_palm_oil_free": is_palm_oil_free,
                        "is_high_protein": is_high_protein,
                        "is_low_sugar": is_low_sugar,
                        "is_low_sodium": is_low_sodium,
                        "is_gluten_free": is_gluten_free,
                        "is_lactose_free": is_lactose_free,
                    }
                },
                metadata={
                    "nutriscore_grade": ns,
                    "nova_group": nova,
                    "ecoscore_grade": eco,
                    "completeness": comp,
                },
                search_text=search_text,
                semantic_document=""
            )
            scored_docs.append((score, doc))

        # Sort descending by score
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        total = len(scored_docs)
        page_results = scored_docs[from_:from_ + size]
        return total, page_results, {}

    def get_by_id(self, doc_id: str) -> Optional[SearchDocument]:
        safe_id = doc_id.replace("'", "''")
        sql = f"""
            SELECT code, product_name_clean, brands_clean, categories_clean, ingredients_clean,
                   nutriments, nutriscore_grade, nova_group, ecoscore_grade, completeness, search_text
            FROM '{self.parquet_path}'
            WHERE code = '{safe_id}'
            LIMIT 1
        """
        rows = self.con.execute(sql).fetchall()
        if not rows:
            return None
        r = rows[0]
        from utils.off_parser import parse_nutriments
        return SearchDocument(
            id=str(r[0]),
            product_name=str(r[1] or ""),
            brand=str(r[2]) if r[2] else None,
            category=str(r[3]) if r[3] else None,
            ingredients=str(r[4]) if r[4] else None,
            attributes={"nutrition": parse_nutriments(str(r[5] or ""))},
            metadata={"nutriscore_grade": str(r[6]) if r[6] else None, "completeness": float(r[9] or 0.0)},
            search_text=str(r[10] or ""),
            semantic_document=""
        )

    def get_autocomplete(self, query: str, size: int = 5) -> List[str]:
        if not query:
            return []
        safe_q = query.replace("'", "''").lower()
        sql = f"""
            SELECT DISTINCT product_name_clean
            FROM '{self.parquet_path}'
            WHERE lower(product_name_clean) LIKE '{safe_q}%'
            LIMIT {size}
        """
        rows = self.con.execute(sql).fetchall()
        return [r[0] for r in rows if r[0]]


def evaluate_product(product: SearchDocument, item: Dict[str, Any]) -> int:
    """
    Assigns relevance score (0, 1, 2, 3) to a product for a given benchmark query.
    3 = Perfect / Highly Relevant (exact intent, brand if required, keywords, flags, no bad words)
    2 = Relevant (keywords matched, flags satisfied)
    1 = Marginally Relevant
    0 = Irrelevant
    """
    name = (product.product_name or "").lower()
    brand = (product.brand or "").lower()
    text = (product.search_text or "").lower()
    flags = product.attributes.get("flags", {}) if product.attributes else {}

    # Check disallowed keywords
    for disallowed in item.get("disallowed_keywords", []):
        if disallowed.lower() in name or disallowed.lower() in text:
            return 0

    # Check required flags
    for req_flag, req_val in item.get("required_flags", {}).items():
        if flags.get(req_flag) != req_val:
            return 0

    # Check required brand if specified
    req_brand = item.get("relevant_brand")
    if req_brand and req_brand.lower() not in brand and req_brand.lower() not in name:
        return 0

    # Check relevant keywords
    keywords = item.get("relevant_keywords", [])
    if not keywords:
        return 3

    matched_kw = sum(1 for kw in keywords if kw.lower() in name or kw.lower() in text or kw.lower() in brand)
    kw_ratio = matched_kw / len(keywords)

    if kw_ratio == 1.0:
        # Check if all keywords are in the product name itself
        all_in_name = all(kw.lower() in name for kw in keywords)
        return 3 if all_in_name else 2
    elif kw_ratio >= 0.5:
        return 1
    else:
        return 0


def calculate_dcg(relevances: List[int], k: int = 10) -> float:
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        # Standard formula: (2^rel - 1) / log2(i + 2)
        gain = (2 ** rel) - 1
        discount = math.log2(i + 2)
        dcg += gain / discount
    return dcg


def run_benchmark():
    benchmark_file = Path(__file__).parent / "benchmark_queries.json"
    with open(benchmark_file, "r", encoding="utf-8") as f:
        benchmark_queries = json.load(f)

    print("=" * 85)
    print("ASK-OFF P3 SEARCH & RETRIEVAL RELEVANCE EVALUATION BENCHMARK")
    print(f"Total Benchmark Queries: {len(benchmark_queries)}")
    print("=" * 85)

    # Initialize search engine (local DuckDB repository)
    repo_name = "duckdb"
    if "--repo" in sys.argv:
        repo_name = sys.argv[sys.argv.index("--repo") + 1]
    if repo_name == "opensearch":
        print("BACKEND: LIVE OpenSearch (full 114k index)")
        repo = OpenSearchSearchRepository()
    else:
        print("BACKEND: Local DuckDB (114k Parquet)")
        repo = DuckDBSearchRepository()
    engine = SearchEngine(repository=repo)

    p5_list = []
    p10_list = []
    ndcg10_list = []
    mrr_list = []
    latencies = []

    category_metrics = {}

    for idx, item in enumerate(benchmark_queries, 1):
        q = item["query"]
        q_type = item["type"]

        start_time = time.time()
        res = engine.search(q, size=10)
        latency_ms = (time.time() - start_time) * 1000
        latencies.append(latency_ms)

        relevances = []
        for hit in res.hits:
            rel = evaluate_product(hit.product, item)
            relevances.append(rel)

        # Pad with 0 if fewer than 10 hits
        while len(relevances) < 10:
            relevances.append(0)

        # Precision@5 (rel >= 2)
        p5 = sum(1 for r in relevances[:5] if r >= 2) / 5.0
        # Precision@10 (rel >= 2)
        p10 = sum(1 for r in relevances[:10] if r >= 2) / 10.0

        # NDCG@10
        ideal_relevances = sorted(relevances[:10], reverse=True)
        dcg = calculate_dcg(relevances, k=10)
        idcg = calculate_dcg(ideal_relevances, k=10)
        ndcg10 = (dcg / idcg) if idcg > 0 else 0.0

        # MRR (rank of first result with rel >= 2)
        mrr = 0.0
        for rank, r in enumerate(relevances, 1):
            if r >= 2:
                mrr = 1.0 / rank
                break

        p5_list.append(p5)
        p10_list.append(p10)
        ndcg10_list.append(ndcg10)
        mrr_list.append(mrr)

        # Record by category
        if q_type not in category_metrics:
            category_metrics[q_type] = {"p5": [], "p10": [], "ndcg10": [], "mrr": []}
        category_metrics[q_type]["p5"].append(p5)
        category_metrics[q_type]["p10"].append(p10)
        category_metrics[q_type]["ndcg10"].append(ndcg10)
        category_metrics[q_type]["mrr"].append(mrr)

        top_hit_name = res.hits[0].product.product_name if res.hits else "NO HITS"
        print(f"[{idx:02d}/{len(benchmark_queries):02d}] {q:<38} | P@5: {p5:4.2f} | P@10: {p10:4.2f} | NDCG@10: {ndcg10:4.2f} | Top Hit: {top_hit_name[:30]}")

    mean_p5 = sum(p5_list) / len(p5_list)
    mean_p10 = sum(p10_list) / len(p10_list)
    mean_ndcg10 = sum(ndcg10_list) / len(ndcg10_list)
    mean_mrr = sum(mrr_list) / len(mrr_list)

    latencies.sort()
    avg_latency = sum(latencies) / len(latencies)
    p50_latency = latencies[len(latencies) // 2]
    p95_latency = latencies[int(len(latencies) * 0.95)]

    print("\n" + "=" * 85)
    print("CATEGORY BREAKDOWN")
    print("=" * 85)
    print(f"{'Category':<22} | {'Count':<5} | {'P@5':<8} | {'P@10':<8} | {'NDCG@10':<8} | {'MRR':<8}")
    print("-" * 85)
    for cat_name, metrics in category_metrics.items():
        c_cnt = len(metrics["p5"])
        c_p5 = sum(metrics["p5"]) / c_cnt
        c_p10 = sum(metrics["p10"]) / c_cnt
        c_ndcg = sum(metrics["ndcg10"]) / c_cnt
        c_mrr = sum(metrics["mrr"]) / c_cnt
        print(f"{cat_name:<22} | {c_cnt:<5} | {c_p5:6.2f}   | {c_p10:6.2f}   | {c_ndcg:6.2f}   | {c_mrr:6.2f}")

    print("\n" + "=" * 85)
    print("FINAL SUMMARY METRICS (35 Benchmark Queries on 114k Canada OFF Dataset)")
    print("=" * 85)
    print(f"  Mean Precision@5  : {mean_p5 * 100:6.2f}%")
    print(f"  Mean Precision@10 : {mean_p10 * 100:6.2f}%")
    print(f"  Mean NDCG@10      : {mean_ndcg10 * 100:6.2f}%")
    print(f"  Mean MRR          : {mean_mrr:6.3f}")
    print(f"  Search Latency    : Avg: {avg_latency:.2f}ms | p50: {p50_latency:.2f}ms | p95: {p95_latency:.2f}ms")
    print("=" * 85)

    return {
        "mean_p5": mean_p5,
        "mean_p10": mean_p10,
        "mean_ndcg10": mean_ndcg10,
        "mean_mrr": mean_mrr,
        "avg_latency_ms": avg_latency,
        "p50_latency_ms": p50_latency,
        "p95_latency_ms": p95_latency,
    }


if __name__ == "__main__":
    run_benchmark()
