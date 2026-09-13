"""HTTP client for the ZSYNC endpoint (/sap/bc/zsync) inside the SAP system."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from abap_cli.config import System

ENDPOINT = "/sap/bc/zsync"
DEFAULT_TIMEOUT = 600.0


class SapError(Exception):
    """A problem reported by SAP, already phrased for the user."""


@dataclass
class ImportResult:
    status: str
    object_count: int
    error_count: int
    warning_count: int
    objects: list[dict]

    @classmethod
    def from_json(cls, payload: dict) -> ImportResult:
        return cls(
            status=payload.get("status", "?"),
            object_count=int(payload.get("object_cnt", 0) or 0),
            error_count=int(payload.get("error_cnt", 0) or 0),
            warning_count=int(payload.get("warning_cnt", 0) or 0),
            objects=payload.get("objects", []) or [],
        )

    @property
    def failed(self) -> bool:
        return self.error_count > 0


class SapClient:
    def __init__(self, system: System, password: str, timeout: float = DEFAULT_TIMEOUT):
        self._system = system
        self._client = httpx.Client(
            base_url=system.host,
            auth=(system.user, password),
            verify=system.verify_tls,
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> SapClient:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _call(self, action: str, params: dict | None = None, content: bytes | None = None):
        query = {"sap-client": self._system.client, "action": action, **(params or {})}
        headers = {"Content-Type": "application/zip"} if content is not None else {}
        try:
            response = self._client.request(
                "POST" if content is not None else "GET",
                ENDPOINT,
                params=query,
                content=content,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise SapError(f"cannot reach {self._system.host}{ENDPOINT}: {exc}") from exc

        if response.status_code == 401:
            raise SapError(
                f"authentication failed for {self._system.describe()}. "
                f"Run 'abap login --system {self._system.name}'."
            )
        if response.status_code == 404:
            raise SapError(
                f"{ENDPOINT} not found on {self._system.host}. "
                "The ZSYNC endpoint is not installed in this system."
            )
        return response

    def ping(self) -> dict:
        response = self._call("ping")
        if "json" not in response.headers.get("content-type", ""):
            raise SapError(f"unexpected reply (HTTP {response.status_code}) - is ZSYNC installed?")
        return response.json()

    def export(self, package: str, include_subpackages: bool = True) -> bytes:
        response = self._call(
            "export",
            {"package": package, "ignore_subpackages": "" if include_subpackages else "X"},
        )
        if response.content[:2] != b"PK":
            detail = _message(response)
            raise SapError(f"export of {package} failed: {detail}")
        return response.content

    def import_zip(
        self,
        package: str,
        archive: bytes,
        transport: str = "",
        dry_run: bool = False,
    ) -> ImportResult:
        response = self._call(
            "import",
            {
                "package": package,
                "transport": transport,
                "dry_run": "X" if dry_run else "",
            },
            content=archive,
        )
        if "json" not in response.headers.get("content-type", ""):
            raise SapError(f"import failed: {_message(response)}")
        payload = response.json()
        if response.status_code >= 500:
            raise SapError(payload.get("message", str(payload)))
        return ImportResult.from_json(payload)


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", response.text[:500]))
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:500]}"
