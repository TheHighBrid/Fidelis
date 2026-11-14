"""Single-owner durable local generation queue; no global GPU interruption."""
from contextlib import contextmanager
import copy
import fcntl
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

import numpy as np

from fidelis.studio.comfy import ComfyTextureBackend, GenerationCancelled, SubmissionUnknown
from fidelis.studio.store import BudgetExceeded, RevisionConflict


class QueueFull(BudgetExceeded):
    pass


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
        if type(capacity) is not int or not 1 <= capacity <= 16 or type(max_records) is not int or not capacity <= max_records <= 1000:
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
        try:
            self.backend = backend or ComfyTextureBackend(self.root / 'runs', address, timeout=2)
        except BaseException:
            self._owner.close()
            raise
        try:
            with self._db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, record TEXT NOT NULL)')
                for task in self._all(db):
                    if task['status'] in ('running', 'applying'):
                        task.update(status='interrupted', message='Worker restarted; explicitly resume to reconcile the existing run')
                        self._save(db, task)
            self.worker = threading.Thread(target=self._work, name='fidelis-generation', daemon=True)
            self.worker.start()
            self.wake.set()
        except BaseException:
            self.backend.close()
            self._owner.close()
            raise

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.root / 'queue.sqlite3', timeout=2)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _all(db):
        return [json.loads(row[0]) for row in db.execute('SELECT record FROM tasks ORDER BY rowid')]

    @staticmethod
    def _save(db, task):
        task['updated_at_unix'] = time.time()
        db.execute('UPDATE tasks SET record=? WHERE id=?', (json.dumps(task, allow_nan=False), task['id']))

    def _owned(self, db, job_id, task_id):
        row = db.execute('SELECT record FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row or json.loads(row[0])['job_id'] != job_id:
            raise KeyError('Generation task not found for this job')
        return json.loads(row[0])

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
            return self._public(task)

    def resume(self, job_id, task_id):
        with self.lock, self._db() as db:
            task = self._owned(db, job_id, task_id)
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
        with self.lock, self._db() as db:
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
            texture, record = self.backend.run(source, task['bundle'], run_id=task['run_id'],
                         deadline_seconds=self.deadline_seconds, cancelled=lambda: self._cancelled(task))
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
            record = self.backend._get(task['run_id'])
            unresolved = record is not None and record['status'] in ('submitting', 'submission_unknown', 'submitted')
            self._finish(task, 'needs_review' if unresolved else 'failed',
                         remote_may_continue=unresolved, error=type(error).__name__, message=str(error))

    def _work(self):
        while not self.stopping.is_set():
            task = None
            with self.lock, self._db() as db:
                for item in self._all(db):
                    if item['status'] == 'queued':
                        task = item
                        task.update(status='running')
                        self._save(db, task)
                        break
                self.wake.clear()
            if task:
                self._execute(task)
            else:
                self.wake.wait(.25)

    def close(self):
        self.stopping.set()
        self.wake.set()
        self.worker.join()  # HTTP calls and polling are bounded; never release ownership while active.
        self.backend.close()
        self._owner.close()
