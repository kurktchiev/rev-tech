import uuid

import httpx
import structlog
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

logger = structlog.get_logger()


class AgentInput(BaseModel):
    query: str


def build_tool_from_card(card: dict, base_url: str, cert=None, ca=None) -> StructuredTool:
    """
    Build a LangChain tool from an A2A agent card.

    base_url is the address used for actual calls (Teleport publicAddr in Phase 2,
    or the direct agent URL in Phase 1). card["url"] is intentionally ignored —
    all calls route through base_url so Teleport can enforce auth + audit.
    """
    skill_descriptions = "\n".join(
        f"- {s['name']}: {s['description']}"
        for s in card.get("skills", [])
    )
    description = f"{card['description']}\n\nCapabilities:\n{skill_descriptions}"

    # Capture for closure
    _base_url = base_url.rstrip("/")
    _cert = cert
    _ca = ca

    async def call_agent(query: str) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [{"kind": "text", "text": query}],
                }
            },
        }
        async with httpx.AsyncClient(cert=_cert, verify=_ca or True) as client:
            resp = await client.post(_base_url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()

        # Check for JSON-RPC error
        if "error" in data:
            logger.error("a2a error", url=_base_url, error=data["error"])
            return f"Agent error: {data['error']}"

        result = data.get("result", {})
        logger.info("a2a response received", url=_base_url, keys=list(result.keys()))

        # A2A message/send can return a Task (with artifacts) or a Message (with parts)
        kind = result.get("kind", "")

        # Try Task format: result.artifacts[0].parts
        artifacts = result.get("artifacts") or []
        if artifacts:
            parts = artifacts[0].get("parts", [])
            text = next((p["text"] for p in parts if p.get("kind") == "text"), None)
            if text:
                return text

        # Try Message format: result.parts
        parts = result.get("parts", [])
        if parts:
            text = next((p["text"] for p in parts if p.get("kind") == "text"), None)
            if text:
                return text

        # Try history (last message in task history)
        history = result.get("history", [])
        if history:
            last = history[-1]
            parts = last.get("parts", [])
            text = next((p["text"] for p in parts if p.get("kind") == "text"), None)
            if text:
                return text

        # Try status message
        status = result.get("status", {})
        status_msg = status.get("message")
        if status_msg and isinstance(status_msg, dict):
            parts = status_msg.get("parts", [])
            text = next((p["text"] for p in parts if p.get("kind") == "text"), None)
            if text:
                return text

        logger.warning("no text in a2a response", url=_base_url, result=result)
        return "No response"

    return StructuredTool.from_function(
        coroutine=call_agent,
        name=card["name"].replace(" ", "_").lower(),
        description=description,
        args_schema=AgentInput,
    )
