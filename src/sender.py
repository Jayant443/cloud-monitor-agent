import logging
from typing import Any
import requests

logger = logging.getLogger(__name__)
_METRICS_PATH = "/api/metrics"

def send_metrics(
    payload: dict[str, Any],
    backend_url: str,
    timeout: float = 5.0,
    api_key: str | None = None,
) -> bool:
    base_url = backend_url.strip().rstrip("/")
    if not base_url:
        logger.warning("Metrics send skipped: backend URL is not configured")
        return False

    url = base_url if base_url.endswith(_METRICS_PATH) else base_url + _METRICS_PATH
    headers: dict[str, str] = {}
    if api_key and api_key.strip():
        headers["X-API-Key"] = api_key.strip()
    try:
        response = requests.post(url, json=payload, timeout=timeout, headers=headers or None)
    except requests.RequestException as exc:
        logger.warning(
            "Metrics send failed: %s",
            type(exc).__name__,
            extra={"event": "metrics_send_failed"},
        )
        return False
    except Exception:
        logger.exception("Unexpected metrics sender error")
        return False

    if not 200 <= response.status_code < 300:
        logger.warning(
            "Metrics backend returned HTTP %s",
            response.status_code,
            extra={"event": "metrics_send_rejected", "status_code": response.status_code},
        )
        return False

    logger.info(
        "Metrics sent to backend",
        extra={"event": "metrics_send_succeeded", "status_code": response.status_code},
    )
    return True
