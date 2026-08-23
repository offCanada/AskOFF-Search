# AskOFF Backend — Codebase Guide

This document is the single, authoritative architectural and engineering reference for the AskOFF search and retrieval backend. It is designed to enable new engineers, Open Food Facts contributors, and maintainers to understand the system's design, operational lifecycle, query semantics, and codebase organization without needing to read every source file.

---

## 1. Purpose

AskOFF is a high-performance natural-language search and retrieval engine built for Open Food Facts Canada. It enables users to discover, compare, and inspect ~114,453 Canadian food products using conversational queries, dietary constraints, nutrition thresholds, recipe quantities, and brand/category filters.

The core challenge AskOFF solves is bridging the semantic gap between unstructured consumer language (e.g. *"500 mL frozen blueberries"*, *"low sugar cereal"*, *"products with at least 20g protein"*) and the heterogeneous, semi-structured product catalog of Open Food Facts without relying on costly black-box LLM calls at search time.

---

## 2. Scope

AskOFF P3 focuses on deterministic, transparent, and low-latency lexical-semantic retrieval:
- **In Scope (Current P3 Capabilities)**:
  - OpenSearch 2.x BM25 lexical retrieval with field-weighted ranking.
  - Canadian Open Food Facts dataset (~114,453 products) ingestion via DuckDB and Parquet.
  - Rule-based natural language query understanding (normalization, tokenization, entity extraction, dietary constraint extraction).
  - Numeric nutrition filtering (per-100g basis, comparison operators $\ge, \le$, calories, protein, sugars, sodium, salt).
  - Recipe ingredient retrieval (decoupling recipe quantities like `500 mL`, `2 cups` from search keywords).
  - Typo tolerance and Canadian bilingual synonym mapping (`soya sauce` $\leftrightarrow$ `soy sauce`).
  - Zero-downtime blue/green index lifecycle (versioned indexing, validation, alias promotion, rollback).
  - FastAPI asynchronous search API, health/readiness probes, and evaluation harnesses.
- **Out of Scope (Intentionally Deferred)**:
  - Vector embeddings, semantic dense retrieval, hybrid fusion, cross-encoder reranking, and RAG pipelines.
  - Automatic core-product/variant clustering without trusted canonical barcodes.

---

## 3. High-Level Architecture

AskOFF operates as two decoupled pipelines: an offline/batch **Data Ingestion & Indexing Pipeline** and an online **Search & Query Processing Pipeline**.

```
[ OFFLINE INGESTION PIPELINE ]
Open Food Facts Parquet (114k rows)
       ↓
OFFAdapter (DuckDB Stream)
       ↓
RawProduct (Pydantic Model)
       ↓
SearchDocumentBuilder (Entity & Flag Inference)
       ↓
SearchDocument (Canonical Pydantic Schema)
       ↓
OpenSearch Indexer (Bulk API, Batch Size 1000)
       ↓
Physical Index (askoff_products_YYYYMMDD_HHMMSS)
       ↓
Validation & Alias Promotion → [ askoff_products (Alias) ]

----------------------------------------------------------------------

[ ONLINE SEARCH PIPELINE ]
User Query (HTTP GET /search?q=...)
       ↓
FastAPI Router (Input Validation, Sanitization)
       ↓
SearchEngine & SearchQueryPipeline
       ↓
1. QueryNormalizer (Lowercase, punctuation, whitespace)
2. Synonym Canonicalization (synonyms_ca.py)
3. ConstraintExtractor (Recipe quantities, dietary flags, numeric nutrition)
4. EntityExtractor (Dynamic dictionaries: brands, categories, ingredients)
5. IntentDetector (Generic search, brand search, category search)
       ↓
SearchQuery (Structured Representation)
       ↓
OpenSearchSearchRepository
       ↓
Construct OpenSearch Bool DSL Query
(Phrase Match + AND Multi-Match + Tiered Fuzzy Match + Must Filters)
       ↓
OpenSearch Cluster (BM25 + Function Score Completeness Boost)
       ↓
Hits & Product Documents
       ↓
SearchResponse (JSON: total, took_ms, hits, parsed search_query)
```

---

## 4. Repository Structure

