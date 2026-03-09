"""Teleport resource discovery via tsh CLI.

Provides async helpers for discovering apps and databases via ``tsh apps ls``
and ``tsh db ls``, and for starting local proxies (``tsh proxy app`` /
``tsh proxy db --tunnel``).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

import structlog

logger = structlog.get_logger()

_PROXY_READY_RE = re.compile(r"((?:127\.0\.0\.1|localhost):\d+)")


def _require_tsh() -> str:
    tsh = shutil.which("tsh")
    if tsh is None:
        raise RuntimeError("tsh binary not found in PATH")
    return tsh


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

async def discover_apps(query: str) -> list[str]:
    """Discover Teleport apps matching *query* via ``tsh apps ls``.

    Returns a sorted list of app names.
    """
    tsh = _require_tsh()
    proc = await asyncio.create_subprocess_exec(
        tsh, "apps", "ls", f"--query={query}", "--format=json",
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
    names.sort()
    return names


async def discover_databases(
    query: str,
    default_username: str = "",
    default_database: str = "",
) -> list[dict]:
    """Discover Teleport databases matching *query* via ``tsh db ls``.

    Returns a sorted list of dicts with keys:
    ``name``, ``protocol``, ``username``, ``database``.

    Username/database are pulled from ``db-user`` / ``db-name`` labels on the
    Teleport database resource, falling back to the provided defaults.
    """
    tsh = _require_tsh()
    proc = await asyncio.create_subprocess_exec(
        tsh, "db", "ls", f"--query={query}", "--format=json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"tsh db ls failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

    dbs = json.loads(stdout.decode())
    results = []
    for db in dbs:
        meta = db.get("metadata", {})
        spec = db.get("spec", {})
        labels = meta.get("labels", {})
        name = meta.get("name") or db.get("name")
        if not name:
            continue
        results.append({
            "name": name,
            "protocol": spec.get("protocol") or db.get("protocol", ""),
            "username": labels.get("db-user") or default_username,
            "database": labels.get("db-name") or default_database,
        })
    results.sort(key=lambda x: x["name"])
    return results


# ---------------------------------------------------------------------------
# Local proxies (for local dev)
# ---------------------------------------------------------------------------

async def _wait_for_listener(
    proc: asyncio.subprocess.Process,
    label: str,
    timeout: float = 30,
) -> str:
    """Read stdout until a ``127.0.0.1:<port>`` address appears."""
    lines_seen: list[str] = []
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            if not line:
                raise RuntimeError(
                    f"{label} exited unexpectedly. Output: {''.join(lines_seen)}"
                )
            text = line.decode().strip()
            lines_seen.append(text + "\n")
            logger.debug("proxy output", label=label, line=text)
            m = _PROXY_READY_RE.search(text)
            if m:
                return m.group(1)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(
            f"{label} did not print a listener address within {timeout}s. "
            f"Output: {''.join(lines_seen)}"
        )


async def start_app_proxy(app_name: str) -> tuple[str, asyncio.subprocess.Process]:
    """Start ``tsh proxy app`` and return ``(local_url, process)``."""
    tsh = _require_tsh()
    proc = await asyncio.create_subprocess_exec(
        tsh, "proxy", "app", app_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    addr = await _wait_for_listener(proc, f"tsh proxy app {app_name}")
    local_url = f"http://{addr}"
    logger.info("app proxy started", app=app_name, url=local_url)
    return local_url, proc


async def start_db_proxy(db_info: dict) -> tuple[str, asyncio.subprocess.Process]:
    """Start ``tsh proxy db --tunnel`` and return ``(local_addr, process)``.

    *db_info* should have ``name`` and optionally ``username``, ``database``.
    """
    tsh = _require_tsh()
    cmd = [tsh, "proxy", "db", "--tunnel", db_info["name"]]
    if db_info.get("username"):
        cmd.extend(["--db-user", db_info["username"]])
    if db_info.get("database"):
        cmd.extend(["--db-name", db_info["database"]])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    addr = await _wait_for_listener(proc, f"tsh proxy db {db_info['name']}")
    logger.info("db proxy started", db=db_info["name"], addr=addr)
    return addr, proc


async def discover_one_database(query: str, **kwargs) -> dict:
    """Discover exactly one database matching *query*.

    Raises ``RuntimeError`` if zero or more than one database matches.
    Extra keyword arguments are forwarded to :func:`discover_databases`.
    """
    dbs = await discover_databases(query, **kwargs)
    if len(dbs) == 0:
        raise RuntimeError(f"No databases matched query: {query}")
    if len(dbs) > 1:
        names = [d["name"] for d in dbs]
        raise RuntimeError(
            f"Expected exactly 1 database but found {len(dbs)} matching query: {query}  "
            f"Matches: {', '.join(names)}  "
            f"Narrow the query to match a single database."
        )
    logger.info("discovered database", db=dbs[0]["name"], query=query)
    return dbs[0]


async def open_db_tunnel(
    query: str,
    databases_config: str | None = None,
    **kwargs,
) -> tuple[dict, asyncio.subprocess.Process | None]:
    """Discover a single database and open a tunnel to it.

    In tunnel mode (when *databases_config* points to an existing file with
    exactly one entry), reads the endpoint from that file — no proxy process
    is started since the tbot sidecar already provides the tunnel.

    Otherwise, discovers via ``tsh db ls`` (enforcing a single match) and
    starts ``tsh proxy db --tunnel``.

    Returns ``(db_info, process | None)`` where *db_info* has keys:
    ``name``, ``host``, ``port``, ``protocol``, ``username``, ``database``.
    """
    # K8s path: tbot sidecar tunnel already running, read from config
    if databases_config:
        config_path = Path(databases_config)
        if config_path.exists():
            dbs = json.loads(config_path.read_text())
            if len(dbs) == 1:
                db = dbs[0]
                logger.info("using tunnel from config", db=db["name"],
                            host=db["host"], port=db["port"])
                return db, None
            if len(dbs) > 1:
                names = [d["name"] for d in dbs]
                raise RuntimeError(
                    f"Expected exactly 1 database in {databases_config} but found {len(dbs)}: "
                    f"{', '.join(names)}"
                )

    # Local dev path: discover + start proxy
    db_meta = await discover_one_database(query, **kwargs)
    addr, proc = await start_db_proxy(db_meta)
    host, port = addr.rsplit(":", 1)
    db_info = {
        "name": db_meta["name"],
        "protocol": db_meta.get("protocol", ""),
        "host": host,
        "port": int(port),
        "username": db_meta.get("username", ""),
        "database": db_meta.get("database", ""),
    }
    return db_info, proc


async def stop_proxies(proxies: list[asyncio.subprocess.Process]) -> None:
    """Terminate a list of proxy processes."""
    for proc in proxies:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            proc.kill()
