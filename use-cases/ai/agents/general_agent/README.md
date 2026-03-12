# General Knowledge Agent

A lightweight A2A agent that answers general knowledge questions using a configurable LLM backend. Handles open-ended questions, concept explanations, summaries, and general reasoning that don't require live data, database queries, or document retrieval.

## Examples

- "Explain how TLS certificates work"
- "What is the difference between authentication and authorisation?"
- "Summarise the CAP theorem"

## Architecture

Single-node LangGraph graph that passes user messages directly to the configured LLM and returns the response. Inherits from `BaseA2AAgent`, which handles A2A protocol (JSON-RPC 2.0 over HTTP) and agent card serving.

**Files:**
- `main.py` -- Entry point; loads agent card, builds graph, starts uvicorn server
- `graph.py` -- LangGraph state machine with a single LLM invocation node
- `card.json` -- Agent metadata and skill definitions consumed by the orchestrator

## Configuration

| Variable | Description | Default |
|---|---|---|
| `AGENT_PORT` | Server listen port | `8080` |
| `LLM_PROVIDER` | LLM backend (`anthropic`, `openai`, `ollama`) | `anthropic` |
| `ANTHROPIC_API_KEY` | API key (when provider is `anthropic`) | -- |
| `OPENAI_BASE_URL` | Base URL (when provider is `openai`) | -- |
| `OPENAI_API_KEY` | API key (when provider is `openai`) | -- |
| `OPENAI_MODEL` | Model name (when provider is `openai`) | -- |
| `OLLAMA_BASE_URL` | Base URL (when provider is `ollama`) | -- |
| `OLLAMA_MODEL` | Model name (when provider is `ollama`) | -- |

## Running

```bash
# Standalone
python -m agents.general_agent.main
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
        "parts": [{"kind": "text", "text": "Explain how TLS certificates work"}]
      }
    }
  }'
```
