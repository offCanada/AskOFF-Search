# AskOFF Technical Architecture & Codebase Guide

This document is the authoritative engineering reference for the AskOFF search and retrieval system. It details the complete architecture, data flow, query processing pipeline, indexing lifecycle, ranking mechanics, and component responsibilities.

---

## 1. System Purpose & Problem Statement

AskOFF is an open-source natural-language search and retrieval engine designed for the **Canadian Open Food Facts catalog (~114,453 products)**. 

Consumers frequently search for groceries using conversational, contextual phrases rather than exact product titles:
- *"500 mL frozen blueberries"* (contains a recipe quantity and food modifier)
- *"zero sugar chocolate"* (demands hard thresholding on sugar $\le 0.5\text{g}/100\text{g}$)
- *"drinks under 300 calories"* (specifies numeric energy upper bound)
- *"lowest sugar cereal"* (requires directional ranking on nutrient value)
- *"Compliments peanut butter"* (combines store brand entity with product category)

Standard keyword search engines often fail on these queries because they treat quantities, nutrient words, and operators as literal text tokens. AskOFF solves this by implementing a **rule-based, deterministic query understanding pipeline** paired with an **OpenSearch 2.x BM25 retrieval engine**. It achieves sub-50ms search latency without relying on runtime LLM calls.

---

## 2. System Architecture

AskOFF is split into two independent, decoupled pipelines:
1. **Offline Ingestion & Indexing Pipeline**: Streams raw Parquet data, normalizes multilingual text, infers dietary flags, transforms records into canonical `SearchDocument` models, and bulk-indexes them into OpenSearch.
2. **Online Search Pipeline**: Accepts user queries via FastAPI, applies normalization and entity/constraint extraction, constructs structured OpenSearch Bool DSL queries, scores candidates, and returns validated results.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       OFFLINE INGESTION PIPELINE                            │
│                                                                             │
│  data/raw/normalized.parquet (114k records)                                 │
│        │                                                                    │
│        ▼                                                                    │
│  OFFAdapter (Streaming DuckDB cursor)                                       │
│        │                                                                    │
│        ▼                                                                    │
│  RawProduct (Pydantic source schema)                                        │
│        │                                                                    │
│        ▼                                                                    │
│  SearchDocumentBuilder (Infere flags, clean text, structure nutrition)     │
│        │                                                                    │
│        ▼                                                                    │
│  SearchDocument (Canonical OpenSearch schema)                               │
│        │                                                                    │
│        ▼                                                                    │
│  OpenSearch Bulk Indexer (Batch size: 1000)                                 │
│        │                                                                    │
│        ▼                                                                    │
│  Physical Index: askoff_products_YYYYMMDDHHMMSS                             │
│        │                                                                    │
│        ▼                                                                    │
│  Validation & Promotion ──► [ askoff_products (Alias) ]                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         ONLINE SEARCH PIPELINE                              │
│                                                                             │
│  User Query (HTTP GET /search?q=...)                                        │
│        │                                                                    │
│        ▼                                                                    │
│  FastAPI Router (Input validation, size/from pagination guards)              │
│        │                                                                    │
│        ▼                                                                    │
│  SearchEngine & SearchQueryPipeline                                         │
│   ├── 1. QueryNormalizer (Typo fixes, operator spacing, lowercasing)        │
│   ├── 2. Canadian Synonyms (SynonymCanonicalizer: soya -> soy)              │
│   ├── 3. ConstraintExtractor (Recipe quantities, dietary & numeric filters) │
│   ├── 4. EntityExtractor (N-gram dictionary lookup: brands, categories)     │
│   └── 5. IntentDetector (generic_search, brand_search, category_browse)     │
│        │                                                                    │
│        ▼                                                                    │
│  SearchQuery (Structured representation: text_term, filters, sort)          │
│        │                                                                    │
│        ▼                                                                    │
│  OpenSearchSearchRepository                                                 │
│   ├── Must Clauses: Active boolean flags & numeric range filters            │
│   ├── Filter Clauses: Hard brand filter (if unambiguous brand recognized)   │
│   ├── Should Clauses: Phrase match + AND multi-match + Tiered fuzzy match   │
│   ├── Sort Clauses: Directional nutrient sort (if requested) + _score       │
│   └── Function Score: Metadata completeness weighting boost                 │
│        │                                                                    │
│        ▼                                                                    │
│  OpenSearch Cluster (askoff_products alias)                                 │
│        │                                                                    │
│        ▼                                                                    │
│  SearchResponse (Total hits, SearchHit array, took_ms, explain info)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Architecture & Ingestion

