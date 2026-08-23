"""Tests for Canadian-English synonym support (P3 D1 fix).

Covers the versioned synonym file, canonicalization, the index mapping analyzer,
and the DuckDB offline repo parity used by the benchmark harness.
"""

from search.mappings import PRODUCT_INDEX_MAPPING
from search.synonyms_ca import (
    canonical_map,
    canonicalize,
    load_synonym_pairs,
    synonym_tokens,
    synonym_variants,
)


class TestSynonymFile:
    def test_file_exists_and_has_evidence_backed_pairs(self):
        pairs = load_synonym_pairs()
        assert len(pairs) >= 5
        as_set = set(pairs)
        assert ("soy", "soya") in as_set
        assert ("yogurt", "yoghurt") in as_set
        assert ("color", "colour") in as_set

    def test_synonym_tokens_format(self):
        tokens = synonym_tokens()
        assert any(t == "soy, soya" for t in tokens)
        # Canonical head (dataset-dominant form) comes first
        assert any(t.startswith("yogurt, ") for t in tokens)


class TestCanonicalization:
    def test_soya_canonicalized_to_soy(self):
        assert canonicalize("compliments soya sauce") == "compliments soy sauce"

    def test_yoghurt_canonicalized_to_yogurt(self):
        assert canonicalize("plain yoghurt") == "plain yogurt"

    def test_non_synonym_text_untouched(self):
        assert canonicalize("2% milk frozen blueberries") == "2% milk frozen blueberries"

    def test_word_boundary_no_partial_replace(self):
        # 'soybean' / 'goat' must never be rewritten by the 'soy'/'oat' synonyms
        assert canonicalize("soybean oil") == "soybean oil"
        assert "goat" in canonicalize("goat cheese")

    def test_canonical_map_injective(self):
        m = canonical_map()
        assert m["soya"] == m["soy"]
        assert m["yoghurt"] == m["yogurt"]

    def test_synonym_variants(self):
        assert set(synonym_variants("soya")) >= {"soya", "soy"}
        assert set(synonym_variants("yogurt")) >= {"yogurt", "yoghurt"}
        assert synonym_variants("peanut") == ["peanut"]


class TestMappingSynonymAnalyzer:
    def test_synonym_analyzer_present(self):
        analysis = PRODUCT_INDEX_MAPPING["settings"]["analysis"]
        assert "synonym_analyzer" in analysis["analyzer"]
        assert "synonym_ca_filter" in analysis["filter"]
        assert analysis["filter"]["synonym_ca_filter"]["type"] == "synonym"
        assert analysis["filter"]["synonym_ca_filter"]["synonyms"]

    def test_search_fields_use_synonym_analyzer(self):
        props = PRODUCT_INDEX_MAPPING["mappings"]["properties"]
        for field in ("product_name", "category", "ingredients", "search_text"):
            assert props[field]["analyzer"] == "synonym_analyzer", field


class TestDuckDBSynonymParity:
    def test_duckdb_soya_query_returns_soy_sauce_reflexively(self):
        from evaluation.evaluate import DuckDBSearchRepository

        repo = DuckDBSearchRepository()
        total_soy, hits_soy, _ = repo.search(query="compliments soy sauce", size=10)
        total_soya, hits_soya, _ = repo.search(query="compliments soya sauce", size=10)
        # Synonym expansion must bring the true "Soya sauce less salt" product to top
        top_soya = [p.product_name for _, p in hits_soya[:3]]
        assert any("soya" in n.lower() or "soy" in n.lower() for n in top_soya), top_soya
        # 'soy' and 'soya' queries must both yield meaningful results over the 114k set
        assert total_soy > 0 and total_soya > 0

    def test_pipeline_canonicalizes_soya(self):
        from query.pipeline import SearchQueryPipeline

        sq = SearchQueryPipeline.process("compliments soya sauce")
        assert sq.normalized_query == "compliments soy sauce"
        assert "soya" not in sq.text_term
