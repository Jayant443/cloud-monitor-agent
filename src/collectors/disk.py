from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import psutil


def disk_usage(mount_points: Iterable[str] | str = ("/",)) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    mounts: list[dict[str, Any]] = []
    paths = (mount_points,) if isinstance(mount_points, str) else mount_points
    for mount_point in paths:
        try:
            usage = psutil.disk_usage(mount_point)
            mounts.append({
                "mount_point": mount_point,
                "usage_percent": usage.percent,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "collection_error": None,
            })
        except Exception as exc:
            mounts.append({
                "mount_point": mount_point,
                "usage_percent": None,
                "used_bytes": None,
                "free_bytes": None,
                "total_bytes": None,
                "collection_error": str(exc),
            })
    return {"timestamp": timestamp, "mounts": mounts}
