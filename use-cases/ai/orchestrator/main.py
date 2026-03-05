import asyncio
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import structlog
import uvicorn
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils.parts import get_text_parts
from langchain_core.messages import HumanMessage

from orchestrator.graph import build_orchestrator
from orchestrator.tool_builder import build_tool_from_card

logger = structlog.get_logger()

PORT = int(os.environ.get("ORCHESTRATOR_PORT", 9000))
CONFIG_PATH = Path(os.environ.get("ORCHESTRATOR_AGENTS_CONFIG", "orchestrator/agents.json"))
TSH_DISCOVERY_QUERY = os.environ.get(
    "ORCHESTRATOR_TSH_DISCOVERY_QUERY",
    'labels["app-type"] == "specialist" && labels["demo"] == "ai-agents"',
)

# Mutable state — updated on every reload
_state: dict = {"tools": [], "graph": None, "proxies": []}

_PROXY_READY_RE = re.compile(r"((?:127\.0\.0\.1|localhost):\d+)")


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------

async def fetch_agent_card(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{base_url.rstrip('/')}/.well-known/agent-card.json")
        resp.raise_for_status()
        return resp.json()


async def discover_agents_via_tsh() -> list[str]:
    """Discover specialist agent app names via ``tsh apps ls``."""
    tsh = shutil.which("tsh")
    if tsh is None:
        raise RuntimeError("tsh binary not found in PATH")

    proc = await asyncio.create_subprocess_exec(
        tsh, "apps", "ls", f"--query={TSH_DISCOVERY_QUERY}", "--format=json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"tsh apps ls failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

    apps = json.loads(stdout.decode())
    names = []
    for app in apps:
        name = (
            app.get("metadata", {}).get("name")
            or app.get("spec", {}).get("name")
            or app.get("name")
        )
        if name:
            names.append(name)
    return names


async def start_app_proxy(app_name: str) -> tuple[str, asyncio.subprocess.Process]:
    """Start ``tsh proxy app`` and return ``(local_url, process)``."""
    tsh = shutil.which("tsh")
    if tsh is None:
        raise RuntimeError("tsh binary not found in PATH")

    proc = await asyncio.create_subprocess_exec(
        tsh, "proxy", "app", app_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # merge so we catch the address on either stream
    )

    # tsh proxy app prints the listening address, e.g.
    #   Proxying connections to <app> on 127.0.0.1:<port>
    lines_seen: list[str] = []
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line:
                raise RuntimeError(
                    f"tsh proxy app {app_name} exited unexpectedly. "
                    f"Output: {''.join(lines_seen)}"
                )
            text = line.decode().strip()
            lines_seen.append(text + "\n")
            logger.debug("tsh proxy app output", app=app_name, line=text)
            m = _PROXY_READY_RE.search(text)
            if m:
                local_url = f"http://{m.group(1)}"
                logger.info("proxy started", app=app_name, url=local_url)
                return local_url, proc
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(
            f"tsh proxy app {app_name} did not print a listener address within 30s. "
            f"Output: {''.join(lines_seen)}"
        )


async def _stop_proxies() -> None:
    """Terminate all running tsh proxy app processes."""
    for proc in _state.get("proxies", []):
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            proc.kill()
    _state["proxies"] = []


async def load_tools_from_config() -> list:
    config = json.loads(CONFIG_PATH.read_text())
    tools = []
    for entry in config:
        base_url = entry["url"]
        try:
            card = await fetch_agent_card(base_url)
            tool = build_tool_from_card(card, base_url)
            tools.append(tool)
            logger.info("agent loaded", name=card["name"], url=base_url)
        except Exception as e:
            logger.warning("agent skipped", url=base_url, error=str(e))
    logger.info("tools ready", count=len(tools))
    return tools


async def load_tools_from_tunnels() -> list | None:
    """Load agents from tunnel-based agents.json (generated by init container).

    Returns None if the config file doesn't exist or is empty, signalling
    the caller to try alternative discovery.
    """
    if not CONFIG_PATH.exists():
        return None
    try:
        config = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return None
    if not config:
        return None

    # Tunnel config from init container has both "name" and "url" fields
    if "name" not in config[0]:
        return None

    logger.info("loading agents from tunnel config", path=str(CONFIG_PATH), count=len(config))
    tools = []
    for entry in config:
        base_url = entry["url"]
        name = entry.get("name", base_url)
        try:
            card = await fetch_agent_card(base_url)
            tool = build_tool_from_card(card, base_url)
            tools.append(tool)
            skills = [s["name"] for s in card.get("skills", [])]
            logger.info("agent loaded", name=card["name"], url=base_url, skills=skills)
        except Exception as e:
            logger.warning("agent skipped (tunnel)", name=name, url=base_url, error=repr(e))
    tool_summary = {t.name: t.description[:80] for t in tools}
    logger.info("tools ready", count=len(tools), tools=tool_summary)
    return tools


async def load_tools() -> list:
    """Load agent tools using the best available method.

    Priority:
      1. Tunnel-based agents.json (from init container, K8s deployment)
      2. tsh apps ls + tsh proxy app (local dev with Teleport)
      3. Static agents.json fallback
    """
    # Try tunnel-based config first (K8s with init container)
    tunnel_tools = await load_tools_from_tunnels()
    if tunnel_tools is not None:
        return tunnel_tools

    # Try tsh discovery with proxy (local dev)
    await _stop_proxies()
    try:
        app_names = await discover_agents_via_tsh()
        logger.info("tsh discovery succeeded", count=len(app_names), apps=app_names,
                     query=TSH_DISCOVERY_QUERY)
    except Exception as e:
        logger.warning("tsh discovery failed, falling back to agents.json", error=str(e))
        return await load_tools_from_config()

    tools = []
    proxies = []
    for app_name in app_names:
        try:
            local_url, proc = await start_app_proxy(app_name)
            proxies.append(proc)
            card = await fetch_agent_card(local_url)
            tool = build_tool_from_card(card, local_url)
            tools.append(tool)
            skills = [s["name"] for s in card.get("skills", [])]
            logger.info("agent loaded", name=card["name"], url=local_url,
                        proxy_pid=proc.pid, skills=skills)
        except Exception as e:
            logger.warning("agent skipped", app=app_name, error=repr(e))
    _state["proxies"] = proxies
    tool_summary = {t.name: t.description[:80] for t in tools}
    logger.info("tools ready", count=len(tools), tools=tool_summary)
    return tools


# ---------------------------------------------------------------------------
# Orchestrator A2A executor — reads _state at call time to support hot-reload
# ---------------------------------------------------------------------------

class OrchestratorExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        graph = _state["graph"]
        if graph is None:
            raise RuntimeError("Orchestrator graph not initialised")

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        user_text = " ".join(get_text_parts(context.message.parts))

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=user_text)]}
        )

        last_msg = result["messages"][-1]
        response_text = (
            last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        )

        await updater.add_artifact(parts=[Part(root=TextPart(text=response_text))])
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()


