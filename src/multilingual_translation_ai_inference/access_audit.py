"""Optional bounded access metadata; never serialize request content or identities."""
import json

from .auth_guard import RequestRateGuard


def _route_label(path: str) -> str:
    if len(path) > 200:
        return "/v1/unmatched"
    if path in ("/v1/models", "/v1/jobs/translations", "/v1/jobs/benchmarks"):
        return path
    parts = path.split("/")
    if parts[1:3] == ["v1", "jobs"]:
        if len(parts) == 4:
            return "/v1/jobs/{job_id}"
        if len(parts) == 7 and parts[4] == "runs" and parts[6] == "retry":
            return "/v1/jobs/{job_id}/runs/{run_id}/retry"
    return "/v1/unmatched"


class AccessRecorder:
    def __init__(self, max_events_per_minute: int):
        self._budget = RequestRateGuard(per_peer=max_events_per_minute,
                                        per_process=max_events_per_minute, max_clients=1)

    def emit(self, *, method: str, path: str, status_code: int, authenticated: bool,
             duration_ms: float) -> None:
        if self._budget.admit("access-events") is not None:
            return
        record = json.dumps({
            "event": "api_access",
            "method": method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER",
            "route": _route_label(path), "status_code": status_code,
            "authenticated": authenticated, "duration_ms": round(max(0, duration_ms), 3),
        })
        try:
            print(record, flush=True)
        except OSError:
            # Best-effort metadata must not change a successful job response.
            pass