### Data Sources & Adapters (`backend/adapters/`)
AskOFF uses an adapter pattern (`BaseAdapter`) to ingest product data from diverse sources:
- **`OFFAdapter`** (`off_adapter.py`): The primary adapter for the 114,453 Canadian Open Food Facts dataset. It uses embedded DuckDB to read `data/raw/normalized.parquet` in streaming memory-safe chunks.
- **`ComplimentsAdapter`** (`compliments_adapter.py`): Dedicated adapter for store-brand private label datasets (`compliments_products.parquet`), supporting comparative and store-specific benchmarking.
- **`ReferenceAdapter`** (`reference_adapter.py`): Mock and validation adapter used in unit and pipeline regression tests.

### Normalized Product Models (`backend/models/`)
- **`RawProduct`** (`raw_product.py`): Captures the raw, untransformed schema directly from source datasets (code, product_name, brands, categories, ingredients_text, nutriments JSON, completeness).
- **`SearchDocument`** (`search_document.py`): Canonical OpenSearch document model containing:
  - `id`: Barcode string (e.g. `"0055742348279"`).
  - `product_name`: Primary sanitized product title.
  - `brand`: Primary brand name.
  - `category`: Categorical taxonomy string.
  - `ingredients`: Sanitized ingredient text.
  - `search_text`: Aggregated weighted text blob for fallback full-text matching.
  - `attributes.nutrition`: Keyed nutrient dictionary with `per_100g`, `value`, and `unit` (e.g. `sugars`, `proteins`, `energy-kcal`, `sodium`, `fat`).
  - `attributes.flags`: Derived boolean flags (`is_organic`, `is_vegan`, `is_vegetarian`, `is_palm_oil_free`, `is_high_protein`, `is_low_sugar`, `is_low_sodium`, `is_gluten_free`, `is_lactose_free`).
  - `metadata`: Completeness score ($0.0 \text{ to } 1.0$), source identifier, and update timestamp.

### Document Builder (`backend/builders/search_document_builder.py`)
Transforms `RawProduct` into `SearchDocument`:
1. **Multilingual Parsing**: Uses `off_parser.py` to extract French/English strings and clean escaped characters.
2. **Nutrition Normalization**: Parses complex Open Food Facts `nutriments` JSON objects, normalizing energy to `kcal` and deriving sodium/salt equivalencies (`salt = sodium * 2.5`).
3. **Threshold Flag Inference**:
   - `is_low_sugar`: `sugars.per_100g <= 5.0g`
   - `is_high_protein`: `proteins.per_100g >= 10.0g`
   - `is_low_sodium`: `sodium.per_100g <= 0.12g` (or `salt <= 0.3g`)

---

## 4. Query Understanding Pipeline (`backend/query/`)

When a user submits a natural-language query, `SearchQueryPipeline.process()` orchestrates 5 sequential stages:

```text
Raw Query String
      ↓
[1. QueryNormalizer] ── Typo correction, operator padding, lowercasing
      ↓
[2. SynonymCanonicalizer] ── Bilingual Canadian French/English mapping
      ↓
[3. ConstraintExtractor] ── Extract numeric bounds, dietary flags, directional sort, recipe quantities
      ↓
[4. EntityExtractor] ── N-gram matching against Brands, Categories, Ingredients dictionaries
      ↓
[5. IntentDetector] ── Intent classification (generic_search, brand_search, category_browse)
      ↓
SearchQuery Object
```

### 1. Normalization (`normalizer.py`)
- Corrects common typos in nutrition keywords before tokenization (`"protien"` $\rightarrow$ `"protein"`, `"sugur"` $\rightarrow$ `"sugar"`, `"drniks"` $\rightarrow$ `"drinks"`).
- Standardizes comparison operator spacing (`"<=300"` $\rightarrow$ `"<= 300"`).

### 2. Canadian Bilingual Synonyms (`backend/search/synonyms_ca.py`)
- Canonicalizes regional spelling and French/English variants (e.g. `soya` $\rightarrow$ `soy`, `yoghurt` $\rightarrow$ `yogurt`, `beurre d'arachide` $\rightarrow$ `peanut butter`).
- Synchronized with OpenSearch index-time synonym analyzer via `synonyms_ca.txt`.