```text
backend/
├── adapters/          # Data extractors for raw sources (OFF Parquet, DuckDB, Reference DB)
├── api/               # FastAPI application, route handlers, dependencies, lifespan
├── builders/          # Transformations from RawProduct to Canonical SearchDocument
├── config/            # Pydantic BaseSettings and environment configuration
├── data/              # Static entity dictionaries and local data storage
├── evaluation/        # Benchmark datasets, evaluation harnesses, metrics calculation
├── models/            # Pydantic domain models (RawProduct, SearchDocument, SearchHit)
├── pipeline/          # Batch ingestion runner, batch loaders, Parquet writers
├── query/             # Query understanding (normalizer, tokenizer, extractors, pipeline)
├── repositories/      # OpenSearch and storage repository implementations
├── retrieval/         # Core search engine, ranking weights, filter managers
├── scripts/           # Production CLI lifecycle scripts (create, index, validate, promote)
├── search/            # OpenSearch client, mappings, index lifecycle, Canadian synonyms
├── tests/             # Pytest automated test suite (unit, integration, evaluation)
└── utils/             # OFF text parsers, multilingual extractors, string helpers
```

### Directory Responsibilities & Boundaries
- `adapters/`: Reads external datasets. Must only yield `RawProduct` instances; must not contain OpenSearch or ranking logic.
- `builders/`: Pure transformation logic converting `RawProduct` to `SearchDocument`. Infers boolean dietary flags and normalizes nutrition structures.
- `query/`: Query understanding module. Translates a raw query string into a structured `SearchQuery` object. No direct database or network dependencies.
- `repositories/`: Database abstraction layer. Translates `SearchQuery` into OpenSearch DSL queries.
- `retrieval/`: Business logic orchestrator (`SearchEngine`). Coordinates `query` parsing and `repositories` execution.

---

## 5. Data Flow

1. **Parquet Source**: `data/raw/normalized.parquet` contains 114,453 Canadian OFF products with columns: `code`, `product_name`, `brands`, `categories`, `ingredients_text`, `nutriments`, `nutriscore_grade`, `nova_group`, `ecoscore_grade`, `completeness`.
2. **Adapter Streaming**: `OFFAdapter.extract_raw_products()` queries DuckDB in streaming chunks defined by `settings.pipeline_batch_size` (default: 1,000) to maintain minimal memory overhead.
3. **Field Normalization**: `off_parser.py` safely extracts text from multilingual strings (preferring `en`, `main`, `fr`) and normalizes the JSON `nutriments` object.
4. **Document Construction**: `SearchDocumentBuilder` derives boolean flags (`is_organic`, `is_vegan`, `is_vegetarian`, `is_palm_oil_free`, `is_high_protein`, `is_low_sugar`, `is_low_sodium`, `is_gluten_free`, `is_lactose_free`) and concatenates searchable text into `search_text`.
5. **OpenSearch Indexing**: `indexer.py` batches documents and sends them via the OpenSearch `helpers.bulk` API with automatic retry and error reporting.

---

## 6. Query Flow

1. **HTTP Request**: Client requests `GET /search?q=500+mL+frozen+blueberries&size=20`.
2. **Pipeline Execution**:
   - `QueryNormalizer.normalize("500 mL frozen blueberries")` $\rightarrow$ `"500 ml frozen blueberries"`.
   - `synonyms_ca.canonicalize(...)` canonicalizes synonyms (e.g. `soya` $\rightarrow$ `soy`).
   - `ConstraintExtractor.extract(...)`:
     - Extracts `recipe_quantities`: `[{"value": 500.0, "unit": "ml"}]`.
     - Extracts `modifiers`: `["frozen"]`.
     - Strips quantity tokens to yield `cleaned_query`: `"frozen blueberries"`.
   - `EntityExtractor.extract(...)` matches known entities against preloaded dictionary sets.
   - `IntentDetector.detect(...)` classifies intent (`generic_search`, `brand_search`, `category_search`).
3. **Repository Execution**:
   - `OpenSearchSearchRepository.search(...)` builds the query DSL:
     - Exact phrase match (`product_name^3.0`, `brand^2.0`, `category^1.5`, `ingredients^1.2`, `search_text^1.0`, boost: 10.0).
     - AND operator multi-match (boost: 5.0).
     - Tiered fuzzy multi-match with `AUTO` fuzziness (boost: 0.5).
     - Function score boost using metadata completeness: `completeness * 0.15`.
4. **Execution & Deserialization**: Hits are returned from OpenSearch, deserialized into `SearchDocument` models, and wrapped in `SearchResponse`.

---

## 7. Query Understanding

### Normalization & Synonyms
- Case folding (lowercase), punctuation stripping (preserving decimal points and percentages like `2% milk`), whitespace collapsing.
- Canadian bilingual and spelling normalization (`synonyms_ca.py`):
  - `soya sauce` $\leftrightarrow$ `soy sauce`
  - `yoghurt` $\leftrightarrow$ `yogurt`
  - `cacao` $\leftrightarrow$ `cocoa`

