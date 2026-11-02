"""Bounded, thread-safe defense against repeated guesses of the API Bearer token.

The state is process-local, intentionally costs no database/Redis reads and never
allocates GPUs. For a strict limit across Modal replicas, add an atomic shared
limiter at the trusted edge or in an external store.
"""

import ipaddress
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from starlette.requests import Request


@dataclass
class _ClientState:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


def client_identity(request: Request) -> str:
    """Use the ASGI peer, never an untrusted forwarding-header value.

    A trusted ASGI proxy may already rewrite scope["client"]. Do not parse
    X-Forwarded-For here, since arbitrary client headers can be spoofed.
    """
    peer = request.scope.get("client")
    host = peer[0] if peer and isinstance(peer[0], str) else ""
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        # Missing/unverifiable peer addresses share a conservative bucket.
        return "unidentified-peer"


class AuthenticationFailureGuard:
    """Three-strike sliding-window lockout with bounded memory per process."""

    def __init__(
        self,
        max_failures: int = 3,
        window_seconds: int = 300,
        lockout_seconds: int = 900,
        max_clients: int = 4096,
        *,
        clock=None,
    ) -> None:
        if any(type(value) is not int or value < 1 for value in (
            max_failures, window_seconds, lockout_seconds, max_clients,
        )):
            raise ValueError("Authentication guard limits must be positive integers")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.max_clients = max_clients
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._clients: OrderedDict[str, _ClientState] = OrderedDict()

    def record_failure(self, peer: str) -> int | None:
        """Return Retry-After for the third and subsequent failures."""
        now = self._clock()
        with self._lock:
            entry = self._clients.get(peer)
            if entry is None:
                if len(self._clients) >= self.max_clients:
                    self._clients.popitem(last=False)
                entry = _ClientState()
                self._clients[peer] = entry
            self._clients.move_to_end(peer)

            if entry.blocked_until > now:
                return max(1, math.ceil(entry.blocked_until - now))

            if entry.blocked_until:
                entry.blocked_until = 0.0
                entry.failures.clear()

            while entry.failures and now - entry.failures[0] >= self.window_seconds:
                entry.failures.popleft()
            entry.failures.append(now)
            if len(entry.failures) >= self.max_failures:
                entry.blocked_until = now + self.lockout_seconds
                entry.failures.clear()
                return self.lockout_seconds
            return None

    def clear_after_success(self, peer: str) -> None:
        """Permit known-good clients behind a shared NAT to clear failures."""
        with self._lock:
            self._clients.pop(peer, None)


class RequestRateGuard:
    """Bound secret comparisons/requests before authentication, per process.

    Monotonic fixed-minute windows; this is not a distributed or edge limiter.
    A global budget remains effective even when bounded peer state is evicted.
    """
    def __init__(self, *, per_peer: int, per_process: int, max_clients: int = 4096, clock=None):
        if any(type(value) is not int or value < 1 for value in (per_peer, per_process, max_clients)):
            raise ValueError("Request rate limits must be positive integers")
        self.per_peer = per_peer
        self.per_process = per_process
        self.max_clients = max_clients
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._peers = OrderedDict()
        self._bucket = None
        self._used = 0

    def admit(self, peer: str) -> int | None:
        with self._lock:
            now = self._clock()
            bucket = int(now // 60)
            if bucket != self._bucket:
                self._bucket, self._used = bucket, 0
            retry_after = max(1, math.ceil((bucket + 1) * 60 - now))
            if self._used >= self.per_process:
                return retry_after
            old_bucket, used = self._peers.get(peer, (bucket, 0))
            if old_bucket != bucket:
                used = 0
            if used >= self.per_peer:
                return retry_after
            if peer not in self._peers and len(self._peers) >= self.max_clients:
                self._peers.popitem(last=False)
            self._peers[peer] = (bucket, used + 1)
            self._peers.move_to_end(peer)
            self._used += 1
            return None
