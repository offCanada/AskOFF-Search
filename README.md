# AskOFF

AskOFF is the natural-language search and retrieval engine for Open Food Facts Canada, providing high-performance, deterministic product discovery over ~114,453 Canadian food products.

---

## Overview

Open Food Facts contains vast amounts of crowdsourced food data, but consumers query products using conversational descriptions, dietary restrictions, and recipe requirements (e.g. *"500 mL frozen blueberries"*, *"low sugar cereal"*, *"products with at least 20g protein"*).

AskOFF bridges this gap with a low-latency, rule-based query understanding pipeline and OpenSearch BM25 lexical retrieval engine. It extracts structured dietary flags and numeric nutrition constraints from raw queries while ensuring fast, transparent, and reproducible search results without runtime LLM dependencies.

---

## Features

- **Natural-Language Query Understanding**: Automatically normalizes text, extracts brand/category/ingredient entities, detects user intent, and isolates modifiers.
- **Dietary & Certification Filtering**: Robust extraction and filtering for `organic`, `vegan`, `vegetarian`, `palm_oil_free`, `gluten_free`, and `lactose_free`.
- **Numeric Nutrition Constraints**: Parses explicit numerical bounds (e.g. `under 200 calories`, `at least 20g protein`) and evaluates them against normalized per-100g nutrient values.
- **Threshold-Based Nutrition Queries**: Automatically maps qualitative phrases like `low sugar` ($\le 5\text{g}/100\text{g}$), `high protein` ($\ge 10\text{g}/100\text{g}$), and `low sodium` ($\le 0.12\text{g}/100\text{g}$) to indexed flags.
- **Recipe Quantity Decoupling**: Separates recipe quantities (e.g. `500 mL`, `2 cups`, `2 tbsp`) from the search term so package sizes are never incorrectly filtered.
- **Canadian French/English Synonyms**: Normalizes Canadian French and alternate spellings (e.g. `soya sauce` $\leftrightarrow$ `soy sauce`, `yoghurt` $\leftrightarrow$ `yogurt`).
- **Fuzzy Typo Tolerance**: Tiered fuzzy multi-match catches misspellings (e.g. `peanute butter` $\rightarrow$ `peanut butter`) while preventing single-token noise.
- **Metadata Completeness Ranking**: Boosts products with richer Open Food Facts metadata using OpenSearch function scores.
- **Safe Zero-Downtime Index Lifecycle**: Versioned index builds, automated validation, and atomic alias promotion (`askoff_products`).
- **Production-Ready FastAPI Backend**: Includes pagination limits, input sanitization, health/readiness probes, and CORS controls.

---

## Architecture

### Ingestion & Indexing Pipeline
```
Open Food Facts Parquet (114k rows)
       ↓
OFFAdapter (DuckDB Stream)
       ↓
RawProduct (Pydantic Model)
       ↓
SearchDocumentBuilder (Entity & Flag Inference)
       ↓
SearchDocument (Canonical Schema)
       ↓
OpenSearch Indexer (Bulk API)
       ↓
Physical Index (askoff_products_YYYYMMDD_HHMMSS)
       ↓
Validation & Promotion → [ askoff_products (Alias) ]
```

### Search Pipeline
```
User Query (HTTP GET /search?q=...)
       ↓
FastAPI Router
       ↓
SearchEngine (Query Understanding Pipeline)
  ├── Normalization & Canonical Synonyms
  ├── Constraint & Entity Extraction
  └── Intent Classification
       ↓
SearchQuery (Structured Representation)
       ↓
OpenSearchSearchRepository (Bool DSL: Phrase + AND + Tiered Fuzzy + Filters)
       ↓
OpenSearch 2.x Cluster (BM25 + Completeness Function Score)
       ↓
SearchResponse (JSON)
```

---

## Search Capabilities

| Query Type | Query Example | Parsed Clean Term | Extracted Constraints / Metadata |
|---|---|---|---|
| **Recipe Quantity** | `500 mL (2 cups) frozen blueberries` | `frozen blueberries` | `quantities: [500ml, 2cups]`, `modifier: frozen` |
| **Dietary Restriction** | `palm oil free peanut butter` | `peanut butter` | `filter: {is_palm_oil_free: true}` |
| **Numeric Nutrition** | `snacks under 200 calories` | `snacks` | `numeric: {calories <= 200 kcal/100g}` |
| **Numeric Protein** | `products with at least 20g protein` | `products with` | `numeric: {protein >= 20g/100g}` |
| **Nutrition Threshold** | `low sugar cereal` | `cereal` | `filter: {is_low_sugar: true}` |
| **Fuzzy Matching** | `peanute butter` | `peanute butter` | Tiered fuzzy match $\rightarrow$ `Peanut Butter` |
| **Synonyms (Bilingual)**| `soya sauce` | `soy sauce` | Canonicalized $\rightarrow$ `Soy Sauce` |
| **Numeric Food Names** | `2% milk` | `2 milk` | Preserves `2` as keyword (not recipe quantity) |