### Constraint & Entity Extraction
- **Dietary Keywords**: `organic`, `bio`, `vegan`, `vegetarian`, `palm oil free`, `gluten free`, `lactose free`.
- **Nutrition Threshold Keywords**:
  - `high protein` $\rightarrow$ `is_high_protein: true` (protein $\ge 10.0\text{g}/100\text{g}$)
  - `low sugar` / `sugar free` $\rightarrow$ `is_low_sugar: true` (sugars $\le 5.0\text{g}/100\text{g}$)
  - `low sodium` / `low salt` $\rightarrow$ `is_low_sodium: true` (sodium $\le 0.12\text{g}/100\text{g}$)
- **Numeric Regex Extraction**:
  - `under 200 calories` $\rightarrow$ `nutrient: "calories", operator: "lte", value: 200.0`
  - `at least 20g protein` $\rightarrow$ `nutrient: "protein", operator: "gte", value: 20.0`

---

## 8. Retrieval

OpenSearch query construction employs a tiered `should` scoring architecture:
1. **Tier 1 (Phrase Match)**: `multi_match` with `type: "phrase"` across all fields. Surfaces exact sequence matches first.
2. **Tier 2 (AND Match)**: `multi_match` with `operator: "and"`. Ensures documents containing all query tokens rank high.
3. **Tier 3 (Fuzzy Match)**: `multi_match` with `fuzziness: "AUTO"`, `operator: "or"`, and tiered `minimum_should_match`:
   - 1 token: `1`
   - 2 tokens: `2` (both tokens required, preventing single-token noise)
   - $3+$ tokens: `max(2, n // 2 + 1)`
4. **Hard Filters (`must` / `filter`)**:
   - Explicit brand/category/ingredient filters when detected.
   - Numeric range filters (`attributes.nutrition.{nutrient}.per_100g`).
   - Negation filters (`must_not` matching ingredients for `palm oil free`).

---

## 9. Ranking

Ranking score calculation combines OpenSearch BM25 term relevance with product metadata completeness:

$$\text{FinalScore} = \text{BM25Score} + (\text{completeness} \times 0.15) + \text{ModifierBoost}$$

- **Field Boosts**:
  - `product_name`: $3.0$
  - `brand`: $2.0$
  - `category`: $1.5$
  - `ingredients`: $1.2$
  - `search_text`: $1.0$
- **Clause Boosts**:
  - Phrase match: $+10.0$
  - AND multi-match: $+5.0$
  - Modifier match in `product_name`: $+2.0$
  - Fuzzy fallback: $+0.5$
- **Completeness Boost**:
  - Open Food Facts completeness score ($0.0 \dots 1.0$) multiplied by $0.15$ via OpenSearch `function_score` with `boost_mode: "sum"`.

---

## 10. Nutrition Semantics

Open Food Facts nutritional data is normalized into a structured dictionary:
```json
{
  "proteins": {"value": 20.0, "per_100g": 20.0, "unit": "g"},
  "sugars": {"value": 4.0, "per_100g": 4.0, "unit": "g"},
  "energy-kcal": {"value": 150.0, "per_100g": 150.0, "unit": "kcal"},
  "sodium": {"value": 0.08, "per_100g": 0.08, "unit": "g"},
  "salt": {"value": 0.20, "per_100g": 0.20, "unit": "g"}
}
```

- **Per-100g Standard**: All search filters and thresholds evaluate against `per_100g` to ensure objective comparability across different package sizes.
- **Bidirectional Aliasing**: `energy` is automatically aliased to `energy-kcal` and vice versa.
- **Sodium/Salt Derivation**: If a record contains `sodium` but omits `salt`, salt is derived as $\text{sodium} \times 2.5$. If `salt` is present without `sodium`, sodium is derived as $\text{salt} / 2.5$.
- **Missing Nutrients**: Missing or null nutrients do not satisfy numeric inequality filters ($\ge$ or $\le$), ensuring zero false positives.

---

## 11. Recipe Ingredient Retrieval

When queries contain recipe quantities (e.g. *"2 tbsp salted butter"*, *"1 cup rolled oats"*, *"500 mL (2 cups) frozen blueberries"*):
1. **Quantity Decoupling**: Recipe quantities are parsed and extracted into `search_query.recipe_quantities`.
2. **Search Term Cleaning**: The quantity tokens (e.g. `2 tbsp`, `1 cup`, `500 ml`) are stripped from the lexical query term.
3. **No Package Constraint**: Recipe volume does **not** become a package size filter (e.g. a recipe needing $500\text{ mL}$ of blueberries should match standard $300\text{g}$ or $600\text{g}$ retail bags).
4. **Modifier Preservation**: Modifiers like `frozen`, `salted`, `fresh` are preserved in the retrieval term and scored with modifier boosts.

