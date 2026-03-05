import uuid

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel


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
            resp = await client.post(_base_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

        parts = (
            data.get("result", {})
            .get("artifacts", [{}])[0]
            .get("parts", [])
        )
        return next(
            (p["text"] for p in parts if p.get("kind") == "text"),
            "No response",
        )

    return StructuredTool.from_function(
        coroutine=call_agent,
        name=card["name"].replace(" ", "_").lower(),
        description=description,
        args_schema=AgentInput,
    )