# ---------------------------------------------------------------------------
# /reload endpoint
# ---------------------------------------------------------------------------

class ReloadRequest(BaseModel):
    reason: str


async def do_reload(request: ReloadRequest) -> None:
    try:
        new_tools = await load_tools()
        _state["tools"] = new_tools
        _state["graph"] = build_orchestrator(new_tools)
        logger.info("reload complete", tool_count=len(new_tools), reason=request.reason)
    except Exception as e:
        logger.error("reload failed", error=str(e))


async def reload_endpoint(request: Request) -> JSONResponse:
    data = await request.json()
    req = ReloadRequest(**data)
    logger.info("reload triggered", reason=req.reason)
    return JSONResponse(
        {"status": "accepted", "reason": req.reason},
        status_code=202,
        background=BackgroundTask(do_reload, req),
    )


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------

def build_orchestrator_card() -> AgentCard:
    return AgentCard(
        name="A2A Orchestrator",
        description=(
            "Multi-agent orchestrator. Routes questions to the most appropriate "
            "specialist agent (SQL queries, document search, general knowledge) "
            "and returns the result."
        ),
        url=f"http://localhost:{PORT}",
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="orchestrate",
                name="Multi-Agent Orchestration",
                description=(
                    "Routes your question to the most appropriate specialist agent "
                    "and returns the result. Handles SQL/data questions, document "
                    "search, and general knowledge queries."
                ),
                tags=["orchestrator", "routing"],
                examples=[
                    "How many orders were placed last month?",
                    "Find documents about GDPR compliance",
                    "Explain the difference between TCP and UDP",
                ],
            )
        ],
    )


@asynccontextmanager
async def lifespan(app):
    _state["tools"] = await load_tools()
    _state["graph"] = build_orchestrator(_state["tools"])
    agents = [t.name for t in _state["tools"]]
    logger.info("discovered agents", agents=agents, count=len(agents))
    logger.info("orchestrator ready", tool_count=len(_state["tools"]), port=PORT)
    yield
    await _stop_proxies()


def build_app() -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=OrchestratorExecutor(),
        task_store=InMemoryTaskStore(),
    )
    a2a = A2AStarletteApplication(
        agent_card=build_orchestrator_card(),
        http_handler=handler,
    )
    app = Starlette(
        lifespan=lifespan,
        routes=[Route("/reload", reload_endpoint, methods=["POST"])],
    )
    a2a.add_routes_to_app(app)
    return app


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
