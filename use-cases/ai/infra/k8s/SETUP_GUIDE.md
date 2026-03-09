# K8s Deployment Setup Guide

This guide covers everything needed to deploy the AI agents demo on Kubernetes. The `setup.sh` script automates Teleport resource creation and K8s deployment, but the prerequisites below must be in place first.

## Prerequisites Checklist

- [ ] Teleport cluster with App Access auto-discovery enabled
- [ ] PostgreSQL database registered in Teleport
- [ ] SSH host(s) registered in Teleport
- [ ] Database seeded with demo data
- [ ] LLM backend accessible from the K8s cluster
- [ ] Container images built and pushed to a registry
- [ ] `.env` file configured
- [ ] CLI tools installed and authenticated (`kubectl`, `tctl`, `tsh`)

---

## 1. Teleport Cluster

A running Teleport cluster with the following features enabled:

- **App Access** with Kubernetes auto-discovery — the orchestrator discovers specialist agents via Teleport App Access. Services in K8s with the label `teleport.expose: "true"` are automatically registered as Teleport apps.
- **Database Access** — for proxying PostgreSQL connections through Teleport with identity-based auth.
- **SSH Access** — for the SSH agent to execute commands on remote hosts.

The proxy address (e.g., `mycluster.teleport.sh`) is set via the `TELEPORT_PROXY` env var.

## 2. PostgreSQL Database

A PostgreSQL instance must be registered in Teleport as a database resource.

### Teleport Database Agent Config

On the PostgreSQL host, `/etc/teleport.yaml` should include:

```yaml
db_service:
  enabled: true
  databases:
    - name: demo-postgres-db
      protocol: postgres
      uri: demo-postgres-db:5432
      admin_user:
        name: teleport_admin
      static_labels:
        env: dev
        owner: homelab
```

Key points:
- The `admin_user` is used by Teleport for automatic database user provisioning (`create_db_user: true` in the agent-db role).
- The `teleport_admin` PostgreSQL role must exist with `CREATEROLE` privilege.
- The hostname in `uri` must resolve to the PostgreSQL host and match the TLS certificate SAN.

### Seed Data

Connect to the database and run the seed script:

```bash
tsh db connect demo-postgres-db --db-user=teleport_admin --db-name=demo < scripts/seed-db.sql
```

This creates `bookings.orders` and `bookings.payments` tables with sample data.

### Database Labels

The `agent-db-access` Teleport role grants access to databases matching:

```yaml
db_labels:
  env: dev
  owner: homelab
```

Ensure your database resource has these labels.

## 3. SSH Hosts

At least one SSH host must be registered in Teleport with the `location: homelab` label. The `agent-ssh-access` role grants access to nodes matching this label.

The SSH agent connects as the `ubuntu` user by default (configurable via `AGENT_SSH_USER` env var).

## 4. LLM Backend

The agents need access to an LLM. The endpoint must be reachable from within the K8s cluster (not `localhost`).

Supported providers (set via `LLM_PROVIDER` env var):

| Provider | Env Vars |
|----------|----------|
| `openai` (default) | `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `ollama` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |

Example for a local LM Studio instance:

```
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://192.168.1.146:1234/v1
OPENAI_API_KEY=lm-studio
OPENAI_MODEL=qwen/qwen3-vl-4b
```

> **Important:** Use the host's LAN IP, not `localhost`, since pods can't reach the host loopback.

## 5. Container Images

Build and push all three images. Use `--platform linux/amd64` if building on ARM (e.g., Apple Silicon):

```bash
cd use-cases/ai

# Orchestrator
docker buildx build --platform linux/amd64 \
  -f orchestrator/Dockerfile \
  -t registry.example.com/orchestrator:latest --push .

# Agent DB
docker buildx build --platform linux/amd64 \
  -f agents/Dockerfile.agent-db \
  -t registry.example.com/agent-db:latest --push agents/

# Agent SSH
docker buildx build --platform linux/amd64 \
  -f agents/Dockerfile.agent-ssh \
  -t registry.example.com/agent-ssh:latest --push agents/
```

If your registry is private, ensure K8s has image pull credentials configured.

## 6. Environment File

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `TELEPORT_PROXY` | Teleport proxy address (no port) | `mycluster.teleport.sh` |
| `LLM_PROVIDER` | LLM backend | `openai` |
| `OPENAI_BASE_URL` | LLM API endpoint | `http://192.168.1.146:1234/v1` |
| `OPENAI_API_KEY` | LLM API key | `lm-studio` |
| `OPENAI_MODEL` | Model name | `qwen/qwen3-vl-4b` |

Optional overrides:

| Variable | Default |
|----------|---------|
| `ORCHESTRATOR_IMAGE` | `registry.ellin.net/orchestrator:latest` |
| `AGENT_DB_IMAGE` | `registry.ellin.net/agent-db:latest` |
| `AGENT_SSH_IMAGE` | `registry.ellin.net/agent-ssh:latest` |
| `ORCHESTRATOR_TSH_DISCOVERY_QUERY` | `labels["app-type"] == "specialist" && labels["demo"] == "ai-agents"` |
| `ORCHESTRATOR_TSH_DB_DISCOVERY_QUERY` | `labels["demo"] == "ai-agents"` |
| `AGENT_DB_TSH_DISCOVERY_QUERY` | `labels["env"] == "dev" && labels["owner"] == "homelab"` |

