# SSH Infrastructure Agent

An A2A agent that executes commands on remote hosts via SSH through Teleport to inspect logs, check system health, and run diagnostics. Uses a ReAct agent pattern with an `ssh_exec` tool.

## Examples

- "Show me the last 50 lines of the application logs"
- "Search for OOM errors in the logs"
- "Check disk usage on the app server"

## Architecture

LangGraph ReAct agent with a single `ssh_exec` tool. The LLM decides which host and command to run, executes via the tool, and summarises the output. Supports three execution modes: local (demo), plain SSH, and Teleport (`tsh ssh`).

**Files:**
- `main.py` -- Entry point; loads agent card, builds graph, starts uvicorn server
- `graph.py` -- ReAct agent with `ssh_exec` tool and system prompt
- `card.json` -- Agent metadata and skill definitions consumed by the orchestrator

## Configuration

| Variable | Description | Default |
|---|---|---|
| `AGENT_PORT` | Server listen port | `8080` |
| `AGENT_SSH_MODE` | Execution mode: `local`, `ssh`, or `teleport` | `local` |
| `AGENT_SSH_USER` | SSH username for remote modes | `$USER` |
| `LLM_PROVIDER` | LLM backend (`anthropic`, `openai`, `ollama`) | `anthropic` |
| `ANTHROPIC_API_KEY` | API key (when provider is `anthropic`) | -- |
| `TELEPORT_PROXY` | Teleport proxy address (teleport mode) | -- |
| `TELEPORT_IDENTITY_FILE` | Identity file for tsh (teleport mode) | -- |

## Running

```bash
# Local mode (commands run directly, for demo with seed logs)
AGENT_SSH_MODE=local python -m agents.agent_ssh.main

# Plain SSH
AGENT_SSH_MODE=ssh 
AGENT_SSH_USER=root 
python -m agents.agent_ssh.main

# Teleport
AGENT_SSH_MODE=teleport 
AGENT_SSH_USER=root 
python -m agents.agent_ssh.main
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
        "parts": [{"kind": "text", "text": "Show the last 20 lines of the application log on dev-host"}]
      }
    }
  }'
```
