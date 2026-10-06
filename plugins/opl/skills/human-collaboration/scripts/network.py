"""Select a private IPv4 address for an explicitly requested LAN listener."""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess

from inbox import InboxError


PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def lan_address() -> str:
    """Prefer a physical Windows adapter with a gateway, then its route metric."""
    if os.name == "nt":
        # Query live adapters instead of hostname DNS, which can return VPN,
        # Hyper-V or stale addresses. This command does not change network settings.
        command = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$configs = Get-NetIPConfiguration -ErrorAction Stop |
    Where-Object { $_.NetAdapter.Status -eq 'Up' -and $_.NetAdapter.HardwareInterface } |
    Sort-Object @{Expression={if ($_.IPv4DefaultGateway) {0} else {1}}},
                @{Expression={$_.NetIPv4Interface.InterfaceMetric}}, InterfaceIndex
$addresses = @($configs | ForEach-Object { $_.IPv4Address.IPAddress })
ConvertTo-Json -InputObject $addresses -Compress
"""
        try:
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, encoding="utf-8", timeout=15, check=True)
            candidates = json.loads(result.stdout)
            if not isinstance(candidates, list):
                raise InboxError("LAN discovery returned an invalid adapter list")
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or str(error)).strip()
            raise InboxError(f"cannot inspect LAN adapters: {detail}; choose --host explicitly") from error
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            raise InboxError(f"cannot inspect LAN adapters: {error}; choose --host explicitly") from error
    else:
        # A UDP route lookup selects the local source address without sending
        # an application datagram. No public lookup service is contacted.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect(("192.0.2.1", 9))
                candidates = [route.getsockname()[0]]
        except OSError as error:
            raise InboxError(f"cannot inspect the local route: {error}; choose --host explicitly") from error
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError as error:
            raise InboxError(f"LAN discovery returned an invalid address: {candidate}") from error
        if address.version == 4 and any(address in network for network in PRIVATE_NETWORKS):
            return str(address)
    raise InboxError("no private LAN IPv4 address found; choose --host explicitly (127.0.0.1 for local-only access)")
