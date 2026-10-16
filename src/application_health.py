from datetime import datetime, timezone
import time
from typing import Any, Iterable
import requests

def check_endpoints(endpoints: Iterable[dict[str, str]], timeout: float = 5.0) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for endpoint in endpoints:
        name = endpoint.get("name") or endpoint.get("url", "unnamed")
        url = endpoint.get("url", "")
        timestamp = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        try:
            response = requests.get(url, timeout=timeout)
            duration = time.monotonic() - started
            status = response.status_code
            results.append({
                "name": name,
                "response_status": status,
                "response_time_seconds": round(duration, 6),
                "available": 200 <= status < 400,
                "timestamp": timestamp,
                "error": None,
            })
        except requests.RequestException as exc:
            results.append({
                "name": name,
                "response_status": None,
                "response_time_seconds": round(time.monotonic() - started, 6),
                "available": False,
                "timestamp": timestamp,
                "error": f"Request failed: {exc.__class__.__name__}",
            })
        except Exception as exc:
            results.append({
                "name": name,
                "response_status": None,
                "response_time_seconds": round(time.monotonic() - started, 6),
                "available": False,
                "timestamp": timestamp,
                "error": f"Request failed: {exc.__class__.__name__}",
            })
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoints": results,
    }
