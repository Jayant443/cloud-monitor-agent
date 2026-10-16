from datetime import datetime, timezone
import math
from typing import Any

try:
    import docker
    from docker.errors import DockerException
except Exception:
    docker = None

    class DockerException(Exception):
        pass

def _timestamp() -> datetime:
    return datetime.now(timezone.utc)

def _parse_docker_time(value: str | None) -> datetime | None:
    if not value or value.startswith("0001-"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None

def _nonnegative_number(value: Any) -> int | float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return value

def _cpu_percent(stats: dict[str, Any]) -> float | None:
    cpu = stats.get("cpu_stats") or {}
    previous = stats.get("precpu_stats") or {}
    cpu_total = _nonnegative_number((cpu.get("cpu_usage") or {}).get("total_usage"))
    previous_cpu_total = _nonnegative_number((previous.get("cpu_usage") or {}).get("total_usage"))
    system_total = _nonnegative_number(cpu.get("system_cpu_usage"))
    previous_system_total = _nonnegative_number(previous.get("system_cpu_usage"))
    if None in (cpu_total, previous_cpu_total, system_total, previous_system_total):
        return None

    cpu_delta = cpu_total - previous_cpu_total
    system_delta = system_total - previous_system_total
    if cpu_delta < 0 or system_delta <= 0:
        return None

    online_cpus = _nonnegative_number(cpu.get("online_cpus"))
    if not online_cpus:
        percpu_usage = (cpu.get("cpu_usage") or {}).get("percpu_usage")
        online_cpus = len(percpu_usage) if isinstance(percpu_usage, list) else None
    if not online_cpus:
        return None
    return round((cpu_delta / system_delta) * online_cpus * 100, 2)

def _memory_values(stats: dict[str, Any]) -> tuple[int | None, int | None]:
    memory = stats.get("memory_stats") or {}
    usage = _nonnegative_number(memory.get("usage"))
    limit = _nonnegative_number(memory.get("limit"))
    cache_stats = memory.get("stats") or {}
    cache = cache_stats.get("inactive_file", cache_stats.get("total_inactive_file"))
    if cache is None:
        cache = cache_stats.get("cache", 0)
    cache = _nonnegative_number(cache)
    if usage is not None and cache is not None:
        usage = max(0, usage - cache)
    return (
        int(usage) if usage is not None else None,
        int(limit) if limit is not None else None,
    )

def _network_values(stats: dict[str, Any]) -> tuple[int | None, int | None]:
    networks = stats.get("networks") or {}
    if not isinstance(networks, dict) or not networks:
        return None, None

    received_values: list[int] = []
    transmitted_values: list[int] = []
    for values in networks.values():
        if not isinstance(values, dict):
            continue
        received = _nonnegative_number(values.get("rx_bytes"))
        transmitted = _nonnegative_number(values.get("tx_bytes"))
        if received is not None:
            received_values.append(int(received))
        if transmitted is not None:
            transmitted_values.append(int(transmitted))
    received_total = sum(received_values) if len(received_values) == len(networks) else None
    transmitted_total = (
        sum(transmitted_values) if len(transmitted_values) == len(networks) else None
    )
    received, transmitted = received_total, transmitted_total
    return received, transmitted

def _block_io_values(stats: dict[str, Any]) -> tuple[int | None, int | None]:
    block_stats = stats.get("blkio_stats") or {}
    entries = block_stats.get("io_service_bytes_recursive")
    if not isinstance(entries, list) or not entries:
        return None, None
    read_bytes = 0
    write_bytes = 0
    found_read = False
    found_write = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        operation = str(entry.get("op", "")).lower()
        value = _nonnegative_number(entry.get("value"))
        if value is None:
            continue
        if operation == "read":
            read_bytes += int(value)
            found_read = True
        elif operation == "write":
            write_bytes += int(value)
            found_write = True
    return (
        read_bytes if found_read else None,
        write_bytes if found_write else None,
    )

def _container_record(container: Any, sampled_at: datetime) -> dict[str, Any]:
    errors: list[str] = []
    try:
        container.reload()
        attrs = container.attrs or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        status = state.get("Status", getattr(container, "status", "unknown"))
        image_data = config.get("Image")
        if not image_data:
            image_data = getattr(container, "image", None)
            image_data = getattr(image_data, "tags", None)
        if isinstance(image_data, list):
            image_data = image_data[0] if image_data else None
        if isinstance(image_data, dict):
            image_data = image_data.get("id")

        started = _parse_docker_time(state.get("StartedAt"))
        ended = _parse_docker_time(state.get("FinishedAt"))
        uptime = None
        if started:
            if status == "running":
                uptime = max(0.0, (sampled_at - started).total_seconds())
            elif ended:
                uptime = max(0.0, (ended - started).total_seconds())

        health_data = state.get("Health")
        if health_data is None:
            health = "not_configured"
        elif isinstance(health_data, dict):
            health = health_data.get("Status") or "unknown"
        else:
            health = "unknown"
        record: dict[str, Any] = {
            "timestamp": sampled_at.isoformat(),
            "container_id": getattr(container, "id", None),
            "name": getattr(container, "name", None),
            "image": image_data,
            "status": status,
            "cpu_usage_percent": None,
            "memory_usage_bytes": None,
            "memory_limit_bytes": None,
            "network_received_bytes": None,
            "network_transmitted_bytes": None,
            "block_read_bytes": None,
            "block_write_bytes": None,
            "restart_count": attrs.get("RestartCount"),
            "uptime_seconds": uptime,
            "exit_code": state.get("ExitCode") if status != "running" else None,
            "health_status": health,
            "collection_errors": errors,
        }

        if status == "running":
            try:
                stats = container.stats(stream=False)
                if not isinstance(stats, dict):
                    errors.append("stats collection returned no data")
                    return record
                record["cpu_usage_percent"] = _cpu_percent(stats)
                record["memory_usage_bytes"], record["memory_limit_bytes"] = (
                    _memory_values(stats)
                )
                received, transmitted = _network_values(stats)
                record["network_received_bytes"] = received
                record["network_transmitted_bytes"] = transmitted
                record["block_read_bytes"], record["block_write_bytes"] = (
                    _block_io_values(stats)
                )
            except Exception as exc:
                errors.append(f"stats collection failed: {exc}")
        return record
    except Exception as exc:
        return {
            "timestamp": sampled_at.isoformat(),
            "container_id": getattr(container, "id", None),
            "name": getattr(container, "name", None),
            "image": None,
            "status": "unknown",
            "cpu_usage_percent": None,
            "memory_usage_bytes": None,
            "memory_limit_bytes": None,
            "network_received_bytes": None,
            "network_transmitted_bytes": None,
            "block_read_bytes": None,
            "block_write_bytes": None,
            "restart_count": None,
            "uptime_seconds": None,
            "exit_code": None,
            "health_status": "unknown",
            "collection_errors": [f"container collection failed: {exc}"],
        }

def container_usage(client: Any | None = None) -> dict[str, Any]:
    sampled_at = _timestamp()
    if docker is None and client is None:
        return {
            "timestamp": sampled_at.isoformat(),
            "containers": [],
            "collection_errors": ["Docker SDK is not available"],
        }
    owns_client = client is None
    try:
        client = client or docker.from_env()
        containers = client.containers.list(all=True)
        records = [_container_record(container, sampled_at) for container in containers]
        return {
            "timestamp": sampled_at.isoformat(),
            "containers": records,
            "collection_errors": [],
        }
    except DockerException as exc:
        return {
            "timestamp": sampled_at.isoformat(),
            "containers": [],
            "collection_errors": [f"Docker collection failed: {exc}"],
        }
    except Exception as exc:
        return {
            "timestamp": sampled_at.isoformat(),
            "containers": [],
            "collection_errors": [f"Container listing failed: {exc}"],
        }
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:
                pass
