"""Explicit local ComfyUI texture adapter with durable, non-retrying submission.

Workflows are exported API graphs supplied by the local operator, not guessed node
packs. No source from Clarity is imported and no cloud provider is contacted.
"""
import copy
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlparse
import uuid

import httpx
import numpy as np
from PIL import Image

from fidelis.studio.store import sha256


class BackendUnavailable(RuntimeError):
    pass


class SubmissionUnknown(RuntimeError):
    pass


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_workflow(bundle, schema):
    """Preflight installed classes/required inputs/model choices and acyclic links.

    The ComfyUI server remains authoritative for tensor types and node validators.
    This does not certify checkpoint compatibility or image quality.
    """
    if not isinstance(bundle, dict) or bundle.get('schema_version') != 1:
        raise ValueError('Expected workflow bundle schema_version 1')
    if bundle.get('family') not in ('sdxl', 'flux', 'other'):
        raise ValueError('Declare the workflow model family')
    graph = bundle.get('workflow')
    if not isinstance(graph, dict) or not graph or len(graph) > 500:
        raise ValueError('Supply an exported ComfyUI API graph (maximum 500 nodes)')
    input_node, output_node = bundle.get('input_node'), bundle.get('output_node')
    if input_node not in graph or graph[input_node].get('class_type') != 'LoadImage':
        raise ValueError('input_node must identify a LoadImage node')
    if output_node not in graph or graph[output_node].get('class_type') != 'SaveImage':
        raise ValueError('output_node must identify a SaveImage node')
    dependencies = {}
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            raise ValueError('Invalid workflow node')
        class_type, values = node.get('class_type'), node.get('inputs')
        if class_type not in schema:
            raise ValueError(f'Required node class is not installed: {class_type}')
        if not isinstance(values, dict):
            raise ValueError('Node inputs must be an object')
        spec = schema[class_type].get('input', {})
        required = spec.get('required', {})
        if set(required) - set(values):
            raise ValueError(f'Missing required inputs on node {node_id}')
        dependencies[node_id] = []
        for name, value in values.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if value[0] not in graph or value[1] < 0:
                    raise ValueError('Dangling workflow link')
                dependencies[node_id].append(value[0])
            else:
                field = required.get(name, spec.get('optional', {}).get(name))
                # LoadImage choices change after upload, so its image path is injected later.
                if field and isinstance(field[0], list) and value not in field[0] and not (node_id == input_node and name == 'image'):
                    raise ValueError(f'Installed model/choice unavailable for {node_id}.{name}')
    active, complete = set(), set()
    def visit(node_id):
        if node_id in active:
            raise ValueError('Workflow contains a cycle')
        if node_id in complete:
            return
        active.add(node_id)
        for dependency in dependencies[node_id]:
            visit(dependency)
        active.remove(node_id)
        complete.add(node_id)
    for node_id in graph:
        visit(node_id)
    ancestors = set()
    def ancestors_of(node_id):
        if node_id in ancestors:
            return
        ancestors.add(node_id)
        for dependency in dependencies[node_id]:
            ancestors_of(dependency)
    ancestors_of(output_node)
    if input_node not in ancestors:
        raise ValueError('Output must depend on the supplied base image')
    return copy.deepcopy(graph)


