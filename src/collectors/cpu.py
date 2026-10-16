from datetime import datetime, timezone
from typing import Any

import psutil


def cpu_usage(interval: float = 2) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        utilization = psutil.cpu_percent(interval=interval)
        return {
            "timestamp": timestamp,
            "cpu_usage": utilization,
            "collection_error": None,
        }
    except Exception as exc:
        return {
            "timestamp": timestamp,
            "cpu_usage": None,
            "collection_error": str(exc),
        }
