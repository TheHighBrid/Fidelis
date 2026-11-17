"""Thread-safe, ownership-scoped cancellation requests for local jobs.

A cancellation request does not mean a worker has stopped. Workers must
cooperatively check the token and persist terminal state separately.
This in-memory primitive is not the durable F07 job ledger.
"""
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class CancellationReceipt:
    job_id: str
    requested: bool
    already_requested: bool


class CancellationRegistry:
    def __init__(self):
        self._lock = Lock()
        self._owners = {}
        self._cancelled = set()

    def register(self, job_id: str, owner_id: str) -> None:
        if not job_id or not owner_id:
            raise ValueError("job_id and owner_id are required")
        with self._lock:
            if job_id in self._owners:
                raise ValueError("job already registered")
            self._owners[job_id] = owner_id

    def request(self, job_id: str, owner_id: str) -> CancellationReceipt:
        with self._lock:
            if not owner_id or self._owners.get(job_id) != owner_id:
                raise PermissionError("job not found or not owned by requester")
            already = job_id in self._cancelled
            self._cancelled.add(job_id)
            return CancellationReceipt(job_id, True, already)

    def is_requested(self, job_id: str, owner_id: str) -> bool:
        with self._lock:
            if not owner_id or self._owners.get(job_id) != owner_id:
                raise PermissionError("job not found or not owned by requester")
            return job_id in self._cancelled

    def unregister(self, job_id: str, owner_id: str) -> None:
        with self._lock:
            if not owner_id or self._owners.get(job_id) != owner_id:
                raise PermissionError("job not found or not owned by requester")
            del self._owners[job_id]
            self._cancelled.discard(job_id)