class ComfyTextureBackend:
    def __init__(self, root, address='http://127.0.0.1:8188', *, timeout=5, poll_interval=.5):
        parsed = urlparse(address)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.path not in ('', '/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use a loopback ComfyUI HTTP address or an explicit SSH tunnel')
        if not 0 < timeout <= 60 or not 0 <= poll_interval <= 10:
            raise ValueError('Invalid backend time limits')
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.address = address.rstrip('/')
        self.timeout, self.poll_interval = timeout, poll_interval
        self.client = httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def close(self):
        self.client.close()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.root / 'generation.sqlite3', timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _get(self, run_id):
        with self._db() as db:
            row = db.execute('SELECT record FROM runs WHERE id=?', (run_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def _save(self, record):
        with self._db() as db:
            db.execute('UPDATE runs SET record=? WHERE id=?', (json.dumps(record), record['id']))

    def _request(self, method, route, *, max_bytes=16*1024**2, **kwargs):
        with self.client.stream(method, self.address + route, **kwargs) as response:
            response.raise_for_status()
            parts, size = [], 0
            for part in response.iter_bytes():
                size += len(part)
                if size > max_bytes:
                    raise ValueError('ComfyUI response exceeds allowed size')
                parts.append(part)
            return b''.join(parts)

    def _json(self, method, route, **kwargs):
        return json.loads(self._request(method, route, **kwargs))

    def probe(self):
        try:
            stats = self._json('GET', '/system_stats')
            schema = self._json('GET', '/object_info')
            if not isinstance(stats, dict) or not isinstance(schema, dict):
                raise ValueError('Invalid ComfyUI capability response')
            return {'reachable': True, 'node_classes': sorted(schema),
                    'devices': stats.get('devices', []), 'live_inference_verified': False}
        except (httpx.HTTPError, ValueError) as error:
            return {'reachable': False, 'reason': type(error).__name__, 'live_inference_verified': False}

    def run(self, source_rgb, bundle, *, run_id=None, deadline_seconds=300):
        if not isinstance(source_rgb, np.ndarray) or source_rgb.dtype != np.uint8 or source_rgb.ndim != 3 or source_rgb.shape[2] != 3:
            raise ValueError('Texture input must be uint8 RGB')
        if not 0 < source_rgb.shape[0] * source_rgb.shape[1] <= 40_000_000:
            raise ValueError('Texture input exceeds pixel limit')
        if not 0 < deadline_seconds <= 3600:
            raise ValueError('Deadline must be in (0,3600] seconds')
        run_id = str(uuid.UUID(run_id)) if run_id else str(uuid.uuid4())
        identity = canonical_hash({'source_sha256': hashlib.sha256(source_rgb.tobytes()).hexdigest(),
                                   'bundle': bundle, 'dimensions': list(source_rgb.shape), 'address': self.address})
        record = self._get(run_id)
        if record and record['recipe_hash'] != identity:
            raise ValueError('Run ID already belongs to a different recipe or source')
        if record is None:
            try:
                schema = self._json('GET', '/object_info')
            except (httpx.HTTPError, ValueError) as error:
                raise BackendUnavailable('Local ComfyUI is unavailable; no generation was submitted') from error
            graph = validate_workflow(bundle, schema)
            record = {'id': run_id, 'recipe_hash': identity, 'workflow_sha256': canonical_hash(bundle),
                      'status': 'preparing', 'prompt_id': None, 'dimensions': list(source_rgb.shape),
                      'family': bundle['family'], 'bundle': bundle, 'backend': 'local-comfyui',
                      'created_at_unix': time.time(), 'live_quality_verified': False}
            try:
                with self._db() as db:
                    db.execute('INSERT INTO runs VALUES (?,?)', (run_id, json.dumps(record)))
            except sqlite3.IntegrityError as error:
                raise SubmissionUnknown('Another caller reserved this run ID; resume it without resubmitting') from error
            try:
                image = io.BytesIO()
                Image.fromarray(source_rgb).save(image, format='PNG')
                uploaded = self._json('POST', '/upload/image', files={'image': (f'fidelis_{run_id}.png', image.getvalue(), 'image/png')}, data={'overwrite': 'false', 'type': 'input'})
                subfolder = uploaded.get('subfolder', '')
                graph[bundle['input_node']]['inputs']['image'] = (subfolder + '/' if subfolder else '') + uploaded['name']
                record['status'] = 'submitting'
                self._save(record)
                try:
                    queued = self._json('POST', '/prompt', json={'prompt': graph, 'client_id': run_id,
                                            'extra_data': {'fidelis_request_id': run_id}})
                except Exception as error:
                    # A 4xx rejects the request. A timeout/5xx may have queued it.
                    rejected = isinstance(error, httpx.HTTPStatusError) and 400 <= error.response.status_code < 500
                    record['status'] = 'rejected' if rejected else 'submission_unknown'
                    record['error'] = str(error)
                    self._save(record)
                    raise SubmissionUnknown('Submission could not be confirmed; this run will not be automatically resubmitted') from error
                if not isinstance(queued.get('prompt_id'), str) or queued.get('error'):
                    record['status'] = 'submission_unknown'
                    self._save(record)
                    raise SubmissionUnknown('Missing prompt ID; reconcile the existing run before retrying')
                record.update(status='submitted', prompt_id=queued['prompt_id'])
                self._save(record)
            except Exception:
                if record['status'] == 'preparing':
                    record['status'] = 'preparation_failed'
                    self._save(record)
                raise
        if record['status'] in ('submitting', 'submission_unknown'):
            record = self.reconcile(run_id)
        if record['status'] not in ('submitted', 'completed'):
            raise SubmissionUnknown(f"Run is {record['status']}; automatic resubmission is disabled")
        cached = self.root / f'{run_id}.png'
        if record['status'] == 'completed' and cached.is_file() and sha256(cached) == record['output_sha256']:
            with Image.open(cached) as image:
                return np.array(image.convert('RGB')), record
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            item = self._json('GET', '/history/' + record['prompt_id']).get(record['prompt_id'])
            if item:
                status = item.get('status', {})
                if status.get('status_str') == 'error':
                    record.update(status='failed', error='ComfyUI execution failed')
                    self._save(record)
                    raise RuntimeError(record['error'])
                images = item.get('outputs', {}).get(bundle['output_node'], {}).get('images', [])
                if images:
                    try:
                        return self._download(images[0], source_rgb.shape, record)
                    except ValueError as error:
                        record.update(status='failed', error=str(error))
                        self._save(record)
                        raise
                if status.get('completed'):
                    record.update(status='failed', error='Workflow completed without the configured image output')
                    self._save(record)
                    raise RuntimeError(record['error'])
            if self.poll_interval:
                time.sleep(min(self.poll_interval, max(0, deadline-time.monotonic())))
        raise TimeoutError('Generation is pending; resume this run ID to poll without another submission')

    def reconcile(self, run_id):
        record = self._get(run_id)
        if not record:
            raise ValueError('Unknown generation run')
        if record.get('prompt_id'):
            return record
        candidates = []
        queue = self._json('GET', '/queue')
        for row in queue.get('queue_running', []) + queue.get('queue_pending', []):
            if len(row) >= 4 and row[3].get('fidelis_request_id') == run_id:
                candidates.append(row[1])
        for prompt_id, item in self._json('GET', '/history?max_items=1000').items():
            prompt = item.get('prompt', [])
            if len(prompt) >= 4 and prompt[3].get('fidelis_request_id') == run_id:
                candidates.append(prompt_id)
        candidates = set(candidates)
        if len(candidates) != 1:
            raise SubmissionUnknown('Cannot uniquely reconcile this submission; inspect the ComfyUI queue/history. No new run was sent')
        record.update(status='submitted', prompt_id=candidates.pop())
        self._save(record)
        return record

    def _download(self, item, expected_shape, record):
        from urllib.parse import urlencode
        if item.get('type') not in ('output', 'temp') or not isinstance(item.get('filename'), str):
            raise ValueError('Invalid ComfyUI output descriptor')
        encoded = self._request('GET', '/view?' + urlencode({key: item.get(key, '') for key in ('filename', 'subfolder', 'type')}), max_bytes=200*1024**2)
        with Image.open(io.BytesIO(encoded)) as image:
            if image.format != 'PNG' or image.size != (expected_shape[1], expected_shape[0]) or image.mode != 'RGB' or image.info.get('icc_profile') or image.getexif().get(274, 1) != 1:
                raise ValueError('Generated pass changed dimensions/encoding/orientation; no implicit resize is allowed')
            array = np.array(image)
        output = self.root / f"{record['id']}.png"
        pending = output.with_suffix(f'.{uuid.uuid4().hex}.pending')
        Image.fromarray(array).save(pending, format='PNG')
        pending.replace(output)
        record.update(status='completed', output_sha256=sha256(output), inference_executed=True)
        self._save(record)
        return array, record
