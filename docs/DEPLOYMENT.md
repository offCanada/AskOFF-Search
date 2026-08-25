# AskOFF Deployment & Operations Guide

This document outlines the deployment, operations, monitoring, and index lifecycle procedures for the AskOFF search backend.

---

## 1. Prerequisites

- **Docker Engine & Docker Compose v2**: Installed and running.
- **Hardware Resources**: At least 2 GB RAM allocated to OpenSearch and at least 1 GB free disk space.
- **Dataset**: `data/raw/off_canada_with_images.parquet` (124,145 Canadian Open Food Facts products) located in the project tree.

---

## 2. Local Development Deployment

The local development configuration provides a self-contained environment running an OpenSearch 2.12 instance, an automatic indexing bootstrap job, and the FastAPI application.

### Start the Stack

```bash
# Clean start (resets existing local volume data)
docker compose down -v

# Build and start all services
docker compose up --build -d
```

### Ingestion & Startup Sequence
1. **OpenSearch Container**: Starts single-node OpenSearch on internal port 9200 (bound to `127.0.0.1:9200`).
2. **Indexer Job**: Runs `scripts/bootstrap_index.py`, which creates a timestamped index (`askoff_products_YYYYMMDDHHMMSS`), ingests `data/raw/normalized.parquet`, validates document count, and assigns the alias `askoff_products`.
3. **API Service**: Waits for the indexer to complete successfully, then starts FastAPI on `http://127.0.0.1:8000`.

### Verifying Service Health

```bash
# Check process liveness
curl http://127.0.0.1:8000/health

# Check search backend readiness
curl http://127.0.0.1:8000/ready

# Test sample query
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
| `/health` returns non-200 | FastAPI process crashed or blocked. | Check `docker compose logs api`. |
| `/ready` returns 503 (`opensearch_unavailable`) | OpenSearch unreachable or bad credentials. | Check OpenSearch container status and verify TLS/network settings. |
| `/ready` returns 503 (`index_missing` or `index_empty`) | Alias `askoff_products` not created or index empty. | Re-run `python backend/scripts/bootstrap_index.py`. |
| `/ready` returns 503 (`index_red`) | OpenSearch shards unassigned or storage full. | Check disk allocation and cluster shard health. |
| Search returns 503 | Cluster overload or connection timeout. | Correlate `X-Request-ID` in logs to check OpenSearch query latency. |

---

## 6. Secret Rotation & Backup Policy

1. **Credential Rotation**: Update credentials in your secret store, inject them into container environment variables, and reload the API container. Confirm `/ready` reports healthy state.
2. **Snapshot Policy**: Configure OpenSearch snapshot repositories (e.g. S3, GCS) on the cluster level to take daily automated snapshots of the underlying storage volumes.
