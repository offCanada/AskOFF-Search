# Contributing to AskOFF

Thank you for your interest in contributing to **AskOFF**! This project is an open-source natural-language search and retrieval engine for Open Food Facts.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for all contributors. Please treat fellow contributors with respect.

---

## Development Setup

### 1. Prerequisites
- **Python**: Python 3.11 recommended (tested on 3.11.14).
- **Docker & Docker Compose v2**: Installed and running (Docker Desktop on macOS/Windows, Docker Engine on Linux).
- **Git**: Configured for your GitHub account.

### 2. Fork and Clone
AskOFF is designed for open-source community development. You do **not** need access to maintainer-private machines, local volumes, or private infrastructure to contribute.

1. Fork `offCanada/AskOFF-Search` to your personal GitHub account.
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/AskOFF-Search.git
   cd AskOFF-Search
   ```

### 3. Set Up Python Virtual Environment
```bash
python3.11 -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

# Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
pip install pytest ruff
```

> [!NOTE]
> Installing Python dependencies provides the runtime environment but does **not** automatically provide the Canadian food catalog dataset.

### 4. Start OpenSearch (Local Infrastructure)
In `docker-compose.yml`, the OpenSearch service expects an external volume named `ask-off-webapp_askoff-os-data`. On a fresh developer machine, running `docker compose up -d opensearch` will encounter:
```text
external volume "ask-off-webapp_askoff-os-data" not found
```

**Verified Temporary Workaround**:
```bash
# 1. Pre-create the external volume manually
docker volume create ask-off-webapp_askoff-os-data

# 2. Start the OpenSearch container
docker compose up -d opensearch

# 3. Verify OpenSearch is responsive
curl http://localhost:9200
```
*(This manual volume creation is a temporary workaround. A future improvement should remove the requirement for an external volume in contributor setups).*

### 5. Obtain / Prepare the Dataset Artifact
The canonical Parquet dataset is **not committed to Git** due to file size constraints (~21.8 MB to ~48.9 MB).

The backend indexing scripts expect a normalized Parquet dataset at:
- `data/raw/off_canada_with_images.parquet` or
- `data/raw/normalized.parquet`

The repository currently does not automatically download the generated Canadian Parquet artifact. Before index bootstrap, obtain or generate a compatible dataset and place it at the path expected by the indexing scripts.

Official resources:
- **Hugging Face**: [`offCanada/openfoodfacts-canada`](https://huggingface.co/datasets/offCanada/openfoodfacts-canada)
- **Generation Notebook**: [`OFF_Canada_Data_Code.ipynb`](https://huggingface.co/datasets/offCanada/openfoodfacts-canada/blob/main/OFF_Canada_Data_Code.ipynb)
- **Kaggle**: [`saitejakommi/open-food-facts-canada-dataset`](https://www.kaggle.com/datasets/saitejakommi/open-food-facts-canada-dataset)

Create the directory if needed and place the file:
```bash
mkdir -p data/raw
# Place off_canada_with_images.parquet or normalized.parquet into data/raw/
```

### 6. Bootstrap and Verify the Index
Once the Parquet file is placed in `data/raw/`:

```bash
# 1. Populate the OpenSearch index from the Parquet dataset
python backend/scripts/bootstrap_index.py

# 2. Verify indexed document count and cluster health
python backend/scripts/verify_index.py
```
`verify_index.py` should report cluster health (`yellow` or `green`) and confirm `Indexed Document Count: 124,145`.

### 7. Run Backend Development Server
```bash
python backend/scripts/run_server.py
# or: uvicorn backend.api.app:app --reload --port 8000
```

Verify service liveness and run a real search:
```bash
# Health check
curl http://127.0.0.1:8000/health

# Normal lexical search (must return actual products, not just 0 hits)
curl "http://127.0.0.1:8000/search?q=milk"
```

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

---

## Making Changes & Testing

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Follow Coding Standards**:
   - Write clean, type-annotated Python code adhering to PEP 8.
   - Decouple query parsing, data models, and OpenSearch DSL generation cleanly.
   - Keep query parsing deterministic with zero external network dependencies.
3. **Run Tests**:
   ```bash
   pytest backend/tests/
   ```
   > [!IMPORTANT]
   > **Test Suite Reproducibility Reality**:
   > In a populated environment where `data/raw/normalized.parquet` is present, all **148 backend tests pass**.
   > 
   > On a fresh clone without the Parquet dataset, running `pytest backend/tests/` yields **143 passed / 5 failed** tests because 5 retrieval/pipeline tests directly read the Parquet file from disk.
   > 
   > Decoupling these tests using synthetic mock fixtures or a lightweight committed test sample is an open contributor improvement.
4. **Run Linter**:
   ```bash
   ruff check backend/
   ```
5. **Add Tests**:
   - Every bug fix or new feature must include corresponding unit tests in `backend/tests/`.

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

- **Decoupling Data-Dependent Tests**: Help refactor the 5 backend tests that expect physical Parquet files to use synthetic fixtures.
- **Normalizing Docker Compose**: Help remove the dependency on pre-existing external Docker volumes so `docker compose up -d opensearch` works out-of-the-box on clean machines.
- **Adding Dietary Constraints**: Update `backend/query/constraint_extractor.py` and `backend/builders/search_document_builder.py`.
- **Adding Canadian French/English Synonyms**: Update `backend/search/synonyms_ca.py` and `backend/search/synonyms_ca.txt`.
- **Improving OpenSearch Indexing**: Update `backend/search/mappings.py` and `backend/search/indexer.py`.