### Database Discovery Queries

There are three separate database discovery queries used at different layers. Each filters databases via `tsh db ls --query=...` using Teleport label predicates.

**`AGENT_DB_TSH_DISCOVERY_QUERY`** — used by the **agent-db init container** (K8s)

Controls which database(s) the agent-db connects to. The init container runs `tsh db ls` with this query, then generates a tbot config with `database-tunnel` services and a `databases.json` for the agent. This should typically match a **single database** (or a narrow set), since each tunnel requires a dedicated local port.

Default: `labels["env"] == "dev" && labels["owner"] == "homelab"`

**`ORCHESTRATOR_TSH_DB_DISCOVERY_QUERY`** — used by the **orchestrator init container** (K8s)

Controls which databases the orchestrator is aware of for routing context. This is a broader query since the orchestrator only needs metadata about available databases, not direct tunnels.

Default: `labels["demo"] == "ai-agents"`

**`AGENT_DB_TSH_DISCOVERY_QUERY`** in `agent_db/main.py` — used in **local dev mode only**

When running agent-db outside K8s (e.g., `python -m agents.agent_db.main`), this env var controls which database the agent discovers and proxies via `tsh proxy db`. Not used in K8s deployments since the init container handles discovery instead.

Default: `name == "demo-postgres-db"`

## 7. Run setup.sh

Ensure you're authenticated:

```bash
tsh login --proxy=mycluster.teleport.sh
kubectl config use-context <your-cluster>
```

Then run:

```bash
cd infra/k8s
./setup.sh
```

### What setup.sh automates

- Creates the `ai-agents` namespace
- Extracts cluster JWKS for Kubernetes join method
- Creates Teleport bots: `orchestrator-bot`, `agent-db-bot`, `agent-ssh-bot`
- Applies Teleport roles: `orchestrator-app-access`, `agent-db-access`, `agent-ssh-access`
- Generates and applies Kubernetes join tokens for each bot
- Applies ConfigMaps (tbot configs, discovery scripts)
- Runs `envsubst` on deployment templates and applies them
- Waits for all deployments to roll out

## 8. Verify Deployment

Check all pods are running:

```bash
kubectl get pods -n ai-agents
```

Each agent pod should show `2/2` (agent container + tbot sidecar). The orchestrator pod should show `2/2` or `3/3` if it has an init container.

Test the orchestrator:

```bash
kubectl port-forward -n ai-agents svc/orchestrator 9000:9000

# Agent card
curl http://localhost:9000/.well-known/agent-card.json

# Query
curl -X POST http://localhost:9000 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"test","method":"message/send","params":{"message":{"messageId":"m1","role":"user","parts":[{"kind":"text","text":"How many orders are in the bookings.orders table?"}]}}}'
```

## Architecture

```
User → Teleport Proxy → Orchestrator (tbot sidecar)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              Agent DB              Agent SSH
          (tbot sidecar)         (tbot sidecar)
                │                       │
                ▼                       ▼
           PostgreSQL             SSH Hosts
        (via db-tunnel)        (via tsh ssh)
```

- Each service runs with its own tbot sidecar for Teleport identity
- The orchestrator discovers agents via Teleport App Access labels
- Inter-agent communication uses the A2A protocol (JSON-RPC 2.0) over Teleport application tunnels
- Database access goes through tbot database tunnels with automatic user provisioning

## K8s Service Labels for Discovery

Agent Services must have these labels to be discovered by the orchestrator:

```yaml
labels:
  teleport.expose: "true"    # Teleport auto-registers as an app
  app-type: specialist       # Matches orchestrator discovery query
  demo: ai-agents            # Matches orchestrator discovery query
```

## Troubleshooting

### Agent not discovered by orchestrator
- Verify the K8s Service has `teleport.expose: "true"`, `app-type: specialist`, and `demo: ai-agents` labels
- Check `tsh apps ls` to see if the agent appears as a Teleport app
- Trigger a reload: `curl -X POST http://localhost:9000/reload -d '{"reason":"manual"}'`

### Database connection errors
- Check agent-db tbot sidecar logs: `kubectl logs <pod> -c tbot -n ai-agents`
- Verify the database is registered in Teleport: `tctl db ls`
- Ensure the database host resolves to an IPv4 address (see `infra/docs/demo-postgres-db-fixes.md`)

### LLM connection errors
- Verify `OPENAI_BASE_URL` uses a LAN IP reachable from K8s pods, not `localhost`
- Check env vars: `kubectl exec <pod> -c <container> -n ai-agents -- env | grep OPENAI`

### "No response" from orchestrator tool calls
- Check agent logs for errors: `kubectl logs <pod> -c agent-db -n ai-agents`
- Common causes: LLM unreachable, database tunnel down, Teleport role misconfigured
