# agent-ssh

SSH infrastructure agent that executes commands on remote hosts via Teleport to inspect logs, check system health, and run diagnostics.

## Prerequisites

- Python 3.12+
- `ANTHROPIC_API_KEY` set (or configure `LLM_PROVIDER` for Ollama/LM Studio)
- For production: `tsh` CLI installed and authenticated
- For local dev: seed log files placed at expected paths

## Running locally

### Set up seed log files

```bash
# Create the log directory and copy the seed log file
sudo mkdir -p /var/log/app
sudo cp scripts/seed-logs/order-pipeline.log /var/log/app/order-pipeline.log
```

### Start the agent

```bash
# Install dependencies
uv sync

# Run in local mode (executes commands on your machine, no SSH)
AGENT_SSH_MODE=local python -m agents.agent_ssh.main
```

The agent starts on port **8081** by default. Override with `AGENT_PORT`.

### Running with plain SSH

```bash
# Run with plain ssh (requires key-based auth to target hosts)
AGENT_SSH_MODE=ssh AGENT_SSH_USER=root python -m agents.agent_ssh.main
```

### Running with Teleport

```bash
# Ensure tsh is authenticated
tsh login --proxy=teleport.example.com

# Run in Teleport mode (uses tsh ssh)
AGENT_SSH_MODE=teleport AGENT_SSH_USER=root python -m agents.agent_ssh.main
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_SSH_MODE` | `local` | `local` runs commands directly, `ssh` uses plain ssh, `teleport` uses `tsh ssh` |
| `AGENT_SSH_USER` | `$USER` | SSH username for `tsh ssh user@host` |
| `AGENT_PORT` | `8081` | Port the A2A server listens on |
| `LLM_PROVIDER` | `anthropic` | LLM backend (`anthropic`, `ollama`, `lmstudio`) |
| `ANTHROPIC_API_KEY` | (required if using anthropic) | API key |

## Verify it's running

```bash
# Check the agent card
curl -s http://localhost:8081/.well-known/agent.json | jq .

# Send a test query
curl -s http://localhost:8081 -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "1",
      "role": "user",
      "parts": [{"kind": "text", "text": "Show the last 20 lines of the application log on app-server-01"}]
    }
  }
}' | jq .
```

## Kubernetes

In K8s, the agent uses tbot's ssh-multiplexer sidecar for SSH access through Teleport. Set `AGENT_SSH_MODE=teleport` and ensure the tbot sidecar is configured.

Copy the seed log file to the target host via an init container or ConfigMap:

```yaml
initContainers:
- name: seed-logs
  image: busybox
  command: ["sh", "-c", "mkdir -p /var/log/app && cp /seed/order-pipeline.log /var/log/app/"]
  volumeMounts:
  - name: seed-logs
    mountPath: /seed
  - name: app-logs
    mountPath: /var/log/app
```
