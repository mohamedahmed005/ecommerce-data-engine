# 09. Deployment Guide (Azure Container Apps)

## Cloud Architecture Summary

The production system runs as a containerized FastAPI service on **Microsoft Azure Container Apps** (`francecentral` region), backed by a managed **Azure Database for PostgreSQL Flexible Server** and automated image publishing through **GitHub Actions** and **GitHub Container Registry (GHCR)**.

| Component | Service / Configuration |
|---|---|
| **Compute Hosting** | Azure Container Apps (`francecentral`) |
| **Public URL** | `https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io` |
| **Container Registry** | GitHub Container Registry (`ghcr.io/mohamedahmed005/ecommerce-data-engine`) |
| **Container Port** | `8080` (configurable via `${PORT:-8080}`) |
| **Database Hosting** | Azure Database for PostgreSQL Flexible Server (database: `ecom`) |
| **Transport Security** | HTTPS ingress on Azure Container Apps; TLS (`PGSSLMODE=require`) to PostgreSQL |

---

## Containerization (`Dockerfile`)

The production container is defined in the root `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

### Local Container Smoke Test
Before pushing changes, you can verify the container build locally:
```bash
docker build -t ecommerce-data-engine:local .
docker run --rm -p 8080:8080 --env-file .env ecommerce-data-engine:local
```

---

## CI/CD Pipeline (GitHub Actions)

Every push to the `main` branch triggers `.github/workflows/docker-publish.yml`:

1. **Checkout Code:** `actions/checkout@v4` fetches the repository snapshot.
2. **Setup Buildx:** `docker/setup-buildx-action@v3` prepares the Docker build environment.
3. **Authenticate to GHCR:** `docker/login-action@v3` logs into `ghcr.io` using `${{ github.actor }}` and `${{ secrets.GITHUB_TOKEN }}` with `packages: write` permission.
4. **Build & Push Image:** `docker/build-push-action@v6` builds `./Dockerfile` and pushes two immutable/mutable tags:
   - `ghcr.io/mohamedahmed005/ecommerce-data-engine:latest`
   - `ghcr.io/mohamedahmed005/ecommerce-data-engine:<full-git-commit-sha>`

---

## Azure Container Apps Configuration

### Required Environment Variables & Secrets
Configure the following environment variables in the Azure Container App revision (store `POSTGRES_PASSWORD` as an Azure Container Apps **Secret** and reference it via `secretref`):

| Variable | Value / Source |
|---|---|
| `POSTGRES_HOST` | `<your-server>.postgres.database.azure.com` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `ecom` |
| `POSTGRES_USER` | Azure PostgreSQL username |
| `POSTGRES_PASSWORD` | Secret reference (`secretref:postgres-password`) |
| `PGSSLMODE` | `require` |
| `PORT` | `8080` (matches Azure Container Apps target ingress port) |

### Networking & Firewall Checklist
- Ensure Azure Database for PostgreSQL Flexible Server allows network access from the Azure Container Apps environment (either via **"Allow public access from any Azure service within Azure"** or VNet integration).
- Enforce SSL connections on the PostgreSQL server (`require_secure_transport = ON`).
- Set Container App HTTP ingress to **External** with Target Port `8080`.

---

## Updating & Rolling Back Production

### Deploying a New Release
1. Merge or push tested changes to `main`.
2. Wait for the **Build and Publish Docker Image** GitHub Actions workflow to complete.
3. In Azure Portal (or via Azure CLI), create a new revision pointing to the updated image tag:
   ```bash
   az containerapp update      --name ecommerce-api-v2      --resource-group <your-resource-group>      --image ghcr.io/mohamedahmed005/ecommerce-data-engine:latest
   ```

### Rolling Back to a Previous Release
Because GitHub Actions publishes a dedicated tag for every commit SHA, rollback is deterministic and requires no rebuild:
```bash
az containerapp update   --name ecommerce-api-v2   --resource-group <your-resource-group>   --image ghcr.io/mohamedahmed005/ecommerce-data-engine:<previous-commit-sha>
```

---

## Post-Deployment Verification

After each deployment revision activates, verify all five production endpoints:

1. **Health & DB Status:** `GET /api/health` → confirm `"status": "ok"` and `"warehouse_ready": true`.
2. **Landing Page:** `GET /` → verify headline KPI strip loads cleanly.
3. **Executive Dashboard:** `GET /dashboard` → verify charts render and switching years/data scopes responds promptly once background cache warming finishes.
4. **AI Analytics Assistant:** `GET /chat` → test both an English analytical query and an Arabic or recommendation query.
5. **OpenAPI Documentation:** `GET /docs` → verify all Analytics, Recommendations, Chat, and Health routes are exposed.

---

## Operational & Scaling Considerations

- **Cold-Start Cache Pre-Warming:** Upon container startup, `api/routers/analytics.py` spawns a daemon thread (`_warm_cache_background`) to pre-populate the 1-hour TTL cache for all years and data scopes. Configure `minReplicas >= 1` in Azure Container Apps if consistent sub-second latency is desired without scale-to-zero cold starts.
- **Connection Pool Sizing:** Each container replica opens `minconn=2` up to `maxconn=10` connections (`api/db.py`). When scaling horizontally to `N` replicas, verify that `N * 10` remains comfortably below Azure PostgreSQL Flexible Server's `max_connections` limit.
- **Cache Scope Across Replicas:** `_CACHE` is process-local in-memory storage (1-hour TTL). If the underlying warehouse is refreshed while containers are running, restart the active Container App revision to flush cached aggregates immediately.
