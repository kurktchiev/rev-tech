import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote

import structlog

from agents.base_agent import BaseA2AAgent
from agents.teleport import open_db_tunnel

logger = structlog.get_logger()

# Query to find exactly one database. Narrow this to match a single target.
TSH_DB_QUERY = os.environ.get(
    "AGENT_DB_TSH_DISCOVERY_QUERY",
    'name == "demo-postgres-db"',
)
TSH_DB_USER = os.environ.get("AGENT_DB_USER", "")
TSH_DB_NAME = os.environ.get("AGENT_DB_NAME", "demo")
# When set, read tunnel endpoint from this file instead of running tsh discovery
DATABASES_CONFIG = os.environ.get("DATABASES_CONFIG", "")


def setup_db_tunnel():
    """Discover and tunnel to the database, setting DATABASE_URL."""
    if os.environ.get("DATABASE_URL"):
        logger.info("using DATABASE_URL from environment")
        return

    loop = asyncio.new_event_loop()
    db_info, proc = loop.run_until_complete(
        open_db_tunnel(
            query=TSH_DB_QUERY,
            databases_config=DATABASES_CONFIG or None,
            default_username=TSH_DB_USER,
            default_database=TSH_DB_NAME,
        )
    )

    user = db_info.get("username", "")
    dbname = db_info.get("database", "")
    host = db_info["host"]
    db_port = db_info["port"]

    # database-tunnel handles auth, so no password needed in the URL
    encoded_user = quote(user, safe="") if user else ""
    url = f"postgresql://{encoded_user}@{host}:{db_port}/{dbname}" if user else f"postgresql://{host}:{db_port}/{dbname}"
    os.environ["DATABASE_URL"] = url
    logger.info("database tunnel ready", db=db_info["name"], url=url)


if __name__ == "__main__":
    port = int(os.environ.get("AGENT_PORT", 8080))

    # Set up tunnel before importing graph (it reads DATABASE_URL at import time)
    setup_db_tunnel()

    from agents.agent_db.graph import build_graph

    card = BaseA2AAgent.load_card(Path(__file__).parent / "card.json", port)
    agent = BaseA2AAgent(graph=build_graph(), card=card)
    agent.run(port=port)
