# Database Agent

An A2A agent that queries PostgreSQL to answer questions about application data. Discovers schema dynamically and writes read-only SQL. Uses a ReAct agent pattern with `list_tables`, `describe_table`, and `run_query` tools.

## Examples

- "How many orders failed in the last hour?"
- "Show me the most recent payments with errors"
- "What's the total revenue today?"

## Architecture

LangGraph ReAct agent with three tools for schema discovery and query execution. Connects to PostgreSQL either directly via `DATABASE_URL` or through a Teleport database tunnel discovered via `tsh db ls`.

**Files:**
- `main.py` -- Entry point; sets up Teleport DB tunnel (if needed), loads agent card, starts server
- `graph.py` -- ReAct agent with SQL tools and system prompt
- `card.json` -- Agent metadata and skill definitions consumed by the orchestrator

## Prerequisites

The database must be:

1. **Registered in Teleport** as a database resource (see `infra/k8s/SETUP_GUIDE.md` for Teleport DB agent config)
2. **Accessible via `tsh db`** -- ensure you have a valid Teleport session (`tsh login`)
3. **Seeded with demo data** using the provided seed script:

```bash
tsh db connect demo-postgres-db --db-user=teleport_admin --db-name=demo < scripts/seed-db.sql
```

This creates `bookings.orders` and `bookings.payments` tables with sample data.

When using Teleport discovery, the agent builds `DATABASE_URL` automatically pointing to the local tunnel endpoint -- you don't need to set it yourself. To connect directly to a database without Teleport, set `DATABASE_URL` with your connection string (e.g., `postgresql://user:pass@host:5432/mydb`) and set `AGENT_DB_SKIP_DISCOVERY=true`.

## Configuration

| Variable | Description | Default |
|---|---|---|
| `AGENT_PORT` | Server listen port | `8080` |
| `DATABASE_URL` | PostgreSQL connection string (`postgresql://user:pass@host:5432/db`) | auto-built by discovery |
| `AGENT_DB_SKIP_DISCOVERY` | Set to `true` to skip Teleport discovery and use `DATABASE_URL` directly | `false` |
| `AGENT_DB_TSH_DISCOVERY_QUERY` | Teleport predicate to find the database | `name == "demo-postgres-db"` |
| `AGENT_DB_USER` | Database username for Teleport tunnel | -- |
| `AGENT_DB_NAME` | Database name for Teleport tunnel | `demo` |

## Running

```bash
# Via Teleport (discovers DB and opens tunnel automatically)
python -m agents.agent_db.main

# Direct connection (skip Teleport discovery)
AGENT_DB_SKIP_DISCOVERY=true DATABASE_URL=postgresql://user:pass@localhost:5432/demo python -m agents.agent_db.main
```

## Endpoints

- `GET /.well-known/agent.json` -- Agent card
- `POST /` -- A2A JSON-RPC messages

## Sample Request

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "1",
        "role": "user",
        "parts": [{"kind": "text", "text": "How many orders failed?"}]
      }
    }
  }'
```
