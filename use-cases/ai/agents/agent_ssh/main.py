import os
from pathlib import Path

from agents.base_agent import BaseA2AAgent
from agents.agent_ssh.graph import build_graph

if __name__ == "__main__":
    port = int(os.environ.get("AGENT_PORT", 8080))
    card = BaseA2AAgent.load_card(Path(__file__).parent / "card.json", port)
    agent = BaseA2AAgent(graph=build_graph(), card=card)
    agent.run(port=port)
