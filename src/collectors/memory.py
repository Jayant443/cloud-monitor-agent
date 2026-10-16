from datetime import datetime, timezone
from typing import Any

import psutil


def memory_usage() -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        memory = psutil.virtual_memory()
        return {
            "timestamp": timestamp,
            "memory_usage": memory.percent,
            "used_bytes": memory.used,
            "available_bytes": memory.available,
            "total_bytes": memory.total,
            "collection_error": None,
        }
    except Exception as exc:
        return {
            "timestamp": timestamp,
            "memory_usage": None,
            "used_bytes": None,
            "available_bytes": None,
            "total_bytes": None,
            "collection_error": str(exc),
        }
