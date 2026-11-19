"""Single-owner durable local generation queue; no global GPU interruption."""
import copy
import fcntl
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from fidelis.studio.comfy import (
    ComfyTextureBackend,
    GenerationCancelled,
    SubmissionUnknown,
)
from fidelis.studio.store import BudgetExceeded, RevisionConflict
from fidelis.studio.cancellation import CancellationRegistry


class QueueFull(BudgetExceeded):
    pass


class QueueStorageError(RuntimeError):
    """The on-disk queue database is partial or unreadable.

    Callers must leave the file in place. A readable database with a damaged
    task row is quarantined separately and is not executed.
    """


QUARANTINE_MESSAGE = 'Corrupt queue record was quarantined and was not executed'
RESTART_MESSAGE = 'Worker restarted; explicitly resume to reconcile the existing run'
ABANDON_MESSAGE = 'Worker fault before a terminal queue update; explicitly resume to reconcile the existing run'

_STATUSES = frozenset({
    'queued', 'running', 'applying', 'completed', 'waiting',
    'needs_review', 'interrupted', 'failed', 'cancelled',
})
_SQLITE_HEADER = b'SQLite format 3\x00'


class CancellationSignals:
    """Read and signal one worker token.

    A retired registration raises PermissionError or RuntimeError. The queue
    keeps the SQLite record authoritative in that case. Implementations must
    not re-enter the queue.
    """

    def requested(self, handle) -> bool:
        return bool(handle.is_requested())

    def request(self, handle):
        return handle.request()


class _Settlements:
    """Count of finished claims, waitable without a polling sleep."""

    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0
        self._event = threading.Event()

    def pulse(self):
        with self._lock:
            self._count += 1
            self._event.set()

    @property
    def count(self):
        with self._lock:
            return self._count

    def wait_until(self, count, timeout):
        if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout < 0):
            raise ValueError('timeout must be nonnegative')
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if self._count >= count:
                    return True
                self._event.clear()
            if deadline is None:
                self._event.wait()
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._event.wait(remaining)


class GenerationQueue:
    """One worker per queue directory; interrupted tasks require explicit resume.

    Cancellation is local abandonment, not proof of remote GPU cancellation.
    All generation uses one trusted startup-configured graph/address. Browser
    requests cannot supply model graphs, filesystem destinations or remote URLs.
    """
    ACTIVE = ('queued', 'running', 'applying')
    RESUMABLE = ('interrupted', 'waiting', 'needs_review')

    def __init__(self, root, store, bundle, *, address='http://127.0.0.1:8188',
                 capacity=4, max_records=64, deadline_seconds=300, backend=None):
        if (
            (not isinstance(capacity, int) or isinstance(capacity, bool))
            or not 1 <= capacity <= 16
            or (not isinstance(max_records, int) or isinstance(max_records, bool))
            or not capacity <= max_records <= 1000
        ):
            raise ValueError('Invalid queue bounds')
        if not 0 < deadline_seconds <= 3600:
            raise ValueError('Invalid polling deadline')
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._owner = (self.root / 'worker.lock').open('a')
        try:
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._owner.close()
            raise RuntimeError('A generation worker already owns this directory')
        self.store, self.bundle = store, copy.deepcopy(bundle)
        self.capacity, self.max_records, self.deadline_seconds = capacity, max_records, deadline_seconds
        self.lock = threading.RLock()
        self.wake, self.stopping = threading.Event(), threading.Event()
        self.cancellations = CancellationRegistry()
        self.signals = CancellationSignals()
        self._settled = _Settlements()
        self._active_handles = {}
        self._inflight = None
        self.worker = None
        try:
            self.backend = backend or ComfyTextureBackend(self.root / 'runs', address, timeout=2)
        except BaseException:
            self._owner.close()
            raise
        try:
            self._reject_partial_database(self.root / 'queue.sqlite3')
            with self._db() as db:
                self._recover_inflight(db)
            self._start_worker()
        except BaseException:
            if self.worker is not None and self.worker.is_alive():
                self.stopping.set()
                self.wake.set()
                self.worker.join(timeout=2)
            self.cancellations.close()
            self.backend.close()
            self._owner.close()
            raise

    def _reject_partial_database(self, path):
        """Refuse an empty, truncated, or malformed database without rewriting it."""
        if not path.exists():
            return
        if not path.is_file():
            raise QueueStorageError('Queue database path is not a file')
        before = path.stat().st_size
        if before == 0:
            raise QueueStorageError('Partial queue database: queue.sqlite3 is empty')
        with path.open('rb') as handle:
            header = handle.read(len(_SQLITE_HEADER))
        if header != _SQLITE_HEADER:
            raise QueueStorageError('Partial or corrupt queue database: invalid SQLite header')
        uri = path.resolve().as_uri() + '?mode=ro'
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=2)
            try:
                row = connection.execute('PRAGMA integrity_check').fetchone()
            finally:
                connection.close()
        except sqlite3.DatabaseError as error:
            raise QueueStorageError(f'Partial or corrupt queue database: {error}') from error
        if not row or row[0] != 'ok':
            detail = row[0] if row else None
            raise QueueStorageError(f'Queue database failed integrity check: {detail}')

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.root / 'queue.sqlite3', timeout=2, isolation_level=None)
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

    def _ensure_table(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _structurally_valid(self, task, row_id):
        if not isinstance(task, dict) or task.get('id') != row_id:
            return False
        if not isinstance(task.get('job_id'), str) or not task['job_id']:
            return False
        if not isinstance(task.get('run_id'), str) or not task['run_id']:
            return False
        if task.get('status') not in _STATUSES:
            return False
        if type(task.get('expected_revision')) is not int:
            return False
        if not isinstance(task.get('bundle'), dict):
            return False
        if not isinstance(task.get('backend_address'), str) or not task['backend_address']:
            return False
        for name in ('cancel_requested', 'remote_may_continue', 'live_quality_verified'):
            if not isinstance(task.get(name), bool):
                return False
        if 'quarantined' in task and not isinstance(task.get('quarantined'), bool):
            return False
        return True

    def _quarantine_record(self, row_id, raw, parsed):
        parsed = parsed if isinstance(parsed, dict) else {}

        def text(key, fallback):
            value = parsed.get(key)
            return value if isinstance(value, str) and value else fallback

        revision = parsed.get('expected_revision')
        bundle = parsed.get('bundle')
        address = parsed.get('backend_address')
        payload = raw.encode('utf-8') if isinstance(raw, str) else bytes(raw)
        return {
            'id': row_id,
            'run_id': text('run_id', 'unknown'),
            'job_id': text('job_id', 'unknown'),
            'expected_revision': revision if type(revision) is int else 0,
            'status': 'needs_review',
            'bundle': bundle if isinstance(bundle, dict) else {},
            'backend_address': address if isinstance(address, str) and address else 'unrecorded',
            'cancel_requested': False,
            'remote_may_continue': True,
            'live_quality_verified': False,
            'quarantined': True,
            'error': 'CorruptRecord',
            'message': QUARANTINE_MESSAGE,
            'invalid_record_sha256': hashlib.sha256(payload).hexdigest(),
            'invalid_record_bytes': len(payload),
            'created_at_unix': time.time(),
        }

    def _parse_record(self, db, row_id, raw):
        parsed = None
        if isinstance(raw, str):
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                loaded = None
            else:
                if isinstance(loaded, dict):
                    parsed = loaded
        if parsed is not None and self._structurally_valid(parsed, row_id):
            return parsed
        repaired = self._quarantine_record(row_id, raw, parsed)
        self._save(db, repaired)
        return repaired

    def _all(self, db):
        self._ensure_table(db)
        rows = list(db.execute('SELECT id, record FROM tasks ORDER BY rowid'))
        return [self._parse_record(db, row_id, raw) for row_id, raw in rows]

    def _save(self, db, task):
        task['updated_at_unix'] = time.time()
        db.execute(
            'UPDATE tasks SET record=? WHERE id=?',
            (json.dumps(task, allow_nan=False), task['id']),
        )

    def _recover_inflight(self, db):
        """Mark crashed in-flight work interrupted and quarantine damaged rows."""
        for task in self._all(db):
            if task['status'] in ('running', 'applying'):
                task.update(status='interrupted', message=RESTART_MESSAGE)
                self._save(db, task)

    def _owned(self, db, job_id, task_id):
        row = db.execute('SELECT record FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise KeyError('Generation task not found for this job')
        task = self._parse_record(db, task_id, row[0])
        if task['job_id'] != job_id:
            raise KeyError('Generation task not found for this job')
        return task

    def list(self, job_id):
        with self.lock, self._db() as db:
            return [self._public(task) for task in self._all(db) if task['job_id'] == job_id]

    def get(self, job_id, task_id):
        with self.lock, self._db() as db:
            return self._public(self._owned(db, job_id, task_id))

    def enqueue(self, job_id, expected_revision):
        if type(expected_revision) is not int:
            raise ValueError('expected_revision must be an integer')
        job = self.store.get(job_id)
        if job['revision'] != expected_revision:
            raise RevisionConflict('Job revision changed; reload before generation')
        if job['profile'] == 'packshot_strict':
            raise ValueError('Packshot Strict never invokes generation')
        with self.lock, self._db() as db:
            if self.stopping.is_set():
                raise RuntimeError('Generation worker is stopping')
            tasks = self._all(db)
            if any(task['job_id'] == job_id and task['status'] in self.ACTIVE + self.RESUMABLE for task in tasks):
                raise RevisionConflict('An unresolved task already owns this job; inspect or cancel it')
            if len(tasks) >= self.max_records or sum(task['status'] in self.ACTIVE for task in tasks) >= self.capacity:
                raise QueueFull('Generation queue/record limit reached')
            task = {'id': str(uuid.uuid4()), 'run_id': str(uuid.uuid4()), 'job_id': job_id,
                    'expected_revision': expected_revision, 'status': 'queued',
                    'bundle': self.bundle, 'backend_address': self.backend.address,
                    'created_at_unix': time.time(), 'cancel_requested': False,
                    'remote_may_continue': False, 'live_quality_verified': False}
            db.execute('INSERT INTO tasks VALUES (?,?)', (task['id'], json.dumps(task)))
        self.wake.set()
        return self._public(task)

    @staticmethod
    def _public(task):
        return {key: value for key, value in task.items() if key not in ('bundle', 'backend_address')}

    def cancel(self, job_id, task_id):
        with self.lock, self._db() as db:
            task = self._owned(db, job_id, task_id)
            if task['status'] == 'applying':
                raise RevisionConflict('Result commit has started; reload the job after it finishes')
            if task['status'] in self.ACTIVE + self.RESUMABLE:
                task.update(cancel_requested=True, status='cancelled',
                            remote_may_continue=task.get('remote_may_continue', False) or task['status'] != 'queued',
                            message='Local task cancelled; submitted GPU work may continue. No global interrupt was sent.')
                self._save(db, task)
                handle = self._active_handles.get(task_id)
                if handle is not None:
                    # SQLite is authoritative: a stale in-memory token must not
                    # make an already-persisted cancellation appear to fail.
                    # The worker also reads the durable flag at checkpoints.
                    try:
                        self.signals.request(handle)
                    except (PermissionError, RuntimeError):
                        pass
            return self._public(task)

    def resume(self, job_id, task_id):
        with self.lock, self._db() as db:
            # A stopped worker cannot claim a resumed task. Reject the request
            # without changing durable state or implying that work was queued.
            if self.stopping.is_set():
                raise RuntimeError('Generation worker is stopping')
            task = self._owned(db, job_id, task_id)
            if task.get('quarantined'):
                raise RevisionConflict('Corrupt queue record cannot be resumed')
            if task['status'] not in self.RESUMABLE:
                raise RevisionConflict('Only interrupted, waiting or unresolved tasks can be resumed')
            if sum(item['status'] in self.ACTIVE for item in self._all(db)) >= self.capacity:
                raise QueueFull('Generation queue is full')
            if task['backend_address'] != self.backend.address:
                raise RevisionConflict('Resume requires the original backend address')
            task.update(status='queued', message='Explicit resume of existing run; no automatic resubmission')
            self._save(db, task)
        self.wake.set()
        return self._public(task)

    def _cancelled(self, task):
        if self.stopping.is_set():
            return True
        with self.lock:
            handle = self._active_handles.get(task['id'])
            if handle is not None:
                try:
                    if self.signals.requested(handle):
                        return True
                except (PermissionError, RuntimeError):
                    # Registry retirement invalidates old handles. Durable SQLite
                    # cancellation remains authoritative even when the token
                    # cannot be inspected during worker cleanup or recovery.
                    pass
            with self._db() as db:
                return self._owned(db, task['job_id'], task['id'])['cancel_requested']

    def _finish(self, task, status, **fields):
        with self.lock, self._db() as db:
            current = self._owned(db, task['job_id'], task['id'])
            if current['status'] == 'cancelled':
                return
            current.update(status=status, **fields)
            self._save(db, current)

    def _execute(self, task):
        try:
            if task['backend_address'] != self.backend.address:
                raise ValueError('Queued task requires its original backend address')
            with self.store.open_array(task['job_id'], 'base', expected_revision=task['expected_revision']) as base:
                source = np.array(base)
            # Cancellation may arrive during the local source read. Do not enter
            # inference or submit a remote run after the durable cancel commit.
            if self._cancelled(task):
                raise GenerationCancelled()
            texture, record = self.backend.run(source, task['bundle'], run_id=task['run_id'],
                         deadline_seconds=self.deadline_seconds, cancelled=lambda: self._cancelled(task))
            # An inference result without a usable receipt cannot be safely
            # committed or attributed to the existing run. Preserve the image
            # revision and require reconciliation rather than trusting it.
            if (not isinstance(record, dict) or not isinstance(record.get('prompt_id'), str)
                    or not record['prompt_id'].strip()
                    or ('id' in record and record['id'] != task['run_id'])
                    or ('status' in record and record['status'] != 'completed')):
                self._finish(task, 'needs_review', remote_may_continue=True,
                             message='Backend returned an invalid generation receipt; reconcile before resume')
                return
            # The apply decision and cancellation are serialized. Once applying,
            # the atomic JobStore commit owns the result and cancellation conflicts.
            with self.lock, self._db() as db:
                current = self._owned(db, task['job_id'], task['id'])
                if current['cancel_requested'] or self.stopping.is_set():
                    if current['status'] != 'cancelled':
                        current.update(status='interrupted', remote_may_continue=True)
                        self._save(db, current)
                    return
                current.update(status='applying', prompt_id=record.get('prompt_id'))
                self._save(db, current)
            updated = self.store.replace_texture(task['job_id'], texture,
                         expected_revision=task['expected_revision'], candidate_recipe=record)
            self._finish(task, 'completed', result_revision=updated['revision'], remote_may_continue=False)
        except GenerationCancelled:
            self._finish(task, 'interrupted', remote_may_continue=True,
                         message='Worker stopped; resume the existing run explicitly')
        except TimeoutError:
            self._finish(task, 'waiting', remote_may_continue=True, message='Polling deadline reached; explicitly resume this run')
        except SubmissionUnknown:
            self._finish(task, 'needs_review', remote_may_continue=True, message='Submission unresolved; resume reconciles without resubmission')
        except Exception as error:
            # A failed backend may also have an unreadable run ledger. Do not
            # crash the queue worker or guess that remote submission was absent.
            try:
                record = self.backend._get(task['run_id'])
            except Exception:
                self._finish(task, 'needs_review', remote_may_continue=True,
                             error=type(error).__name__,
                             message='Backend failed and run state could not be read; reconcile before resume')
                return
            # A damaged or incompatible ledger record cannot establish that a
            # remote submission was absent. Preserve the run for reconciliation.
            if record is not None and (
                not isinstance(record, dict) or not isinstance(record.get('status'), str)
            ):
                self._finish(task, 'needs_review', remote_may_continue=True,
                             error=type(error).__name__,
                             message='Backend run state is invalid; reconcile before resume')
                return
            # Only explicitly recognized terminal/pre-submission states can
            # establish that remote execution is not ongoing. New backend
            # statuses must fail closed instead of silently becoming "failed".
            safe_states = ('preparing', 'preparation_failed', 'rejected', 'failed', 'completed')
            # A missing run row is not proof that submission never happened:
            # the ledger may have been deleted after ComfyUI accepted a prompt.
            # Only a persisted, recognized terminal state permits failure.
            unresolved = record is None or record['status'] not in safe_states
            self._finish(task, 'needs_review' if unresolved else 'failed',
                         remote_may_continue=unresolved, error=type(error).__name__,
                         message=('Unrecognized or active backend run state; reconcile before resume'
                                  if unresolved else str(error)))

    def _retire_registry(self):
        self.cancellations.close()
        self.cancellations = CancellationRegistry()

    def _claim_next(self, db):
        """Claim at most one queued task. A second call is refused while it runs."""
        if self.stopping.is_set() or self._inflight is not None:
            return None
        for item in self._all(db):
            if item.get('status') != 'queued' or item.get('quarantined'):
                continue
            try:
                handle = self.cancellations.register(item['id'], item['job_id'])
            except Exception:
                # A registration implementation can fail after creating its
                # owner/event. Retire that registry before the next claim so no
                # stale token survives a partial failure.
                self._retire_registry()
                item.update(status='needs_review', remote_may_continue=False,
                            message='Local cancellation registration failed; inspect before resume')
                self._save(db, item)
                continue
            item.update(status='running')
            try:
                self._save(db, item)
            except Exception:
                try:
                    handle.unregister()
                except Exception:
                    self._retire_registry()
                raise
            self._active_handles[item['id']] = handle
            self._inflight = item['id']
            return item
        return None

    def _rollback_inflight_memory(self):
        with self.lock:
            inflight = self._inflight
            self._inflight = None
            handle = self._active_handles.pop(inflight, None) if inflight is not None else None
            if handle is None:
                return
            try:
                handle.unregister()
            except Exception:
                self._retire_registry()

    def _release_claim(self, task):
        with self.lock:
            if self._inflight == task['id']:
                self._inflight = None
            handle = self._active_handles.pop(task['id'], None)
            if handle is not None:
                try:
                    handle.unregister()
                except Exception:
                    # The queue has exactly one execution worker. If unregister
                    # fails, retire the entire in-memory registry rather than
                    # leave a stale owner/token that could block a future claim
                    # or be signalled for a different task.
                    self._retire_registry()
        self._settled.pulse()

    def _abandon(self, task, error):
        with self.lock, self._db() as db:
            current = self._owned(db, task['job_id'], task['id'])
            if current['status'] not in ('running', 'applying'):
                return
            current.update(status='interrupted', remote_may_continue=True,
                           error=type(error).__name__, message=ABANDON_MESSAGE)
            self._save(db, current)

    def _run_claimed(self, task):
        try:
            try:
                self._execute(task)
            except Exception as error:
                try:
                    self._abandon(task, error)
                except Exception:
                    pass
        finally:
            self._release_claim(task)

    def _work(self):
        fault = False
        while not self.stopping.is_set():
            task = None
            try:
                with self.lock, self._db() as db:
                    if self.stopping.is_set():
                        break
                    task = self._claim_next(db)
                    if task is None:
                        self.wake.clear()
                fault = False
            except Exception:
                self._rollback_inflight_memory()
                if fault and not self.stopping.is_set():
                    # A repeated claim fault waits for the next queue event
                    # instead of spinning. The short bound also covers a wake
                    # that was cleared while the producer was between insert
                    # and set. Healthy claims do not use this path.
                    with self.lock:
                        self.wake.clear()
                    self.wake.wait(0.25)
                    fault = False
                    continue
                fault = True
                continue
            if task is not None:
                self._run_claimed(task)
            elif not self.stopping.is_set():
                self.wake.wait()

    def _start_worker(self):
        if self.worker is not None and self.worker.is_alive():
            raise RuntimeError('A generation worker is already running')
        self.worker = threading.Thread(target=self._work, name='fidelis-generation', daemon=True)
        self.worker.start()
        self.wake.set()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.worker is not None:
            self.worker.join()  # HTTP calls and polling are bounded; never release ownership while active.
        self.cancellations.close()
        self.backend.close()
        self._owner.close()
