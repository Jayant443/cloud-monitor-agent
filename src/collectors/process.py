from datetime import datetime, timezone
from typing import Any, Iterable
import psutil

def _process_record(pid: int) -> dict[str, Any]:
    record: dict[str, Any] = {
        "pid": pid,
        "process_name": None,
        "cpu_percent": None,
        "memory_usage_bytes": None,
        "status": None,
        "collection_error": None,
    }
    try:
        process = psutil.Process(pid)
        record["process_name"] = process.name()
        record["cpu_percent"] = process.cpu_percent(interval=None)
        record["memory_usage_bytes"] = process.memory_info().rss
        record["status"] = process.status()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        record["collection_error"] = str(exc) or exc.__class__.__name__
    except Exception as exc:
        record["collection_error"] = str(exc)
    return record

def process_usage(enabled: bool = False, pids: Iterable[int] | None = None, names: Iterable[str] | None = None) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    if not enabled:
        return {
            "timestamp": timestamp,
            "enabled": False,
            "processes": [],
            "collection_errors": [],
        }

    selected_pids = {int(pid) for pid in (pids or [])}
    wanted_names = {name.casefold() for name in (names or [])}
    collection_errors: list[str] = []
    if wanted_names:
        try:
            for process in psutil.process_iter(["pid", "name"]):
                try:
                    if (process.info.get("name") or "").casefold() in wanted_names:
                        selected_pids.add(process.info["pid"])
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
        except Exception as exc:
            collection_errors.append(f"Process discovery failed: {exc}")

    return {
        "timestamp": timestamp,
        "enabled": True,
        "processes": [_process_record(pid) for pid in sorted(selected_pids)],
        "collection_errors": collection_errors,
    }
