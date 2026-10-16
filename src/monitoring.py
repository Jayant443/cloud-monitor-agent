from collections import deque
from datetime import datetime, timezone
import time
from typing import Any, Callable

def _result_errors(value: Any) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        error = value.get("collection_error")
        if error:
            errors.append(str(error))
        plural = value.get("collection_errors")
        if isinstance(plural, list):
            errors.extend(str(item) for item in plural if item)
        error = value.get("error")
        if error:
            errors.append(str(error))
        for key, nested in value.items():
            if key not in {"collection_error", "collection_errors", "error"}:
                errors.extend(_result_errors(nested))
    elif isinstance(value, list):
        for item in value:
            errors.extend(_result_errors(item))
    return errors

class AgentHealthMonitor:
    def __init__(self, recent_error_limit: int = 5) -> None:
        self._recent_error_limit = recent_error_limit
        self._collectors: dict[str, dict[str, Any]] = {}

    def run(self, name: str, collector: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()
        result: Any
        try:
            result = collector(*args, **kwargs)
            errors = _result_errors(result)
        except Exception as exc:
            result = {"collection_error": str(exc)}
            errors = [str(exc)]

        duration = max(0.0, time.monotonic() - started)
        state = self._collectors.setdefault(name, {
            "last_successful_collection": None,
            "last_collection_duration_seconds": None,
            "consecutive_failures": 0,
            "recent_errors": deque(maxlen=self._recent_error_limit),
        })
        state["last_collection_duration_seconds"] = duration
        if errors:
            state["consecutive_failures"] += 1
            for error in errors:
                state["recent_errors"].append({
                    "timestamp": timestamp,
                    "error": error,
                })
        else:
            state["last_successful_collection"] = timestamp
            state["consecutive_failures"] = 0
        return result

    def report(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collectors": {
                name: {
                    **state,
                    "recent_errors": list(state["recent_errors"]),
                }
                for name, state in self._collectors.items()
            },
        }
