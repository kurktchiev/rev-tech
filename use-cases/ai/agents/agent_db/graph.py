import os

import psycopg2
import psycopg2.extras
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from agents.base_agent import get_llm

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://demo:demo@localhost:5432/demo"
)

SYSTEM_PROMPT = """\
You are a database agent with read-only access to a PostgreSQL database.

## Workflow
1. First call list_tables() to see what tables exist (returns schema.table).
2. Call describe_table(table_name) to see columns and types (use schema.table format).
3. Write and execute SQL using run_query(sql). Use fully qualified table names (schema.table).

## Rules
- ONLY run SELECT statements. Never INSERT, UPDATE, DELETE, or DROP.
- Keep queries targeted -- use WHERE clauses and LIMIT.
- Summarise results in plain language, not raw table dumps.
- If a query returns no rows, say so clearly.
"""


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


@tool
def list_tables() -> str:
    """List all tables in the database (excludes system schemas)."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY table_schema, table_name"
            )
            tables = [f"{s}.{t}" for s, t in cur.fetchall()]
        return "\n".join(tables) if tables else "No tables found."
    finally:
        conn.close()


@tool
def describe_table(table_name: str) -> str:
    """Show column names, types, and nullability for a table.

    Args:
        table_name: Name of the table to describe.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # Support both "table" and "schema.table" formats
            if "." in table_name:
                schema, tbl = table_name.split(".", 1)
            else:
                schema, tbl = None, table_name
            query = (
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = %s "
            )
            params: list = [tbl]
            if schema:
                query += "AND table_schema = %s "
                params.append(schema)
            else:
                query += "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
            query += "ORDER BY ordinal_position"
            cur.execute(query, params)
            cols = cur.fetchall()
        if not cols:
            return f"Table '{table_name}' not found."
        return "\n".join(
            f"{name} ({dtype}, nullable={nullable})"
            for name, dtype, nullable in cols
        )
    finally:
        conn.close()


@tool
def run_query(sql: str) -> str:
    """Execute a read-only SQL query and return results.

    Args:
        sql: A SELECT query to run.
    """
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        return "ERROR: Only SELECT queries are allowed."
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            if not rows:
                return "No rows returned."
            cols = list(rows[0].keys())
            lines = [" | ".join(cols)]
            lines.append("-" * len(lines[0]))
            for r in rows:
                lines.append(" | ".join(str(r[c]) for c in cols))
            return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        conn.close()


def build_graph():
    llm = get_llm()
    return create_react_agent(
        llm,
        tools=[list_tables, describe_table, run_query],
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )
