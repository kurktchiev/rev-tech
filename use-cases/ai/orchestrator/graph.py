from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from orchestrator.llm import get_llm


def build_orchestrator(tools: list):
    """
    Compile a ReAct orchestrator graph bound to the given tools.
    Called at startup and again on every /reload.
    """
    llm = get_llm()
    llm_with_tools = llm.bind_tools(tools)

    async def agent_node(state: MessagesState):
        return {"messages": [await llm_with_tools.ainvoke(state["messages"])]}

    def should_continue(state: MessagesState):
        last = state["messages"][-1]
        return "tools" if last.tool_calls else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile()
