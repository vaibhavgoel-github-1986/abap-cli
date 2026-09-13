"""Connection profiles and credential handling.

Profiles live in ~/.abap-cli/config.json so the CLI works from any directory and
is not tied to any particular workspace or to the SAP MCP server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_HOME = Path.home() / ".abap-cli" / "config.json"
KEYCHAIN_SERVICE = "abap-cli"


class ConfigError(Exception):
    """Raised for anything the user can fix by editing config or passing a flag."""


@dataclass(frozen=True)
class System:
    name: str
    host: str
    user: str
    client: str
    verify_tls: bool = True
    description: str = ""

    @property
    def keychain_account(self) -> str:
        return f"{self.name}:{self.user}"

    def describe(self) -> str:
        return f"{self.user}@{self.host} client {self.client}"


def _read_raw() -> dict:
    if not CONFIG_HOME.is_file():
        return {}
    try:
        return json.loads(CONFIG_HOME.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONFIG_HOME} is not valid JSON: {exc}") from exc


def list_systems() -> dict[str, dict]:
    return _read_raw().get("systems", {})


def default_system() -> str:
    raw = _read_raw()
    systems = raw.get("systems", {})
    if raw.get("default_system"):
        return str(raw["default_system"])
    return next(iter(systems)) if len(systems) == 1 else ""


def save_system(system: System, make_default: bool = False) -> None:
    raw = _read_raw()
    systems = raw.setdefault("systems", {})
    systems[system.name] = {
        "host": system.host,
        "user": system.user,
        "client": system.client,
        "insecure": not system.verify_tls,
        "description": system.description,
    }
    if make_default or not raw.get("default_system"):
        raw["default_system"] = system.name

    _write_raw(raw)


def set_default(name: str) -> None:
    raw = _read_raw()
    if name not in raw.get("systems", {}):
        raise ConfigError(
            f"unknown system '{name}', available: {', '.join(sorted(raw.get('systems', {})))}"
        )
    raw["default_system"] = name
    _write_raw(raw)


def remove_system(name: str) -> None:
    raw = _read_raw()
    if name not in raw.get("systems", {}):
        raise ConfigError(f"unknown system '{name}'")
    del raw["systems"][name]
    if raw.get("default_system") == name:
        raw["default_system"] = next(iter(raw["systems"]), "")
    _write_raw(raw)


def _write_raw(raw: dict) -> None:
    CONFIG_HOME.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_HOME.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    CONFIG_HOME.chmod(0o600)


def resolve(
    name: str = "",
    host: str = "",
    user: str = "",
    client: str = "",
    insecure: bool = False,
) -> System:
    """Build a System from config, environment and explicit flags (flags win)."""
    systems = list_systems()
    chosen = name or os.environ.get("ABAP_SYSTEM", "") or default_system()

    if not chosen and not (host and user and client):
        if systems:
            raise ConfigError(
                "several systems configured, pick one with --system: "
                + ", ".join(sorted(systems))
            )
        raise ConfigError(
            f"no systems configured. Run 'abap init' or create {CONFIG_HOME}."
        )

    profile = systems.get(chosen, {})
    if chosen and systems and chosen not in systems:
        raise ConfigError(
            f"unknown system '{chosen}', available: {', '.join(sorted(systems))}"
        )

    resolved_host = host or os.environ.get("ABAP_HOST", "") or str(profile.get("host", ""))
    resolved_user = user or os.environ.get("ABAP_USER", "") or str(profile.get("user", ""))
    resolved_client = client or os.environ.get("ABAP_CLIENT", "") or str(profile.get("client", ""))

    missing = [
        label
        for label, value in (("host", resolved_host), ("user", resolved_user), ("client", resolved_client))
        if not value
    ]
    if missing:
        raise ConfigError(f"missing {', '.join(missing)} for system '{chosen or 'ad hoc'}'")

    return System(
        name=chosen or "ad-hoc",
        host=resolved_host.rstrip("/"),
        user=resolved_user,
        client=resolved_client,
        verify_tls=not (insecure or profile.get("insecure", False)),
        description=str(profile.get("description", "")),
    )


# --------------------------------------------------------------------------- secrets


def keychain_get(account: str) -> str:
    """Read a stored password, or '' when unavailable."""
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def keychain_store(account: str) -> bool:
    """Store a password. Omitting -w makes `security` prompt, so the secret
    never reaches argv or a log."""
    if sys.platform != "darwin":
        return False
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"]
    )
    return result.returncode == 0


def keychain_delete(account: str) -> bool:
    if sys.platform != "darwin":
        return False
    result = subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
        capture_output=True,
    )
    return result.returncode == 0


def password_for(system: System) -> str:
    """$ABAP_PASSWORD, then the OS keychain. Empty string means 'ask the user'."""
    return os.environ.get("ABAP_PASSWORD", "") or keychain_get(system.keychain_account)
