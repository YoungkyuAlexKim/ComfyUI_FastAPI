"""Shared MCP IP identity helpers.

MCP callers do not have a browser cookie.  Their stable workspace ID is a
one-way digest of the client IP resolved by the trusted-proxy policy.  Browser
pairing uses the exact same helper so the two paths cannot drift.
"""

from __future__ import annotations

import hashlib
import ipaddress


def principal_for_mcp_ip(client_ip: str) -> str:
    normalized = str(client_ip or "unknown").strip() or "unknown"
    digest = hashlib.sha256(f"mcp-ip:{normalized}".encode("utf-8")).hexdigest()[:24]
    return f"mcp-ip-{digest}"


def parse_allowed_mcp_networks(raw_value: str | None) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw_part in str(raw_value or "").split(","):
        part = raw_part.strip()
        if part:
            networks.append(ipaddress.ip_network(part, strict=False))
    return tuple(networks)


def mcp_client_ip_allowed(client_ip: str, raw_value: str | None) -> bool:
    networks = parse_allowed_mcp_networks(raw_value)
    if not networks:
        return True
    try:
        address = ipaddress.ip_address(str(client_ip or "").strip())
    except ValueError:
        return False
    return any(address in network for network in networks)
