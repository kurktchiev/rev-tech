# Orchestrator

A2A multi-agent orchestrator on port `9000`. Uses a ReAct LangGraph loop to route incoming questions to the most appropriate specialist agent and return the result via the A2A protocol (JSON-RPC 2.0).

## Agent Discovery

The orchestrator supports two discovery modes, tried in order:

### 1. Teleport App Access (`tsh apps ls`)

When `tsh` is available and the bot identity is authenticated, the orchestrator runs:

```
tsh apps ls --query='<TSH_DISCOVERY_QUERY>' --format=json
```

It then starts a local `tsh proxy app` for each discovered agent, fetches its agent card, and wraps it as a LangChain tool.

### 2. Static config (`agents.json`)

If `tsh` discovery fails (no binary, not authenticated, no matching apps), the orchestrator falls back to `orchestrator/agents.json`.

#### `agents.json` format

A JSON array of objects, each with a `url` pointing to a running agent:

```json
[
  { "url": "http://localhost:9003" },
  { "url": "http://localhost:9004" }
]
```

At startup the orchestrator iterates the list, fetches each agent's card from `<url>/.well-known/agent-card.json`, reads the `skills` array, and builds a LangChain `StructuredTool` for each agent. The LLM uses these tool descriptions to decide which agent handles each query.

To add a new agent: start it on a port, add its URL to `agents.json`, and restart (or POST to `/reload`).

## Hot Reload

POST to `/reload` to re-discover agents without restarting:

```bash
curl -X POST http://localhost:9000/reload \
  -H 'Content-Type: application/json' \
  -d '{"reason":"new agent added"}'
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ORCHESTRATOR_PORT` | `9000` | Port the orchestrator listens on |
| `ORCHESTRATOR_AGENTS_CONFIG` | `orchestrator/agents.json` | Path to static agent registry |
| `ORCHESTRATOR_TSH_DISCOVERY_QUERY` | `labels["app-type"] == "specialist" && ...` | Teleport label predicate for `tsh apps ls` |
| `ORCHESTRATOR_LLM_PROVIDER` | *(falls back to `LLM_PROVIDER`)* | Override LLM backend for orchestrator only |
| `LLM_PROVIDER` | `anthropic` | Shared LLM backend: `anthropic`, `ollama`, or `openai` |

## Running

```bash
# Local
python -m orchestrator.main

# Docker (build from use-cases/ai/)
docker build -f orchestrator/Dockerfile -t orchestrator .
docker run -e LLM_PROVIDER=anthropic -e ANTHROPIC_API_KEY=sk-ant-... -p 9000:9000 orchestrator
```

## Testing

```bash
# Check agent card
curl -s http://localhost:9000/.well-known/agent-card.json | jq .

# Send a query
curl -s http://localhost:9000/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"msg-001","parts":[{"type":"text","text":"Explain how TLS certificates work"}]}}}' \
  | jq .
```
