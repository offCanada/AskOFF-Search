# AskOFF Backend Operations

## Start and Stop

```powershell
docker compose up -d
docker compose down
```

Use `docker compose down -v` only for an intentional clean reset; it removes Compose-managed index data.

## Health, Readiness, and Logs

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
docker compose logs -f api
docker compose logs -f indexer
docker compose logs -f opensearch
```

Every API response includes `X-Request-ID`. Request logs include that ID, path, status, and latency, but not full product documents or credentials.

## Diagnose Failures

- `health` fails: inspect API container logs and container status.
- `ready` reason `opensearch_unavailable`: inspect OpenSearch logs/networking.
- `ready` reason `index_missing` or `index_empty`: inspect the indexer job logs; rerun the safe build/promote sequence.
- `ready` reason `index_red`: stop promotion/deployment work and repair cluster allocation before serving traffic.
- Search 503: correlate `X-Request-ID` with API logs, then inspect OpenSearch health.

## Index Operations

Use `create_index.py`, `index_data.py`, `validate_index.py`, and `promote_index.py` in that order. `rollback_index.py` restores the alias to a retained index. The legacy `rebuild_index.py` intentionally exits rather than delete a serving index.

## Secret Rotation and Recovery

Store production OpenSearch credentials and certificates outside the repository. Rotate them in the secret manager, update the deployment, and verify `/ready`. Recover a failed release by rolling back the application image and, independently, moving the alias to the last validated physical index. Snapshot/restore policy is an OpenSearch platform responsibility and must be configured before production launch.
