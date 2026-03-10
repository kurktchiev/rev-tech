# Base Agent

Shared foundation for all A2A specialist agents. Provides the glue between a LangGraph graph and the Google A2A protocol so you can focus on agent logic instead of protocol plumbing.

This is a starting point -- extend it to build new specialist agents.

## What It Provides

**`BaseA2AAgent`** -- Takes a compiled LangGraph graph and an `AgentCard`, wires them into an `A2AStarletteApplication`, and starts a uvicorn server. Handles agent card serving (`/.well-known/agent.json`) and A2A JSON-RPC message handling (`POST /`).

**`LangGraphAgentExecutor`** -- Adapts any LangGraph graph to the A2A `AgentExecutor` interface. Extracts text from incoming A2A messages, invokes the graph, and emits the response as an A2A artifact.

**`get_llm()`** -- Shared LLM factory controlled by `LLM_PROVIDER` env var:

| `LLM_PROVIDER` | Backend | Key env vars |
|---|---|---|
| `anthropic` (default) | Anthropic Claude | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `openai` | OpenAI-compatible (LM Studio, etc.) | `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY` |
| `ollama` | Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |

## Extending: Create a New Agent

Create a new directory under `agents/` with four files:

```
agents/my_agent/
├── __init__.py
├── card.json      # Agent metadata and skills (orchestrator reads this)
├── graph.py       # Your LangGraph graph
└── main.py        # Entry point
```

**`graph.py`** -- Build your graph. Must accept `MessagesState` and return updated messages.

```python
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from agents.base_agent.llm import get_llm

@tool
def my_tool(query: str) -> str:
    """Description the LLM reads to decide when to call this tool."""
    return "result"

def build_graph():
    llm = get_llm().bind_tools([my_tool])

    def agent_node(state: MessagesState):
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state: MessagesState):
        return "tools" if state["messages"][-1].tool_calls else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode([my_tool]))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile()
```

**`main.py`** -- Load the card, build the graph, and run.

```python
import os
from pathlib import Path
from agents.base_agent.base_agent import BaseA2AAgent
from agents.my_agent.graph import build_graph

if __name__ == "__main__":
    port = int(os.environ.get("AGENT_PORT", 8080))
    card = BaseA2AAgent.load_card(Path(__file__).parent / "card.json", port)
    agent = BaseA2AAgent(graph=build_graph(), card=card)
    agent.run(port=port)
```

See `general_agent/` for the simplest working example.
