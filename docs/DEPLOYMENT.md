# Deployment

## Topology

Same shape as `challenges-n8n` on the EC2 box, fewer moving parts:

| Container | Replaces | Notes |
|---|---|---|
| `postgres:16` | n8n's Postgres **and** Redis **and** Mongo | queue + checkpoints + app tables + cache |
| `litellm` (1×) | n8n's LiteLLM | single instance = shared rate limiter |
| `api` | n8n main (2×, both lanes) | stateless, front with nginx |
| `worker-short` | n8n short worker `--concurrency=4` | scale replicas or `SN_LANE_SHORT_CONCURRENCY` |
| `worker-long` | n8n heavy worker `--concurrency=6` | scale replicas or `SN_LANE_LONG_CONCURRENCY` |
| `worker-retry` | (new) | dedicated retry pool |

No Caddy — nginx already owns 80/443 (as in the n8n deploy).

## First deploy

```bash
git clone <this repo> /opt/strategy-navigator && cd /opt/strategy-navigator
cp .env.example .env
#  set: SN_ENV=prod  SN_LOG_JSON=true
#       SN_DATABASE_URL   (managed Postgres or the compose one)
#       SN_LLM_API_KEY = LiteLLM master key,  OPENROUTER_KEY
#       SN_JINA_API_KEY
#       SN_BACKEND_BASE_URL = https://challenges.one   SN_BACKEND_CALLBACK_TOKEN
chmod 600 .env
docker compose -f docker-compose.yml up -d --build
docker compose logs -f migrate        # wait for "db.upgrade_complete"
curl -fsS localhost:8000/readyz
```

`migrate` runs `strategy-navigator db upgrade`: alembic (app tables) →
procrastinate schema → LangGraph checkpointer schema. It is idempotent; it runs
on every `up` and exits 0.

## nginx

```nginx
location /strategy-navigator/ {
    proxy_pass http://127.0.0.1:8000/;   # NOTE: trailing slash strips the prefix
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Request-Id $request_id;
    proxy_read_timeout 120s;             # triggers return 202 fast; this is slack
}
```

Then in `challenges-backend`'s env, repoint each workflow:

```
N8N_WEBHOOK_DOMAIN_SPECIFIC_AGENT_GENERATION_URL=https://challenges.one/strategy-navigator/webhooks/trigger
N8N_WEBHOOK_AGENT_IDEAS_URL=https://challenges.one/strategy-navigator/webhooks/trigger
# … one per workflow, all the same URL — the workflow_name in the body routes it
```

Roll back a single workflow by pointing its URL back at n8n.

## Backend callback endpoints

The app POSTs results to `SN_BACKEND_BASE_URL + <path>` (see
`callbacks/client._DEFAULT_PATH`) unless the trigger payload carried an explicit
`callbackUrl` (preferred — have the backend send it, exactly as it did for n8n).
Auth: `Authorization: Bearer $SN_BACKEND_CALLBACK_TOKEN`.

## Scaling a lane

```bash
docker compose up -d --scale worker-long=3        # 3 × 6 = 18 concurrent long runs
# or
SN_LANE_LONG_CONCURRENCY=10 docker compose up -d worker-long
```

Remember the ceiling is OpenRouter's rpm/tpm (in `litellm-config.yaml`), not the
worker count. If you scale workers past what the model pool allows you just move
the wait from the queue to `429` + backoff.

## Database migrations on later deploys

`db upgrade` runs automatically via the `migrate` service. To add a table:

```bash
uv run alembic -c alembic.ini revision -m "add sn_foo"   # edit migrations/versions/*
git commit && deploy                                     # migrate service applies it
```

procrastinate and checkpointer schema upgrades are handled by their libraries in
the same `db upgrade` command.

## Backups

One database to back up. `pg_dump` covers the queue, checkpoints, run history,
token spend, and cache. A restore resumes in-flight runs from their last
checkpoint on the next worker poll.

## Health checks

| Endpoint | Meaning |
|---|---|
| `GET /healthz` | process is up (liveness) |
| `GET /readyz` | Postgres reachable + lists ported workflows (readiness) |

Compose `HEALTHCHECK` hits `/healthz`. Point the load balancer at `/readyz`.
