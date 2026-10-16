from datetime import datetime, timezone
import time
from typing import Any

import psutil


_previous_sample: tuple[float, int, int] | None = None


def network_usage() -> dict[str, Any]:
    global _previous_sample

    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        counters = psutil.net_io_counters()
        sent = counters.bytes_sent
        received = counters.bytes_recv
        now = time.monotonic()

        sent_rate: float | None = None
        received_rate: float | None = None
        if _previous_sample is not None:
            previous_time, previous_sent, previous_received = _previous_sample
            elapsed = now - previous_time
            if elapsed > 0:
                sent_rate = (
                    0.0 if sent < previous_sent
                    else (sent - previous_sent) / elapsed
                )
                received_rate = (
                    0.0 if received < previous_received
                    else (received - previous_received) / elapsed
                )

        _previous_sample = (now, sent, received)
        return {
            "timestamp": timestamp,
            "bytes_sent": sent,
            "bytes_received": received,
            "bytes_sent_per_second": sent_rate,
            "bytes_received_per_second": received_rate,
            "collection_error": None,
        }
    except Exception as exc:
        return {
            "timestamp": timestamp,
            "bytes_sent": None,
            "bytes_received": None,
            "bytes_sent_per_second": None,
            "bytes_received_per_second": None,
            "collection_error": str(exc),
        }
