# AskOFF

AskOFF is an open-source natural-language search and retrieval engine for **Open Food Facts Canada**, enabling fast, deterministic product discovery over **114,453 Canadian grocery products**.

---

## 1. Project Overview

Open Food Facts provides an extensive open food database, but consumer grocery searches are inherently conversational and constraint-heavy (e.g. *"250 g tomato sauce"*, *"zero sugar chocolate"*, *"drinks under 300 calories"*).

AskOFF bridges the gap between unstructured consumer search queries and semi-structured catalog records. It uses a low-latency, rule-based query understanding pipeline and an OpenSearch 2.x BM25 retrieval engine to deliver accurate, constraint-compliant search results with sub-50ms execution times and zero runtime LLM dependencies.

---

## 2. What AskOFF Does

- **Understands Natural Language**: Extracts brands, food categories, recipe quantities, food modifiers, and dietary constraints from raw search strings.
- **Enforces Hard Nutrition Constraints**: Accurately filters numeric criteria such as calories (`under 200 calories`), protein (`at least 20g protein`), sugar (`under 5g sugar`), and sodium (`under 120mg sodium`).
- **Differentiates Zero Sugar & Low Sugar**: Enforces Canadian regulatory standards for `zero sugar` ($\le 0.5\text{g}/100\text{g}$) distinct from `low sugar` ($\le 5.0\text{g}/100\text{g}$).
- **Applies Directional Nutrient Sorting**: Orders search results dynamically by nutritional properties when requested (e.g. `lowest sugar`, `highest protein`, `lowest calories`).
- **Decouples Recipe Quantities**: Isolates measurements like `250 g`, `500 mL`, or `2 cups` from search keywords so package sizes are never incorrectly filtered.
- **Handles Canadian Bilingual Synonyms**: Normalizes Canadian French and regional spelling variants (e.g. `soya` $\leftrightarrow$ `soy`, `yoghurt` $\leftrightarrow$ `yogurt`).
- **Fast & Scalable REST API**: Provides low-latency FastAPI endpoints for search, product lookup, autocomplete, and multi-product comparison.

---

## 3. Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SEARCH PIPELINE                                │
│                                                                             │
│  User Query (HTTP GET /search?q=...)                                        │
│        │                                                                    │
│        ▼                                                                    │
│  FastAPI API Layer                                                          │
│        │                                                                    │
│        ▼                                                                    │
│  SearchEngine (Query Understanding Pipeline)                                │
│   ├── Normalizer & Canadian Synonyms                                        │
│   ├── Constraint & Quantity Extractor                                       │
│   └── Entity & Intent Detector                                              │
│        │                                                                    │
│        ▼                                                                    │
│  OpenSearch 2.x Cluster (Bool DSL: Phrase + AND + Tiered Fuzzy + Filters)   │
│        │                                                                    │
│        ▼                                                                    │
│  SearchResponse (Ranked Products + Complete Query Explain Metadata)         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Key Capabilities

| Capability | Example Query | Parsed Keyword | Applied Constraints / Filters |
| :--- | :--- | :--- | :--- |
| **Recipe Quantity** | `250 g tomato sauce` | `tomato sauce` | `quantity: 250 g` |
| **Zero Sugar** | `zero sugar chocolate` | `chocolate` | `filter: {sugars <= 0.5g/100g}` |
| **Numeric Calorie Bound** | `drinks under 300 calories` | `drinks` | `filter: {energy <= 300 kcal/100g}` |
| **Numeric Protein Bound** | `snacks with at least 20g protein` | `snacks` | `filter: {protein >= 20g/100g}` |
| **Directional Sort** | `lowest sugar cereal` | `cereal` | `sort: sugars ASC` |
| **Dietary Restriction** | `vegan high protein snacks` | `snacks` | `filters: {is_vegan: true, is_high_protein: true}` |
| **Store Brand Discovery** | `Compliments peanut butter` | `peanut butter` | `filter: {brand: Compliments}` |
| **Typo Tolerance** | `high protien snacks` | `snacks` | Normalized `protien` $\to$ `protein` |

---

## 5. Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, Uvicorn
- **Search & Ingestion**: OpenSearch 2.12+, DuckDB, PyArrow / Parquet
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, TanStack Query, Lucide Icons
- **Infrastructure**: Docker, Docker Compose

---

## 6. Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- Docker and Docker Compose v2

### Clone Repository
```bash
git clone https://github.com/SaitejaKommi/Ask-OFF-WebApp.git
cd Ask-OFF-WebApp
```

---

## 7. Running the Backend

### Option A: Via Docker Compose (Recommended)
```bash
# Start OpenSearch, Indexer, and FastAPI backend
docker compose up --build -d

# Verify backend readiness
curl http://localhost:8000/ready
```

### Option B: Local Python Development
```bash
# Set up virtual environment
python -m venv .venv
# On Linux/macOS: source .venv/bin/activate
# On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Start OpenSearch in Docker
docker compose up -d opensearch

# Verify index & start backend server
python backend/scripts/verify_index.py
python backend/scripts/run_server.py
```

The API will be available at `http://localhost:8000` (Interactive docs at `http://localhost:8000/docs`).

---

## 8. Running the Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

Open `http://localhost:5173` in your browser to interact with the discovery application.

---

## 9. Running Tests

### Automated Backend Tests (Pytest)
```bash
pytest backend/tests/ -v
```

### Code Style & Linting (Ruff)
```bash
ruff check backend/
```

### Frontend Build Validation
```bash
cd frontend && npm run build
```

---

## 10. Dataset Requirements

AskOFF operates over the Canadian Open Food Facts dataset located at:
```text
data/raw/normalized.parquet
```
- **Total Products**: ~114,453 Canadian food products.
- **Schema**: `code`, `product_name`, `brands`, `categories`, `ingredients_text`, `nutriments`, `nutriscore_grade`, `nova_group`, `ecoscore_grade`, `completeness`.

---

## 11. Contributing

Contributions are welcome! Please review [CONTRIBUTING.md](CONTRIBUTING.md) for code style guidelines, branch workflows, and PR requirements.

---

## 12. Technical Documentation

For the complete technical architecture, request lifecycles, ranking equations, and OpenSearch mapping schemas, see:
- [docs/UNDERSTAND_CODEBASE.md](docs/UNDERSTAND_CODEBASE.md) — Single comprehensive architecture guide.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Deployment, operations, and zero-downtime index lifecycle.

---

## 13. Current Limitations

- **Lexical BM25 Engine**: Uses OpenSearch BM25 and rule-based NLP. Semantic vector embeddings and hybrid dense retrieval are deferred to future milestones.
- **Product Images**: The Canadian Open Food Facts dataset does not contain image URLs. The frontend uses deterministic, polished SVG placeholders.
- **Unrecorded Nutrition Data**: Products with missing nutrient values in Open Food Facts are safely excluded from hard threshold queries to prevent false positives.

---

## 14. License

This project is licensed under the [Apache 2.0 License](LICENSE).