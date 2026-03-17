import json
import uuid
import jwt
from typing import Optional, Dict
import chainlit as cl
import httpx
from os import environ


ORCHESTRATOR_URL = environ.get("ORCHESTRATOR_URL", "http://localhost:9000")
ORCHESTRATOR_FALLBACK_URL = environ.get("ORCHESTRATOR_FALLBACK_URL", "")

SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Only call tools if they are strictly necessary to answer the user's question. "
    "If the user greets you or asks a general question, respond directly."
)

# ----------------------------------------------------------------------------------------
# Teleport JWT authentication: extract user info from the token and create a Chainlit user
# ----------------------------------------------------------------------------------------

@cl.header_auth_callback
async def header_auth_callback(headers: Dict) -> Optional[cl.User]:
    token = headers.get("teleport-jwt-assertion")
    if not token:
        # Local development: allow unauthenticated access
        return cl.User(identifier="dev", display_name="Developer")

    try:
        payload = jwt.decode(token, options={"verify_signature": False})

        sub = payload.get("sub")
        traits = payload.get("traits", {})
        if not sub:
            return None

        display = payload.get("username", sub)

        return cl.User(
            identifier=sub,
            display_name=display,
            metadata={"traits": traits, "display_name": display, "provider": "teleport"},
        )
    except Exception as e:
        print(f"Failed to parse Teleport JWT: {e}")
        return None


# ---------------------------------------------------------------------
# A2A client: send message to orchestrator via JSON-RPC 2.0
# ---------------------------------------------------------------------

async def a2a_send_message(text: str) -> str:
    """Send a message/send JSON-RPC request to the orchestrator and return the response text."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }

    urls = [ORCHESTRATOR_URL]
    if ORCHESTRATOR_FALLBACK_URL:
        urls.append(ORCHESTRATOR_FALLBACK_URL)

    last_err = None
    async with httpx.AsyncClient(timeout=120) as client:
        for url in urls:
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_err = e
                continue
        else:
            raise last_err

    # Handle JSON-RPC error
    if "error" in data:
        error = data["error"]
        return f"Error from orchestrator: {error.get('message', 'unknown error')}"

    result = data.get("result", {})

    # Task response: artifacts[].parts[]
    artifacts = result.get("artifacts", [])
    if artifacts:
        for artifact in artifacts:
            for part in artifact.get("parts", []):
                if part.get("kind") == "text":
                    return part["text"]

    # Message response: result.parts[] or result.message.parts[]
    for key in ("parts", "message"):
        container = result.get(key)
        if container is None:
            continue
        parts = container if isinstance(container, list) else container.get("parts", [])
        for part in parts:
            if part.get("kind") == "text":
                return part["text"]

    # Status message fallback
    status = result.get("status", {})
    status_msg = status.get("message")
    if status_msg and isinstance(status_msg, dict):
        for part in status_msg.get("parts", []):
            if part.get("kind") == "text":
                return part["text"]

    return "No response from orchestrator."


# ---------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------

@cl.on_message
async def main(message: cl.Message):
    msg = cl.Message(content="")
    await msg.send()

    try:
        response_text = await a2a_send_message(message.content)
    except httpx.HTTPStatusError as e:
        response_text = f"Orchestrator returned HTTP {e.response.status_code}"
    except httpx.ConnectError:
        response_text = f"Could not connect to orchestrator at {ORCHESTRATOR_URL}"
    except Exception as e:
        response_text = f"Error communicating with orchestrator: {e}"

    msg.content = response_text
    await msg.update()
