# AskOFF Backend Deployment

## Prerequisites

- Docker Engine and Docker Compose v2.
- Approximately 2 GB RAM available for OpenSearch and at least 1 GB free disk.
- The repository's `data/raw/normalized.parquet` dataset. The image contains it; do not add a downloaded dataset to a production image without validating its source and checksum.

## Configuration

Copy `.env.example` to `.env` only for local overrides. It contains placeholders, never credentials. Compose supplies development-safe internal OpenSearch networking by default.

For production, set `ASKOFF_ENVIRONMENT=production`, explicit `ASKOFF_CORS_ORIGINS`, `ASKOFF_OPENSEARCH_USE_SSL=true`, `ASKOFF_OPENSEARCH_VERIFY_CERTS=true`, and both OpenSearch credentials through a secret manager. Production settings reject missing TLS verification, missing credentials, and wildcard CORS.

Use `docker-compose.production.yml` only with a provisioned, authenticated TLS OpenSearch cluster. Copy `.env.production.example` outside version control to `.env.production`, inject the password from the deployment secret manager, then start the API:

```powershell
docker compose -f docker-compose.production.yml up -d --build api
```

This production profile does not publish port 9200 or create an insecure single-node cluster. Put the API behind an authenticated TLS ingress. To rebuild after the API is healthy, run the explicit indexing profile; it remains off by default:

```powershell
docker compose -f docker-compose.production.yml --profile indexing run --rm indexer
```

## Clean Development Deployment

From the repository root:

```powershell
docker compose down -v
docker compose up --build
```

The `indexer` job creates a timestamped physical index, indexes the local dataset, validates count/searchability, then atomically assigns the `askoff_products` alias. The API starts only after that job succeeds. OpenSearch is intentionally not published to the host in the development Compose file; use `docker compose exec opensearch` for diagnosis.

Verify:

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl "http://127.0.0.1:8000/search?q=peanute%20butter&size=3"
```

`/health` confirms the process is alive. `/ready` requires OpenSearch, a non-empty serving alias, and non-red index health. A single-node development index may be yellow because it retains a replica; this is not treated as production-green.

## Manual Safe Index Promotion

Run these in a one-off API image/container with the same environment as the API:

```powershell
python scripts/create_index.py
python scripts/index_data.py --index askoff_products_YYYYMMDDHHMMSS
python scripts/validate_index.py --index askoff_products_YYYYMMDDHHMMSS --expected-count 114453
python scripts/promote_index.py --index askoff_products_YYYYMMDDHHMMSS
```

Promotion is an atomic alias switch. It does not delete the previous physical index. The commands refuse to overwrite an existing target and refuse to promote if the serving name is still a legacy concrete index.

## Production Topology

Use a secured multi-node OpenSearch cluster, TLS/certificate validation, secret injection, at least one replica assigned on another node, backups/snapshots, and an ingress/proxy that terminates public TLS. Do not expose the development Compose OpenSearch configuration publicly.

## Upgrade and Rollback

Build and validate a new physical index before promotion. To roll back, retain the old physical index and run:

```powershell
python scripts/rollback_index.py --to-index askoff_products_YYYYMMDDHHMMSS
```

Only remove an old index after an explicit retention decision and backup verification.
