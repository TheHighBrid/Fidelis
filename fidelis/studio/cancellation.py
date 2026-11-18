"""Thread-safe, ownership-scoped cancellation requests for local jobs.

A cancellation request does not mean a worker has stopped. Workers must
cooperatively check the token and persist terminal state separately.
This in-memory primitive is not the durable F07 job ledger.
"""
from dataclasses import dataclass
from threading import Event, Lock
from uuid import uuid4


@dataclass(frozen=True)
class CancellationReceipt:
    job_id: str
    requested: bool
    already_requested: bool


class CancellationRequested(Exception):
    """Raised at a cooperative checkpoint when cancellation was requested."""


@dataclass(frozen=True)
class CancellationHandle:
    """Worker registration identity, preventing stale workers from acting on reused IDs."""
    registry: "CancellationRegistry"
    job_id: str
    owner_id: str
    registration_id: str

    def checkpoint(self) -> None:
        self.registry.checkpoint(self.job_id, self.owner_id, registration_id=self.registration_id)

    def is_requested(self) -> bool:
        return self.registry.is_requested(self.job_id, self.owner_id, registration_id=self.registration_id)

    def request(self) -> CancellationReceipt:
        return self.registry.request(self.job_id, self.owner_id, registration_id=self.registration_id)

    def wait_requested(self, timeout: float | None = None) -> bool:
        """Wait for this registration's cancellation without busy polling.

        A stale registration raises PermissionError even if its old event fired.
        False means only that the timeout expired, not that work completed.
        """
        return self.registry.wait_requested(
            self.job_id, self.owner_id, registration_id=self.registration_id,
            timeout=timeout,
        )

    def unregister(self) -> None:
        self.registry.unregister(self.job_id, self.owner_id, registration_id=self.registration_id)


class CancellationRegistry:
    def __init__(self):
        self._lock = Lock()
        self._owners = {}
        self._cancelled = set()
        self._events = {}

    def register(self, job_id: str, owner_id: str) -> CancellationHandle:
        if not job_id or not owner_id:
            raise ValueError("job_id and owner_id are required")
        with self._lock:
            if job_id in self._owners:
                raise ValueError("job already registered")
            registration_id = uuid4().hex
            self._owners[job_id] = (owner_id, registration_id)
            self._events[job_id] = Event()
            return CancellationHandle(self, job_id, owner_id, registration_id)

    def _require_owned(self, job_id, owner_id, registration_id=None):
        record = self._owners.get(job_id)
        if not owner_id or record is None or record[0] != owner_id or (registration_id is not None and record[1] != registration_id):
            raise PermissionError("job not found or not owned by requester")

    def request(self, job_id: str, owner_id: str, *, registration_id=None) -> CancellationReceipt:
        with self._lock:
            self._require_owned(job_id, owner_id, registration_id)
            already = job_id in self._cancelled
            self._cancelled.add(job_id)
            self._events[job_id].set()
            return CancellationReceipt(job_id, True, already)

    def is_requested(self, job_id: str, owner_id: str, *, registration_id=None) -> bool:
        with self._lock:
            self._require_owned(job_id, owner_id, registration_id)
            return job_id in self._cancelled

    def wait_requested(self, job_id: str, owner_id: str, *, registration_id=None,
                       timeout: float | None = None) -> bool:
        """Bounded wait with identity recheck after waking or timing out."""
        if timeout is not None and (not isinstance(timeout, (int, float))
                                    or isinstance(timeout, bool)
                                    or not 0 <= timeout < float('inf')):
            raise ValueError("timeout must be finite and nonnegative")
        with self._lock:
            self._require_owned(job_id, owner_id, registration_id)
            event = self._events[job_id]
            identity = self._owners[job_id][1]
        requested = event.wait(timeout)
        with self._lock:
            self._require_owned(job_id, owner_id, identity)
            return requested and job_id in self._cancelled

    def checkpoint(self, job_id: str, owner_id: str, *, registration_id=None) -> None:
        """Abort cooperative work only when its owner requested cancellation.

        Call between bounded worker steps; this cannot interrupt an active
        external inference call and does not persist terminal job state.
        """
        if self.is_requested(job_id, owner_id, registration_id=registration_id):
            raise CancellationRequested(job_id)

    def unregister(self, job_id: str, owner_id: str, *, registration_id=None) -> None:
        with self._lock:
            self._require_owned(job_id, owner_id, registration_id)
            del self._owners[job_id]
            self._cancelled.discard(job_id)
            self._events.pop(job_id).set()