---

## 12. OpenSearch Architecture & Lifecycle

AskOFF uses versioned physical indices behind a stable alias:
- **Serving Alias**: `askoff_products`
- **Versioned Physical Index**: `askoff_products_YYYYMMDD_HHMMSS`

### Safe Index Lifecycle Workflow
```
1. python backend/scripts/create_index.py
   → Creates askoff_products_20260823_120000 with schema & analyzers.
   → Serving alias remains untouched.

2. python backend/scripts/index_data.py --index askoff_products_20260823_120000
   → Streams 114,453 documents via bulk API.

3. python backend/scripts/validate_index.py --index askoff_products_20260823_120000
   → Verifies document count == expected, cluster health != red, sample searches succeed.

4. python backend/scripts/promote_index.py --index askoff_products_20260823_120000
   → Atomically points alias 'askoff_products' to new index and unlinks previous.

5. python backend/scripts/rollback_index.py --to askoff_products_PREVIOUS
   → Instant rollback if issues are detected post-deployment.
```

---

## 13. API Architecture

Built with FastAPI with automated OpenAPI schema generation:

| Endpoint | Method | Purpose | Key Parameters |
|---|---|---|---|
| `/search` | `GET` | Main search endpoint | `q` (query), `size` (limit), `from_` (offset), `brand`, `category`, `explain` |
| `/products/{id}` | `GET` | Product lookup by barcode | `id` (string barcode/code) |
| `/autocomplete` | `GET` | Autocomplete suggestions | `q` (prefix string), `size` |
| `/compare` | `POST` | Multi-product comparison | Body: `{"product_ids": ["0066721011862", ...]}` |
| `/health` | `GET` | Liveness probe | Returns `{"status": "ok"}` |
| `/ready` | `GET` | Readiness probe | Checks OpenSearch cluster connectivity and index availability |

---

## 14. Error Handling

- **`503 Service Unavailable`**: Returned if OpenSearch is unreachable (`ConnectionError`), with actionable remediation guidance in the response body.
- **`400 Bad Request`**: Returned for invalid query parameters, excessive offsets ($> 10,000$), or malformed JSON payloads.
- **`404 Not Found`**: Returned when querying a non-existent product ID.
- **Safe Fallback**: If OpenSearch is temporarily unavailable during local test runs, evaluation harnesses fall back to the embedded DuckDB query engine.

---

## 15. Configuration

Configured via `backend/config/settings.py` using `pydantic-settings`:

| Variable | Default | Purpose |
|---|---|---|
| `ASKOFF_OPENSEARCH_HOSTS` | `["localhost:9200"]` | List of OpenSearch node addresses |
| `ASKOFF_OPENSEARCH_INDEX` | `askoff_products` | Search alias name |
| `ASKOFF_OPENSEARCH_USE_SSL` | `false` | Enable TLS encryption |
| `ASKOFF_OPENSEARCH_VERIFY_CERTS` | `false` | Verify TLS certificates (required `true` in prod) |
| `ASKOFF_RAW_DATA_PATH` | `data/raw/normalized.parquet` | Canonical dataset location |
| `ASKOFF_PROCESSED_DIR` | `data/processed` | Processed data output directory |
| `ASKOFF_CORS_ORIGINS` | `["http://localhost:3000", ...]` | Explicit CORS whitelist |
| `ASKOFF_ENVIRONMENT` | `development` | `development` or `production` |
| `ASKOFF_PIPELINE_BATCH_SIZE`| `1000` | Bulk indexing batch size |

---

## 16. Security

- **Container Hardening**: Dockerfile runs as non-root `appuser` (UID 10001).
- **CORS Enforcement**: Wildcard `*` is prohibited when credentials are enabled.
- **Production Validator**: `Settings.validate_deployment_settings()` prevents starting in `production` mode with default credentials, disabled TLS, or debug mode enabled.
- **Secret Isolation**: Credentials are passed strictly via environment variables; `.env` is gitignored.

---

## 17. Deployment

Production deployment is orchestrated via Docker Compose:
- **`docker-compose.yml`**: Defines the single-node OpenSearch service (with data persistence volume) and the FastAPI service.
- **Startup Sequencing**: The API container depends on `opensearch` passing its healthcheck before starting.
- **Zero Downtime Updates**: New data reindexing is performed into a separate versioned index before promoting the `askoff_products` alias.

