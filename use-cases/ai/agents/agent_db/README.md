# agent-db

Database agent that queries PostgreSQL to answer questions about application data. Discovers schema dynamically and writes its own SQL.

## Prerequisites

- Python 3.12+
- PostgreSQL 16+
- `ANTHROPIC_API_KEY` set (or configure `LLM_PROVIDER` for Ollama/LM Studio)

## Running locally

```bash
# Start postgres
docker run -d --name demo-pg \
  -e POSTGRES_USER=demo \
  -e POSTGRES_PASSWORD=demo \
  -e POSTGRES_DB=demo \
  -p 5432:5432 \
  postgres:16-alpine

# Seed the database (idempotent -- safe to run repeatedly)
psql postgresql://demo:demo@localhost:5432/demo -f scripts/seed-db.sql

# Install dependencies
uv sync

# Start the agent
DATABASE_URL=postgresql://demo:demo@localhost:5432/demo python -m agents.agent_db.main
```

The agent starts on port **8083** by default. Override with `AGENT_PORT`.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://demo:demo@localhost:5432/demo` | PostgreSQL connection string |
| `AGENT_PORT` | `8083` | Port the A2A server listens on |
| `LLM_PROVIDER` | `anthropic` | LLM backend (`anthropic`, `ollama`, `lmstudio`) |
| `ANTHROPIC_API_KEY` | (required if using anthropic) | API key |

## Verify it's running

```bash
# Check the agent card
curl -s http://localhost:8083/.well-known/agent.json | jq .

# Send a test query
curl -s http://localhost:8083 -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "1",
      "role": "user",
      "parts": [{"kind": "text", "text": "How many orders failed?"}]
    }
  }
}' | jq .
```

## Kubernetes

Use an init container to seed the database on first deploy. The seed script is idempotent -- it skips inserts if data already exists.

```yaml
initContainers:
- name: seed-db
  image: postgres:16-alpine
  command: ["psql", "$(DATABASE_URL)", "-f", "/seed/seed-db.sql"]
  env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: db-credentials
        key: url
  volumeMounts:
  - name: seed-sql
    mountPath: /seed
```
