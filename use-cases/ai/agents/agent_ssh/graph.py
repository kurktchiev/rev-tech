import asyncio
import os
import shutil

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from agents.base_agent import get_llm

# AGENT_SSH_MODE controls how commands are executed:
#   local         - run commands directly on this machine (for demo with seed logs)
#   ssh           - run commands via plain ssh
#   tsh/teleport  - run commands via tsh ssh (through Teleport)
AGENT_SSH_MODE = os.environ.get("AGENT_SSH_MODE", "local")
AGENT_SSH_USER = os.environ.get("AGENT_SSH_USER", os.environ.get("USER", "root"))

SYSTEM_PROMPT = """\
You are an SSH infrastructure agent with access to remote hosts via Teleport.

When given a task, determine which host(s) and commands are needed, then
execute them using the ssh_exec tool.

## Guidelines
- Always prefer targeted commands (tail, grep, journalctl with filters) over
  dumping entire files.
- When searching logs, use time-based filters when a timeframe is mentioned.
- Summarise command output concisely -- highlight errors, anomalies, and
  relevant patterns rather than echoing raw output verbatim.
- If a command returns too much output, refine with grep/awk/head/tail.
- Never run destructive commands (rm, kill, reboot, shutdown, mkfs, dd)
  unless the user explicitly asks for it.

## Known hosts and log locations
- dev-host: development server, system log via journalctl

Only operate on hosts the user explicitly names. Do not check additional hosts.

## Available diagnostic commands
- System health: top -bn1, free -h, df -h, uptime
- Process inspection: ps aux | grep <service>, systemctl status <service>
- Network: ss -tlnp, netstat -an
- Logs: journalctl -u <service> --since "1 hour ago", tail, grep
"""


async def _run_command(host: str, command: str) -> str:
    """Run a command either locally or via SSH/tsh depending on AGENT_SSH_MODE."""
    if AGENT_SSH_MODE == "local":
        # Local mode: run commands directly (for demo with seed log files)
        cmd = command
    elif AGENT_SSH_MODE == "ssh":
        # Plain SSH mode
        cmd = ["ssh", f"{AGENT_SSH_USER}@{host}", "--", command]
    elif AGENT_SSH_MODE in ("tsh", "teleport"):
        # Teleport mode: use tsh ssh
        tsh = shutil.which("tsh") or "tsh"
        cmd = [tsh, "ssh"]
        identity = os.environ.get("TELEPORT_IDENTITY_FILE")
        if identity:
            cmd.extend(["-i", identity])
        proxy = os.environ.get("TELEPORT_PROXY")
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.extend([f"{AGENT_SSH_USER}@{host}", command])
    else:
        return f"ERROR: Unknown AGENT_SSH_MODE '{AGENT_SSH_MODE}'. Use 'local', 'ssh', 'tsh', or 'teleport'."

    if isinstance(cmd, list):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    output = stdout.decode()
    if proc.returncode != 0:
        err = stderr.decode()
        output = f"{output}\nSTDERR: {err}" if output else f"STDERR: {err}"
        output += f"\n(exit code {proc.returncode})"
    return output or "(no output)"


@tool
async def ssh_exec(host: str, command: str) -> str:
    """Execute a command on a remote host via SSH through Teleport.

    Args:
        host: The target hostname (e.g. app-server-01).
        command: The shell command to run on the host.
    """
    try:
        return await _run_command(host, command)
    except asyncio.TimeoutError:
        return f"ERROR: Command timed out after 30s on {host}"
    except Exception as e:
        return f"ERROR: {e}"


def build_graph():
    llm = get_llm()
    return create_react_agent(
        llm,
        tools=[ssh_exec],
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )
