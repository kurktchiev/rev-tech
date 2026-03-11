"""Builder for tbot YAML configuration files.

Generates tbot v2 configs with identity, application-tunnel, and
database-tunnel service entries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class AppTunnel:
    app_name: str
    port: int


@dataclass
class DbTunnel:
    service: str
    port: int
    username: str = ""
    database: str = ""


@dataclass
class TbotConfigBuilder:
    """Builds a tbot v2 YAML config and companion JSON manifests."""

    proxy_server: str
    join_token: str
    join_method: str = "kubernetes"
    storage_path: str = "/opt/machine-id/storage"
    identity_path: str = "/opt/machine-id/identity"
    app_tunnels: list[AppTunnel] = field(default_factory=list)
    db_tunnels: list[DbTunnel] = field(default_factory=list)

    # -- Convenience: populate from discovery results ----------------------

    def add_app_tunnels(self, app_names: list[str], base_port: int = 18000) -> None:
        """Add application-tunnel entries for discovered apps."""
        for i, name in enumerate(sorted(app_names)):
            self.app_tunnels.append(AppTunnel(app_name=name, port=base_port + i))

    def add_db_tunnels(self, db_list: list[dict], base_port: int = 19000) -> None:
        """Add database-tunnel entries from discovery metadata.

        Each dict in *db_list* should have ``name`` and optionally
        ``username``, ``database``.
        """
        for i, db in enumerate(sorted(db_list, key=lambda d: d["name"])):
            self.db_tunnels.append(DbTunnel(
                service=db["name"],
                port=base_port + i,
                username=db.get("username", ""),
                database=db.get("database", ""),
            ))

    # -- Render ------------------------------------------------------------

    def render_tbot_yaml(self) -> str:
        """Render the full tbot v2 YAML config."""
        lines = [
            "version: v2",
            f"proxy_server: \"{self.proxy_server}\"",
            "onboarding:",
            f"  token: \"{self.join_token}\"",
            f"  join_method: {self.join_method}",
            "storage:",
            "  type: directory",
            f"  path: {self.storage_path}",
            "services:",
            "  - type: identity",
            "    destination:",
            "      type: directory",
            f"      path: {self.identity_path}",
        ]

        for t in self.app_tunnels:
            lines.append(f"  - type: application-tunnel")
            lines.append(f"    app_name: {t.app_name}")
            lines.append(f"    listen: tcp://127.0.0.1:{t.port}")

        for t in self.db_tunnels:
            lines.append(f"  - type: database-tunnel")
            lines.append(f"    service: {t.service}")
            lines.append(f"    listen: tcp://127.0.0.1:{t.port}")
            if t.username:
                lines.append(f"    username: {t.username}")
            if t.database:
                lines.append(f"    database: {t.database}")

        return "\n".join(lines) + "\n"

    def render_agents_json(self) -> str:
        """Render agents.json mapping app tunnel names to local URLs."""
        entries = [
            {"name": t.app_name, "url": f"http://127.0.0.1:{t.port}"}
            for t in self.app_tunnels
        ]
        return json.dumps(entries, indent=2) + "\n"

    def render_databases_json(self) -> str:
        """Render databases.json mapping db tunnels to local endpoints."""
        entries = []
        for t in self.db_tunnels:
            entries.append({
                "name": t.service,
                "host": "127.0.0.1",
                "port": t.port,
                "username": t.username,
                "database": t.database,
            })
        return json.dumps(entries, indent=2) + "\n"