### 3. Constraint Extraction (`constraint_extractor.py`)
- **Zero Sugar vs. Low Sugar**: Strict differentiation between `"zero sugar"` ($\le 0.5\text{g}/100\text{g}$) and `"low sugar"` ($\le 5.0\text{g}/100\text{g}$).
- **Comparison Operators**: Supports symbolic (`<`, `<=`, `>`, `>=`) and natural-language operators (`under`, `below`, `less than`, `at most`, `above`, `over`, `at least`, `with ... or less`).
- **Directional Ranking Preferences**: Extracts sort directives (e.g. `"lowest sugar"` $\rightarrow$ sort `sugars ASC`, `"highest protein"` $\rightarrow$ sort `proteins DESC`, `"lowest calorie"` $\rightarrow$ sort `energy-kcal ASC`).
- **Recipe Quantities**: Extracts cooking quantities (`500 ml`, `2 cups`, `1/2 tbsp`) into `recipe_quantities` and removes them from the lexical search term.
- **Connective Cleaning**: Strips filler words (`with`, `having`, `containing`) so residual search text remains clean.

### 4. Entity Extraction (`entity_extractor.py`)
- Uses greedy longest-match n-grams against preloaded memory sets (`BRANDS`, `CATEGORIES`, `INGREDIENTS`).
- Dynamic dictionaries are built from the Canadian dataset via `backend/scripts/build_dictionaries.py` and cached in `backend/data/dictionaries.json`.

### 5. Intent Detection (`intent_detector.py`)
- Classifies query into:
  - `brand_search`: Explicit brand navigation (e.g. `"by brand compliments"`).
  - `category_browse`: Category exploration (e.g. `"under category cereal"`).
  - `generic_search`: Default product discovery with combined lexical, brand, and constraint criteria.

---

## 5. Retrieval & Ranking Architecture (`backend/repositories/`)

### OpenSearch Repository (`opensearch_repository.py`)
The search repository translates the structured `SearchQuery` into an OpenSearch `function_score` query:

```json
{
  "query": {
    "function_score": {
      "query": {
        "bool": {
          "must": [
            { "term": { "attributes.flags.is_high_protein": true } },
            { "range": { "attributes.nutrition.sugars.per_100g": { "lte": 0.5, "gte": 0.0 } } },
            { "match": { "brand": { "query": "compliments", "operator": "and" } } }
          ],
          "should": [
            {
              "multi_match": {
                "query": "bar",
                "fields": ["product_name^3.0", "brand^2.0", "category^1.5", "ingredients^1.2", "search_text^1.0"],
                "type": "phrase",
                "boost": 10.0
              }
            },
            {
              "multi_match": {
                "query": "bar",
                "fields": ["product_name^3.0", "brand^2.0", "category^1.5", "ingredients^1.2", "search_text^1.0"],
                "operator": "and",
                "boost": 5.0
              }
            },
            {
              "multi_match": {
                "query": "bar",
                "fields": ["product_name^3.0", "brand^2.0", "category^1.5", "ingredients^1.2", "search_text^1.0"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "operator": "or",
                "boost": 0.5,
                "minimum_should_match": 1
              }
            }
          ],
          "minimum_should_match": 1
        }
      },
      "functions": [
        {
          "field_value_factor": {
            "field": "metadata.completeness",
            "factor": 0.15,
            "missing": 0.0
          }
        },
        {
          "filter": { "term": { "attributes.nutrition.sugars.per_100g": 0.0 } },
          "weight": 3.0
        }
      ],
      "boost_mode": "sum"
    }
  },
  "sort": [
    { "attributes.nutrition.sugars.per_100g": { "order": "asc", "missing": "_last" } },
    "_score"
  ]
}
```

### Ranking & Scoring Breakdown
1. **Tiered Lexical Matching (`bool.should`)**:
   - **Exact Phrase (Boost: 10.0)**: Prioritizes exact sequence matches in `product_name`.
   - **Conjunctive AND (Boost: 5.0)**: Requires all query tokens to be present across document fields.
   - **Fuzzy OR (Boost: 0.5)**: Employs `fuzziness: AUTO` to tolerate typos while enforcing minimum token matching.
2. **Field Weighting**:
   - `product_name^3.0` > `brand^2.0` > `category^1.5` > `ingredients^1.2` > `search_text^1.0`.
3. **Metadata Completeness Boost**:
   - High-quality Open Food Facts documents with complete nutrient and ingredient data receive a function score boost (`completeness * 0.15`).
