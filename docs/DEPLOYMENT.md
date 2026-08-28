# AskOFF Deployment & Operations Guide

This document outlines the deployment, operations, monitoring, and index lifecycle procedures for the AskOFF search backend.

---

## 1. Prerequisites

- **Docker Engine & Docker Compose v2**: Installed and running.
- **Hardware Resources**: At least 2 GB RAM allocated to OpenSearch and at least 1 GB free disk space.
- **Docker External Volume**: On clean machines, create the expected volume before starting OpenSearch:
  ```bash
  docker volume create ask-off-webapp_askoff-os-data
  ```
- **Dataset Artifact**: The canonical Parquet dataset (~21.8 MB to ~48.9 MB) is not committed to Git. Obtain or generate it and place it at:
  - `data/raw/off_canada_with_images.parquet` or
  - `data/raw/normalized.parquet`
  *(See official links on [Hugging Face](https://huggingface.co/datasets/offCanada/openfoodfacts-canada), [Colab Notebook](https://huggingface.co/datasets/offCanada/openfoodfacts-canada/blob/main/OFF_Canada_Data_Code.ipynb), or [Kaggle](https://www.kaggle.com/datasets/saitejakommi/open-food-facts-canada-dataset)).*

---

## 2. Local Development Deployment

There are two verified workflows for local development:

### Workflow A: Hybrid Docker OpenSearch + Local Python Backend (Recommended)

1. **Pre-create external volume and start OpenSearch**:
   ```bash
   docker volume create ask-off-webapp_askoff-os-data
   docker compose up -d opensearch
   ```
2. **Set up Python virtual environment**:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r backend/requirements.txt
   ```
3. **Place dataset in `data/raw/`**:
   Ensure `data/raw/off_canada_with_images.parquet` or `data/raw/normalized.parquet` is present.
4. **Bootstrap & verify the index**:
   ```bash
   # Populates the OpenSearch index from the Parquet dataset
   python backend/scripts/bootstrap_index.py

   # Verifies index document count (124,145 expected)
   python backend/scripts/verify_index.py
   ```
5. **Start FastAPI**:
   ```bash
   python backend/scripts/run_server.py
   ```

### Workflow B: Full-Stack Docker Compose

> [!IMPORTANT]
> The `Dockerfile` copies `data/` into the image at build time, and the `indexer` container depends on `off_canada_with_images.parquet`. Therefore, you **must** obtain the Parquet dataset and place it at `data/raw/off_canada_with_images.parquet` **before** running `docker compose up --build -d`.

```bash
# 1. Pre-create the external volume
docker volume create ask-off-webapp_askoff-os-data

# 2. Build and start all services (OpenSearch, Indexer, and API)
docker compose up --build -d

# 3. Follow indexer progress
docker compose logs -f indexer
```

### Ingestion & Startup Sequence
1. **OpenSearch Container**: Starts single-node OpenSearch on internal port 9200 (bound to `127.0.0.1:9200`).
2. **Indexer Job**: Runs `scripts/bootstrap_index.py`, which creates a timestamped index (`askoff_products_YYYYMMDDHHMMSS`), ingests `data/raw/off_canada_with_images.parquet`, validates document count, and assigns the alias `askoff_products`.
3. **API Service**: Waits for the indexer to complete successfully, then starts FastAPI on `http://127.0.0.1:8000`.

### Verifying Service Health

```bash
# Check process liveness
curl http://127.0.0.1:8000/health

# Check search backend readiness
curl http://127.0.0.1:8000/ready

# Test sample query (must return actual product hits, not 0)
curl "http://127.0.0.1:8000/search?q=peanut+butter&size=3"
```

---

## 3. Production Deployment

In production, AskOFF runs as an API service connecting to an external, authenticated, TLS-secured OpenSearch cluster.

### Configuration
1. Set production environment variables in `.env.production` (never commit secrets to version control):
   ```ini
   ASKOFF_ENVIRONMENT=production
   ASKOFF_CORS_ORIGINS=["https://your-frontend-domain.com"]
   ASKOFF_OPENSEARCH_HOSTS=["https://opensearch.internal.yourdomain.com:9200"]
   ASKOFF_OPENSEARCH_USE_SSL=true
   ASKOFF_OPENSEARCH_VERIFY_CERTS=true
   ASKOFF_OPENSEARCH_USERNAME=askoff_app
   ASKOFF_OPENSEARCH_PASSWORD=YOUR_SECURE_PASSWORD
   ```
2. Start the production API:
   ```bash
   docker compose -f docker-compose.production.yml up -d --build api
   ```

### Production Index Ingestion
To build or rebuild an index in production without impacting live traffic:
```bash
docker compose -f docker-compose.production.yml --profile indexing run --rm indexer
```

---

## 4. Zero-Downtime Index Promotion & Rollback

All index lifecycle operations use timestamped physical indices and an atomic pointer alias (`askoff_products`).

### Manual Step-by-Step Lifecycle Sequence

```bash
# 1. Create a new physical index with mappings and synonym analyzers
python backend/scripts/create_index.py
# Output: Created index askoff_products_20260824120000

# 2. Ingest parquet dataset into the new index
python backend/scripts/index_data.py --index askoff_products_20260824120000

# 3. Validate document counts and cluster health
python backend/scripts/validate_index.py --index askoff_products_20260824120000 --expected-count 124145

# 4. Atomically switch the alias to the new index
python backend/scripts/promote_index.py --index askoff_products_20260824120000
```

### Rollback
If an issue is identified after promotion, point the alias back to the previous physical index instantly:
```bash
python backend/scripts/rollback_index.py --to-index askoff_products_PREVIOUS_TIMESTAMP
```

---

## 5. Operations, Monitoring & Logs

### Viewing Logs

```bash
# Follow API logs
docker compose logs -f api

# Follow Indexer logs
docker compose logs -f indexer

# Follow OpenSearch logs
docker compose logs -f opensearch
```

### Request Tracing with `X-Request-ID`
Every API response includes an `X-Request-ID` header. Application log lines correlate this ID with endpoint path, response status, and execution duration (`took_ms`).

### Common Troubleshooting Scenarios

| Symptom | Probable Cause | Resolution |
| :--- | :--- | :--- |
| `external volume "ask-off-webapp_askoff-os-data" not found` | Compose expects pre-existing external volume on clean machine. | Run `docker volume create ask-off-webapp_askoff-os-data` before starting compose. |
| `FileNotFoundError` during index bootstrap | Parquet dataset artifact not present in `data/raw/`. | Obtain `off_canada_with_images.parquet` or `normalized.parquet` from Hugging Face / Colab and place in `data/raw/`. |
| Search returns HTTP 200 with 0 hits | OpenSearch is running but index is unpopulated. | Run `python backend/scripts/bootstrap_index.py` to index products. |
| `/health` returns non-200 | FastAPI process crashed or blocked. | Check `docker compose logs api`. |
| `/ready` returns 503 (`opensearch_unavailable`) | OpenSearch unreachable or bad credentials. | Check OpenSearch container status and verify TLS/network settings. |
| `/ready` returns 503 (`index_missing` or `index_empty`) | Alias `askoff_products` not created or index empty. | Re-run `python backend/scripts/bootstrap_index.py`. |
| `/ready` returns 503 (`index_red`) | OpenSearch shards unassigned or storage full. | Check disk allocation and cluster shard health. |
| Search returns 503 | Cluster overload or connection timeout. | Correlate `X-Request-ID` in logs to check OpenSearch query latency. |

---

## 6. Secret Rotation & Backup Policy

1. **Credential Rotation**: Update credentials in your secret store, inject them into container environment variables, and reload the API container. Confirm `/ready` reports healthy state.
2. **Snapshot Policy**: Configure OpenSearch snapshot repositories (e.g. S3, GCS) on the cluster level to take daily automated snapshots of the underlying storage volumes.
