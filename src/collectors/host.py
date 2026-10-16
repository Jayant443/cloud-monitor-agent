import hashlib
import ipaddress
import os
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import psutil

_MACHINE_ID_PATHS = ("/rootfs/etc/machine-id", "/etc/machine-id", "/var/lib/dbus/machine-id")

def _machine_id_source() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                if value:
                    return str(value)
        except (ImportError, OSError):
            pass

    for path in _MACHINE_ID_PATHS:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
            if value:
                return value
        except (OSError, UnicodeError):
            continue
    return "\0".join((platform.system(), platform.machine(), platform.node()))

def _stable_machine_identifier() -> str:
    digest = hashlib.sha256(_machine_id_source().encode("utf-8")).hexdigest()
    return f"host-{digest}"

def _os_version() -> str:
    if platform.system() == "Linux":
        try:
            release = platform.freedesktop_os_release()
            return release.get("PRETTY_NAME") or platform.release()
        except (AttributeError, OSError):
            pass
    return platform.release()

def _available_ip_addresses() -> list[str]:
    addresses: set[str] = set()
    for interface_addresses in psutil.net_if_addrs().values():
        for address in interface_addresses:
            if address.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            value = address.address.split("%", 1)[0]
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified:
                continue
            addresses.add(str(parsed))
    return sorted(addresses, key=lambda item: (ipaddress.ip_address(item).version, item))

def host_identity() -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    try:
        ip_addresses = _available_ip_addresses()
    except Exception as exc:
        ip_addresses = []
        errors.append(f"IP address collection failed: {exc}")

    try:
        machine_identifier = _stable_machine_identifier()
    except Exception as exc:
        fallback = "\0".join((platform.system(), platform.machine(), platform.node()))
        machine_identifier = f"host-{hashlib.sha256(fallback.encode()).hexdigest()}"
        errors.append(f"Machine identifier fallback used: {exc}")

    return {
        "timestamp": timestamp,
        "machine_id": machine_identifier,
        "hostname": os.getenv("AGENT_HOSTNAME", "").strip() or platform.node(),
        "operating_system": platform.system(),
        "os_version": _os_version(),
        "architecture": platform.machine(),
        "ip_addresses": ip_addresses,
        "collection_errors": errors,
    }