4. **Directional Numeric Sorting**:
   - When a directional preference is detected (`lowest sugar`, `highest protein`, `lowest calories`), documents are ordered by the target nutrient value with secondary BM25 `_score` tie-breaking.

---

## 6. REST API Architecture (`backend/api/`)

FastAPI exposes standard, validated endpoints:

| Endpoint | Method | Purpose | Key Parameters |
| :--- | :--- | :--- | :--- |
| `/search` | `GET` | Natural-language product discovery | `q` (query), `size` (default: 20, max: 100), `from_` (offset), `explain` (boolean) |
| `/products/{barcode}` | `GET` | Single product detail lookup | `barcode` (string path param) |
| `/autocomplete` | `GET` | Prefix search suggestions | `q` (prefix), `size` (default: 5) |
| `/compare` | `POST` | Side-by-side product comparison | Body: `{"product_ids": ["...", "..."]}` |
| `/health` | `GET` | Liveness probe | None (returns 200 if process alive) |
| `/ready` | `GET` | Readiness probe | None (validates OpenSearch cluster, alias, and non-red index state) |

---

## 7. Index Lifecycle & Management (`backend/search/`)

AskOFF enforces a **safe, zero-downtime blue/green index lifecycle**:

1. **Versioned Index Creation** (`create_index.py`): Creates a new index with timestamped physical name (`askoff_products_20260824120000`) and applies mappings.
2. **Bulk Ingestion** (`index_data.py`): Streams Parquet rows via `helpers.bulk` without impacting the live alias.
3. **Validation** (`validate_index.py`): Validates total document count (must match expected 114,453) and verifies cluster status is not red.
4. **Atomic Promotion** (`promote_index.py`): Atomically switches the `askoff_products` alias from the old physical index to the new one.
5. **Rollback** (`rollback_index.py`): Points the alias back to the previous physical index if needed.

---

## 8. Security & Production Configuration (`backend/config/`)

All configuration is managed through Pydantic `Settings` (`settings.py`):
- **CORS Protection**: In production (`ASKOFF_ENVIRONMENT=production`), wildcard CORS (`"*"`) is strictly rejected. Specific allowed origins must be configured.
- **TLS Verification**: Production mode requires `ASKOFF_OPENSEARCH_USE_SSL=true` and `ASKOFF_OPENSEARCH_VERIFY_CERTS=true`.
- **Input Sanitization**: Query length is bounded, pagination offset is constrained, and OpenSearch special characters are escaped to prevent DSL injection.
- **Request Tracing**: All API responses attach an `X-Request-ID` header for log correlation.

---

## 9. Testing & Evaluation Framework

### Automated Tests (`backend/tests/`)
The test suite consists of 134 automated unit and integration tests:
- `test_api.py`: FastAPI endpoints, parameter validation, and error handling.
- `test_nutrition.py` & `test_nutrition_ranking.py`: Nutrition parsing, zero-sugar boundaries, comparison operators, and directional sorting.
- `test_nlp_semantics.py` & `test_query_engine.py`: Normalization, constraint extraction, entity detection, and recipe quantities.
- `test_index_lifecycle.py`: Timestamped index creation, validation, and atomic alias switching.
- `test_ranking.py` & `test_retrieval_quality.py`: BM25 field weights, minimum_should_match rules, and retrieval quality.
- `test_synonyms.py`: Canadian French/English synonym analyzer and parity.
- `test_settings.py`: Security and environment validation rules.

### Evaluation Harness (`backend/evaluation/`)
- `benchmark_queries.json`: Standardized benchmark query set.
- `evaluate.py`: Computes Precision@k ($P@5, P@10$), Mean Reciprocal Rank (MRR), and Normalized Discounted Cumulative Gain (NDCG@10).
- `verify_nutrition.py`: Verifies constraint satisfaction against OpenSearch.

---

## 10. Known Limitations & Design Boundaries

1. **Lexical BM25 Engine**: The retrieval architecture is strictly lexical BM25 with rule-based NLP. Dense vector search and hybrid fusion are intentionally deferred to future versions.
2. **Product Image Data**: The Canadian Open Food Facts dataset does not contain image URLs. The frontend displays polished, deterministic fallback placeholders.
3. **Crowdsourced Missing Attributes**: When products have unrecorded nutrient values in Open Food Facts, hard numeric filters exclude them to ensure constraint compliance. Missing data is never fabricated.