---

## 18. Testing

The automated test suite (`backend/tests/`) contains 129 tests across 13 test modules:
- `test_api.py`: Route responses, pagination limits, error handlers, and `/ready` probes.
- `test_index_lifecycle.py`: Alias creation, versioning, promotion, validation, and rollback.
- `test_nlp_semantics.py`: Constraint extraction, dietary negation, recipe quantity decoupling.
- `test_normalizers.py`: Text normalization and tokenization edge cases.
- `test_nutrition.py`: JSON nutriment parsing, flag derivations, missing nutrient handling.
- `test_pipeline.py`: DuckDB extraction, batch streaming, and document builder integration.
- `test_query_engine.py`: Intent detection, entity extraction, and query structure.
- `test_ranking.py`: BM25 boost configuration and tiered `minimum_should_match` logic.
- `test_retrieval_quality.py`: Numeric nutrient constraints and boolean flag validation on live dataset.
- `test_search.py` & `test_search_engine.py`: End-to-end search engine execution and hit formatting.
- `test_synonyms.py`: Canadian French/English synonym canonicalization.
- `test_settings.py`: Deployment validator rules and environment configuration.

---

## 19. Evaluation

Evaluation tooling is located in `backend/evaluation/`:
- **`evaluate.py`**: Computes Precision@5, Precision@10, NDCG@10, and Mean Reciprocal Rank (MRR) across benchmark query sets (`benchmark_queries.json`, `benchmark_queries_structured.json`).
- **`audit_harness.py`**: Automated audit runner comparing OpenSearch and DuckDB retrieval across intent categories.
- **`grading.py`**: Evaluates individual query results against structured constraint rules.

---

## 20. Current Limitations

1. **Pure Lexical Retrieval**: The current production deployment uses lexical BM25 search. Queries relying on deep semantic abstraction (e.g. *"refreshing summer breakfast"*) depend on lexical matches in product descriptions or ingredient texts.
2. **Upstream OFF Data Incompleteness**: ~8.9% of raw products in Open Food Facts lack nutritional tables, and some entries only specify nutrients per serving.
3. **No Barcode-Verified Variant Grouping**: Core product vs. size/flavor variants are retrieved as individual documents rather than grouped under parent clusters.

---

## 21. Future Extension Points

- **Dense Semantic Embeddings**: Add an offline embedding generator (`bge-small-en-v1.5` or similar) to populate `semantic_document` vectors in OpenSearch k-NN indices.
- **Hybrid Retrieval**: Combine OpenSearch BM25 with neural vector search using Reciprocal Rank Fusion (RRF).
- **Cross-Encoder Reranker**: Implement a lightweight local cross-encoder model (e.g. `bge-reranker-base`) for top-20 reranking.
- **Human Relevance Benchmark**: Expand benchmark query annotations with human-curated graded relevance judgments (0-3).

---

## 22. Contributor Workflow

Where to make changes in the codebase:
- **Adding new dietary or nutrient filters**: Update `query/constraint_extractor.py` and `builders/search_document_builder.py`.
- **Adding Canadian synonyms**: Update `search/synonyms_ca.py` and `search/synonyms_ca.txt`.
- **Adjusting ranking weights**: Update `retrieval/ranking.py`.
- **Modifying OpenSearch mappings**: Update `search/mappings.py`.
- **Adding API endpoints**: Add route handler in `api/routes.py`.
- **Adding tests**: Add corresponding test in `backend/tests/test_*.py`.

---

## 23. Important Design Decisions

1. **Why OpenSearch?** Provides distributed, reliable inverted-index BM25 retrieval, flexible boolean filtering, function score customization, and native synonym analyzers with sub-10ms query execution.
2. **Why DuckDB + Parquet for offline data?** DuckDB processes 114k Parquet rows in milliseconds with zero memory bloat, allowing streaming extraction directly from compressed columnar storage.
3. **Why separate Query Understanding from Retrieval?** Decoupling NLP entity extraction from OpenSearch DSL generation allows testing query intent and constraint extraction in pure unit tests without needing a running database.
4. **Why are Hard Constraints implemented as Filters?** Treating dietary rules (e.g. `palm_oil_free`, `vegan`) and numeric bounds (e.g. `proteins >= 20g`) as boolean filters prevents irrelevant products from surfacing regardless of their keyword relevance.
5. **Why are Recipe Quantities decoupled from package constraints?** Consumers searching for *"1 cup oats"* or *"500 mL blueberries"* need the ingredient, not a package containing exactly that volume.
