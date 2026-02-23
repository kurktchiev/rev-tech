import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
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
CONFIG_PATH = Path(os.environ.get("AGENTS_CONFIG", "orchestrator/agents.json"))

# Mutable state — updated on every reload
_state: dict = {"tools": [], "graph": None}


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------

async def fetch_agent_card(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base_url.rstrip('/')}/.well-known/agent.json")
        resp.raise_for_status()
        return resp.json()


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
    agentName: str
    eventType: str
    labels: dict
    timestamp: datetime


async def do_reload(request: ReloadRequest) -> None:
    try:
        new_tools = await load_tools_from_config()
        _state["tools"] = new_tools
        _state["graph"] = build_orchestrator(new_tools)
        logger.info("reload complete", tool_count=len(new_tools), trigger=request.agentName)
    except Exception as e:
        logger.error("reload failed", error=str(e))


async def reload_endpoint(request: Request) -> JSONResponse:
    data = await request.json()
    req = ReloadRequest(**data)
    logger.info("reload triggered", agent=req.agentName, event=req.eventType)
    return JSONResponse(
        {"status": "accepted", "agent": req.agentName},
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
    _state["tools"] = await load_tools_from_config()
    _state["graph"] = build_orchestrator(_state["tools"])
    logger.info("orchestrator ready", tool_count=len(_state["tools"]), port=PORT)
    yield


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