---

## API

The backend serves an interactive OpenAPI documentation page at `http://localhost:8000/docs`.

### Core Endpoints

#### `GET /search`
Execute a natural-language search over the 114k catalog.
```bash
curl "http://localhost:8000/search?q=low+sugar+cereal&size=5"
```
**Response**:
```json
{
  "total": 1734,
  "hits": [
    {
      "score": 331.28,
      "product": {
        "id": "0066721011862",
        "product_name": "Cocca Cereal",
        "brand": null,
        "category": "Cereal",
        "attributes": {
          "nutrition": {
            "sugars": {"value": 0.0, "per_100g": 0.0, "unit": "g"}
          },
          "flags": {"is_low_sugar": true}
        }
      }
    }
  ],
  "query": "low sugar cereal",
  "took_ms": 12
}
```

#### `GET /products/{id}`
Retrieve a single product by barcode.
```bash
curl "http://localhost:8000/products/0066721011862"
```

#### `GET /autocomplete?q=pea`
Retrieve prefix completion suggestions.
```bash
curl "http://localhost:8000/autocomplete?q=pea&size=5"
```

#### `POST /compare`
Compare multiple products by ID.
```bash
curl -X POST "http://localhost:8000/compare" \
  -H "Content-Type: application/json" \
  -d '{"product_ids": ["0066721011862", "0061362433721"]}'
```

#### `GET /health` & `GET /ready`
Liveness and readiness probes for orchestrators and load balancers.
```bash
curl "http://localhost:8000/health"
curl "http://localhost:8000/ready"
```

---

## Data

The canonical dataset is stored at:
```text
data/raw/normalized.parquet
```
- **Total Products**: ~114,453 Canadian Open Food Facts products.
- **Columns**: `code`, `product_name`, `brands`, `categories`, `ingredients_text`, `nutriments`, `nutriscore_grade`, `nova_group`, `ecoscore_grade`, `completeness`, `product_name_clean`, `brands_clean`, `categories_clean`, `ingredients_clean`, `search_text`.

---

## Development Setup

### 1. Prerequisites
- Python 3.11+
- OpenSearch 2.12+ (or Docker Compose)

### 2. Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
pip install pytest ruff
```

### 3. Start Local OpenSearch
```bash
docker compose up -d opensearch
```

### 4. Verify Index Status & Run Server
```bash
# Verify 114k OpenSearch index
python backend/scripts/verify_index.py

# Start FastAPI server
python backend/scripts/run_server.py
```

---

## Docker Deployment

To spin up the complete stack (OpenSearch + Indexer Job + FastAPI):
```bash
# Start development stack
docker compose up --build -d

# Verify readiness
curl http://localhost:8000/ready
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for production configuration and [OPERATIONS.md](docs/OPERATIONS.md) for operational maintenance.

---

## Testing & Verification

Run the automated test suite (129 unit, integration, and quality tests):
```bash
pytest backend/tests/
```

Run code formatting and linting checks:
```bash
ruff check backend/
```

Run search evaluation benchmarks:
```bash
python backend/evaluation/evaluate.py --benchmark backend/evaluation/benchmark_queries.json
```

---

## Contributing

Contributions are welcome! Please review [CONTRIBUTING.md](CONTRIBUTING.md) for branch guidelines, code style standards, and test expectations.

For in-depth architectural details, refer to [docs/UNDERSTAND_CODEBASE.md](docs/UNDERSTAND_CODEBASE.md).

---

## Project Status

- **Current Version**: `0.2.0` (P3 Retrieval Engine)
- **Status**: Stable Lexical Search Backend MVP over 114,453 Canadian Open Food Facts products.

---

## Roadmap

- **Dense Neural Search**: Add vector embeddings for semantic query abstraction.
- **Hybrid Fusion**: Combine BM25 with dense vectors using Reciprocal Rank Fusion (RRF).
- **Cross-Encoder Reranking**: Integrate lightweight local reranker for top-20 precision.
- **Human Relevance Benchmark**: Expand benchmark with graded human relevance annotations.

---

## License

This project is licensed under the [Apache 2.0 License](LICENSE).