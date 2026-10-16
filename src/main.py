import argparse
import json
import logging
import math
import os
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any
from application_health import check_endpoints
from collectors.cpu import cpu_usage
from collectors.container import container_usage
from collectors.disk import disk_usage
from collectors.host import host_identity
from collectors.memory import memory_usage
from collectors.network import network_usage
from collectors.process import process_usage
from monitoring import AgentHealthMonitor
from sender import send_metrics

logger = logging.getLogger(__name__)

def _csv_setting(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]

def _float_setting(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and value > 0 else default
    except ValueError:
        return default

def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

def _reported_errors(value: Any) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key in ("collection_error", "error"):
            if value.get(key):
                errors.append(str(value[key]))
        nested_errors = value.get("collection_errors")
        if isinstance(nested_errors, list):
            errors.extend(str(error) for error in nested_errors if error)
        for key, item in value.items():
            if key not in {"collection_error", "collection_errors", "error"}:
                errors.extend(_reported_errors(item))
    elif isinstance(value, list):
        for item in value:
            errors.extend(_reported_errors(item))
    return errors

def _collect(monitor: AgentHealthMonitor, name: str, collector: Any, *args: Any, **kwargs: Any) -> Any:
    result = monitor.run(name, collector, *args, **kwargs)
    for error in _reported_errors(result):
        logger.warning("Collector %s reported an error: %s", name, error)
    return result

def _configured_endpoints() -> list[dict[str, str]]:
    try:
        endpoints = json.loads(os.getenv("APP_HEALTH_ENDPOINTS", "[]"))
        if isinstance(endpoints, list):
            return [item for item in endpoints if isinstance(item, dict) and item.get("url")]
    except (json.JSONDecodeError, TypeError):
        pass
    return [{"name": "configuration_error", "url": "invalid://configuration"}]

def _configured_processes() -> tuple[bool, list[int], list[str]]:
    enabled = os.getenv("PROCESS_MONITOR_ENABLED", "false").casefold() in {
        "1", "true", "yes", "on"
    }
    pids: list[int] = []
    for value in _csv_setting("PROCESS_MONITOR_PIDS"):
        try:
            pids.append(int(value))
        except ValueError:
            logger.warning("Ignoring invalid process PID setting: %s", value)
    return enabled, pids, _csv_setting("PROCESS_MONITOR_NAMES")

def _max_cycles_setting() -> int | None:
    raw = os.getenv("MAX_CYCLES", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid MAX_CYCLES setting: %s", raw)
        return None
    return value if value > 0 else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cloud monitoring agent")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Collect and send a single cycle, then exit (CI/smoke tests).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    monitor = AgentHealthMonitor()
    endpoints = _configured_endpoints()
    process_enabled, process_pids, process_names = _configured_processes()
    collection_interval = _float_setting("COLLECTION_INTERVAL_SECONDS", 2)
    backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
    backend_timeout = _float_setting("BACKEND_TIMEOUT_SECONDS", 5)
    mount_points = _csv_setting("DISK_MOUNT_POINTS") or ["/"]
    max_cycles = 1 if args.once else _max_cycles_setting()

    shutdown = threading.Event()

    def _handle_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s, shutting down", signum)
        shutdown.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, _handle_shutdown)
        except (OSError, ValueError):
            pass

    cycles = 0
    while not shutdown.is_set():
        cycle_started = time.monotonic()
        try:
            cycle_timestamp = datetime.now(timezone.utc).isoformat()
            cpu_reading = _collect(monitor, "cpu", cpu_usage, 0)
            memory_reading = _collect(monitor, "memory", memory_usage)
            disk_reading = _collect(monitor, "disk", disk_usage, mount_points)
            network_reading = _collect(monitor, "network", network_usage)
            containers_reading = _collect(monitor, "containers", container_usage)
            host_reading = _collect(monitor, "host", host_identity)
            application_reading = _collect(
                monitor,
                "application_health",
                check_endpoints,
                endpoints,
                _float_setting("APP_HEALTH_TIMEOUT_SECONDS", 5),
            )
            process_reading = _collect(
                monitor,
                "processes",
                process_usage,
                process_enabled,
                process_pids,
                process_names,
            )
            payload = {
                "timestamp": cycle_timestamp,
                "cpu": cpu_reading,
                "memory": memory_reading,
                "disk": disk_reading,
                "network": network_reading,
                "containers": containers_reading,
                "host": host_reading,
                "application_health": application_reading,
                "processes": process_reading,
                "agent_health": monitor.report(),
            }
            json_payload = _json_compatible(payload)
            print(json.dumps(json_payload, allow_nan=False), flush=True)
            send_metrics(json_payload, backend_url, backend_timeout)
        except Exception:
            logger.exception("Collection cycle failed, continuing")

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            logger.info("Reached max cycles (%s), exiting", max_cycles)
            break

        elapsed = time.monotonic() - cycle_started
        remaining = collection_interval - elapsed
        if remaining > 0:
            shutdown.wait(timeout=remaining)
        else:
            logger.warning(
                "Collection cycle took %.3fs, longer than the %.3fs interval",
                elapsed,
                collection_interval,
            )


if __name__ == "__main__":
    main()
