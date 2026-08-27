# Contributing to AskOFF

Thank you for your interest in contributing to **AskOFF**! This project is an open-source natural-language search and retrieval engine for Open Food Facts.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for all contributors. Please treat fellow contributors with respect.

---

## Development Setup

### 1. Prerequisites
- Python 3.11+
- OpenSearch 2.12+ (or Docker Compose)
- Git

### 2. Fork and Clone
```bash
git clone https://github.com/offCanada/AskOFF-Search.git
cd AskOFF-Search
```

### 3. Set Up Python Virtual Environment
```bash
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

pip install -r backend/requirements.txt
pip install pytest ruff
```

### 4. Start OpenSearch (Local Dev)
```bash
docker compose up -d opensearch
```

### 5. Verify the Index & Run Backend
```bash
# Verify canonical dataset
python backend/scripts/verify_index.py

# Run development server
python backend/scripts/run_server.py
```

The API will be available at `http://localhost:8000`. OpenAPI documentation is accessible at `http://localhost:8000/docs`.

---

## Making Changes

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Follow Coding Standards**:
   - Write clean, type-annotated Python code.
   - Separate query parsing, domain models, and database queries cleanly.
   - Do not add external network calls to query parsing pipelines.
3. **Run Tests**:
   ```bash
   pytest backend/tests/
   ```
4. **Run Linter**:
   ```bash
   ruff check backend/
   ```
5. **Add Tests**:
   - Every bug fix or new feature must include corresponding unit or integration tests in `backend/tests/`.

---

## Submitting a Pull Request

1. Commit your changes with clear, descriptive commit messages.
2. Push your branch to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
3. Open a Pull Request on GitHub against the `main` branch.
4. Describe:
   - What problem your PR solves.
   - Summary of changes.
   - Verification steps and test results.

---

## Where to Make Common Contributions

- **Adding a new dietary filter or constraint**: Update `backend/query/constraint_extractor.py` and `backend/builders/search_document_builder.py`.
- **Adding Canadian French/English synonyms**: Update `backend/search/synonyms_ca.py` and `backend/search/synonyms_ca.txt`.
- **Modifying OpenSearch indexing or schema**: Update `backend/search/mappings.py` and `backend/search/indexer.py`.
- **Improving evaluation queries**: Update `backend/evaluation/benchmark_queries.json`.


