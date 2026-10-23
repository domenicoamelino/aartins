#!/usr/bin/env python3
"""Meeting ingestion for Open WebUI 0.12.3. Python 3.10+, standard library only."""
import argparse
from contextlib import closing, contextmanager
import datetime as dt
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

VERSION = '1.0.1'
DEFAULT_HOME = Path.home() / 'ai-platform/ingestion'
MAX_FILE_BYTES = 8 * 1024 * 1024


class IngestionError(Exception):
    pass


class APIError(IngestionError):
    def __init__(self, status, route):
        self.status = status
        super().__init__(f'Open WebUI returned HTTP {status} for {route}. '
                         'Check API permissions, server logs and the README; response bodies are not logged.')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def emit(message):
    print(now(), message, flush=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + secrets.token_hex(6))
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_json(path, obj):
    atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


@contextmanager
def locked(path):
    """OS lock releases automatically on process exit; file can remain on disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    handle = os.fdopen(fd, 'r+b')
    try:
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise IngestionError('Another ingestion operation is running') from None
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise IngestionError('Another ingestion operation is running') from None
        yield
    finally:
        handle.close()


def normalized_bytes(raw):
    return raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def slug(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:60] or 'meeting'


def document(folder, root, include_legacy=False, approved_revision=None):
    folder, root = Path(folder), Path(root).resolve()
    if folder.is_symlink() or folder.resolve().parent != root:
        raise IngestionError('Meeting folder must be a direct, non-symlink child of archive root')
    for name in ('knowledge.md', 'job.json', 'meeting_metadata.json'):
        if (folder / name).is_symlink():
            raise IngestionError(f'Symlink source refused: {folder.name}/{name}')
    job_path = folder / 'job.json'
    if job_path.exists():
        if read_json(job_path).get('state') != 'completed':
            return None
    elif not include_legacy:
        return None
    # Approval is mandatory, including legacy archives. include_legacy never bypasses review.
    state_path = folder/'review.json'
    if not state_path.is_file():
        return None
    if state_path.is_symlink():
        raise IngestionError('Symlink review state refused')
    review_state = read_json(state_path)
    if review_state.get('schema') != 'meeting-review/1':
        raise IngestionError('Invalid review state schema')
    approval = review_state.get('last_approved')
    if approved_revision is not None:
        if type(approved_revision) is not int or approved_revision < 1:
            raise IngestionError('Invalid pending approval revision')
        approval_path = folder/'review'/f'r{approved_revision:06d}'/'approval.json'
        if not approval_path.is_file() or approval_path.is_symlink():
            raise IngestionError('Pending work does not have an approved immutable revision')
        approval = read_json(approval_path)
    if not approval:
        return None
    revision = approval.get('revision')
    if type(revision) is not int or revision < 1 or approval.get('owner') != review_state.get('owner'):
        raise IngestionError('Invalid approval identity')
    directory = folder/'review'/f'r{revision:06d}'
    path = directory/'knowledge.md'
    metadata_path = directory/'meeting_metadata.json'
    approval_path = directory/'approval.json'
    for item in (folder/'review', directory, path, metadata_path, approval_path):
        if item.is_symlink():
            raise IngestionError('Symlink approved source refused')
    if approval.get('path') != f'review/r{revision:06d}/knowledge.md' or read_json(approval_path) != approval:
        raise IngestionError('Approval record does not match the immutable snapshot')
    if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise IngestionError('Approved knowledge exceeds the size limit')
    original = path.read_bytes()
    if digest(original) != approval.get('knowledge_sha256') or digest(metadata_path.read_bytes()) != approval.get('metadata_sha256'):
        raise IngestionError('Approved snapshot changed; indexing refused')
    raw = normalized_bytes(original)
    if not raw.strip() or b'\x00' in raw:
        raise IngestionError('Approved knowledge is empty or contains null bytes')
    metadata = read_json(metadata_path)
    title = metadata.get('meeting_title')
    title = title.strip() if isinstance(title, str) and title.strip() else 'untitled-meeting'
    date = metadata.get('meeting_date')
    if date is not None:
        if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise IngestionError('Invalid metadata date')
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            raise IngestionError('Invalid metadata date') from None
    else:
        date = 'date-unknown'
    # Identity is derived from the exact folder name; independent of editable metadata.
    job_id = re.search(r'_([0-9a-f]{32})$', folder.name)
    identity = job_id[1] if job_id else hashlib.sha256(folder.name.encode()).hexdigest()[:20]
    sha = digest(raw)
    filename = f'{date}__{slug(title)}__{identity}__{sha[:12]}.md'
    return {'key': folder.name, 'sha256': sha, 'filename': filename, 'identity': identity,
            'source': str(path), 'raw': raw, 'approval_revision': revision, 'approval_sha256': approval['knowledge_sha256']}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward an API key to an unexpected redirect destination.


class Client:
    def __init__(self, base_url, token, timeout=60):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise IngestionError('Base URL must be an HTTP(S) origin without credentials/query/fragment')
        if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise IngestionError('Use HTTPS for a non-loopback Open WebUI address')
        if parsed.path not in ('', '/'):
            raise IngestionError('Use the base origin, without /api or another path')
        self.base = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, obj=None, raw=None, content_type=None, binary=False):
        body = json.dumps(obj).encode() if obj is not None else raw
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'}
        if obj is not None:
            headers['Content-Type'] = 'application/json'
        elif content_type:
            headers['Content-Type'] = content_type
        req = Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise IngestionError('API response exceeded safety limit')
            return data if binary else json.loads(data)
        except HTTPError as exc:
            raise APIError(exc.code, path.split('?')[0]) from None
        except (TimeoutError, URLError, OSError):
            raise IngestionError(f'Connection timed out or failed for {path.split("?")[0]}. '
                                 'A server operation may still be running; inspect status before retrying.') from None
        except (ValueError, UnicodeError):
            raise IngestionError('API returned invalid JSON; verify the base URL points to Open WebUI') from None

    def pages(self, path):
        output = []
        for page in range(1, 10001):
            result = self.request('GET', path + ('&' if '?' in path else '?') + f'page={page}')
            if not isinstance(result, dict) or not isinstance(result.get('items'), list):
                raise IngestionError('Unexpected paginated API response; expected Open WebUI 0.12.3')
            rows = result['items']
            output.extend(rows)
            if not rows or len(output) >= result.get('total', len(output)):
                return output
        raise IngestionError('API pagination exceeded limit')

    def version(self):
        version = self.request('GET', '/api/version').get('version')
        if version != '0.12.3':
            raise IngestionError(f'Expected Open WebUI 0.12.3, found {version!r}; verify API compatibility before upgrading')

    def collections(self):
        return self.pages('/api/v1/knowledge/')

    def files(self, collection):
        return self.pages('/api/v1/knowledge/' + quote(collection, safe='') + '/files')

    def raw_file(self, file_id):
        return self.request('GET', '/api/v1/files/' + quote(file_id, safe='') + '/content', binary=True)

    def stored_files(self, filename):
        """Find a possibly orphaned upload by its exact deterministic name."""
        result = []
        for skip in range(0, 100000, 100):
            try:
                rows = self.request('GET', '/api/v1/files/search?filename=' + quote(filename, safe='') +
                                    f'&content=false&skip={skip}&limit=100')
            except APIError as exc:
                if exc.status == 404:
                    return result
                raise
            if not isinstance(rows, list):
                raise IngestionError('Unexpected file-search API response')
            result.extend(row for row in rows if row.get('filename') == filename)
            if len(rows) < 100:
                return result
        raise IngestionError('File-search pagination exceeded limit')

    def upload(self, doc):
        boundary = 'meeting-' + secrets.token_hex(16)
        # knowledge_id omitted: processing and collection membership are tracked separately.
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{doc["filename"]}"\r\nContent-Type: text/markdown\r\n\r\n').encode()
        body = head + doc['raw'] + f'\r\n--{boundary}--\r\n'.encode()
        result = self.request('POST', '/api/v1/files/?process=true&process_in_background=true',
                              raw=body, content_type='multipart/form-data; boundary=' + boundary)
        if not isinstance(result, dict) or not isinstance(result.get('id'), str):
            raise IngestionError('Upload response did not contain a file ID; inspect Open WebUI before retrying')
        return result['id']

    def wait(self, file_id, seconds, pause=2):
        deadline = time.monotonic() + seconds
        previous = None
        while True:
            result = self.request('GET', '/api/v1/files/' + quote(file_id, safe='') + '/process/status')
            status = result.get('status')
            if status != previous:
                emit(f'  File processing: {status}')
                previous = status
            if status == 'completed':
                return
            if status == 'failed':
                raise IngestionError('Open WebUI file processing failed; pending file ID retained in local state. '
                                     'Inspect Open WebUI, remove the failed upload there, then retry.')
            if status not in ('pending', 'processing', 'queued', None):
                raise IngestionError(f'Unexpected processing status: {status!r}')
            if time.monotonic() >= deadline:
                raise IngestionError('Processing wait expired; pending file ID retained. Re-run to resume polling.')
            time.sleep(pause)

    def add(self, collection, file_id):
        return self.request('POST', '/api/v1/knowledge/' + quote(collection, safe='') + '/file/add', {'file_id': file_id})

    def remove(self, collection, file_id):
        # Explicitly retain the uploaded file resource; never delete a global file.
        return self.request('POST', '/api/v1/knowledge/' + quote(collection, safe='') + '/file/remove?delete_file=false', {'file_id': file_id})


class State:
    def __init__(self, path, config):
        self.path = Path(path)
        self.identity = {key: config[key] for key in ('base_url', 'collection_id', 'meetings_root')}
        self.data = read_json(path) if self.path.exists() else {'schema': 1, 'destination': self.identity, 'meetings': {}}
        if self.data.get('schema') != 1 or self.data.get('destination') != self.identity:
            raise IngestionError('State destination/root differs from configuration; use a separate state file')

    def save(self):
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix('.json.bak'))
        save_json(self.path, self.data)


def worker_busy(root):
    path = Path(root) / 'jobs.sqlite3'
    review_db = Path(root)/'reviews.sqlite3'
    if review_db.exists():
        try:
            with closing(sqlite3.connect(review_db.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as review_connection:
                if review_connection.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[0]:
                    return True
        except sqlite3.Error:
            raise IngestionError('Could not read review queue; deferring ingestion') from None
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            return connection.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('waiting_upload','uploading','queued','transcribing','analyzing') AND (state != 'waiting_upload' OR created > ?)", (time.time() - 1800,)).fetchone()[0] > 0
    except sqlite3.Error:
        raise IngestionError('Could not read worker queue; refusing to compete with unknown worker activity') from None


def verify_destination(client, config):
    client.version()
    kb = client.request('GET', '/api/v1/knowledge/' + quote(config['collection_id'], safe=''))
    if not isinstance(kb, dict) or kb.get('id') != config['collection_id']:
        raise IngestionError('Destination knowledge collection not found')
    if not kb.get('write_access'):
        raise IngestionError('API account needs write access to the destination knowledge collection')
    emit('Destination collection: ' + str(kb.get('name', kb['id'])))


def sync(client, config, state, apply=False, include_legacy=False, limit=None, busy=worker_busy):
    root = Path(config['meetings_root'])
    if not root.is_dir():
        raise IngestionError('Meetings root does not exist')
    verify_destination(client, config)
    remote = {row['id']: row for row in client.files(config['collection_id'])}
    hashes = {}
    report = {'mode': 'apply' if apply else 'dry-run', 'started': now(), 'uploaded': 0,
              'adopted': 0, 'unchanged': 0, 'skipped': 0, 'errors': [], 'deferred': False, 'planned': 0}
    operations = 0
    for folder in sorted(root.glob('processed-*')):
        if not folder.is_dir():
            continue
        try:
            pending_snapshot = state.data['meetings'].get(folder.name, {}).get('pending')
            if pending_snapshot and not pending_snapshot.get('approval_revision'):
                raise IngestionError('Pre-review pending upload is unapproved; reconcile it before resuming ingestion')
            doc = document(folder, root, include_legacy,
                           approved_revision=pending_snapshot.get('approval_revision') if pending_snapshot else None)
            if doc is None:
                report['skipped'] += 1
                continue
            key = doc['key']
            # Copy through JSON so dry-run never mutates local state.
            entry = json.loads(json.dumps(state.data['meetings'].get(key, {})))
            committed, pending = entry.get('committed'), entry.get('pending')
            if pending and pending['sha256'] != doc['sha256']:
                raise IngestionError('Source changed while an upload was pending. Restore that source snapshot or '
                                     'finish/reconcile the pending file before changing it again; see README.')
            managed_elsewhere = {e.get('committed', {}).get('file_id') for k, e in state.data['meetings'].items() if k != key}
            candidates = [r for r in remote.values() if r['id'] not in managed_elsewhere and
                          (r.get('filename') in ('knowledge.md', doc['filename']) or
                           r['id'] == (committed or {}).get('file_id'))]
            matches = []
            for row in candidates:
                fid = row['id']
                if fid not in hashes:
                    try:
                        raw = client.raw_file(fid)
                        hashes[fid] = digest(normalized_bytes(raw)) if len(raw) <= MAX_FILE_BYTES else None
                    except UnicodeError:
                        hashes[fid] = None
                if hashes[fid] == doc['sha256']:
                    matches.append(fid)
            if len(matches) > 1:
                raise IngestionError('Multiple exact copies already exist in the collection. Remove the duplicate '
                                     'collection entries manually; no copies were removed by this tool.')
            clean = bool(committed and committed['sha256'] == doc['sha256'] and committed['file_id'] in matches and not pending)
            if clean:
                emit('UNCHANGED ' + doc['filename'])
                report['unchanged'] += 1
                continue
            if limit is not None and operations >= limit:
                break
            if apply and busy(root):
                emit('DEFERRED: meeting worker has an active/recent upload or queued/processing job')
                report['deferred'] = True
                break
            operations += 1
            report['planned'] += 1
            action = 'ADOPT' if matches else ('RESUME' if pending else ('REPLACE' if committed else 'UPLOAD'))
            emit(('APPLY ' if apply else 'WOULD ') + action + ' ' + doc['filename'])
            if not apply:
                continue
            # Keep the exact normalized source used for this indexed version.
            snapshot = state.path.parent / 'snapshots' / (doc['sha256'] + '.md')
            if not snapshot.exists():
                atomic(snapshot, doc['raw'].decode('utf-8'))
            if matches:
                new_id = matches[0]
                # Adoption reuses exact source bytes, including the manual test upload.
                # Keep its original remote name to avoid changing someone else's file metadata.
                was_adopted = pending.get('adopted', False) if pending else True
                pending = {k: doc[k] for k in ('sha256', 'filename', 'source', 'approval_revision', 'approval_sha256')}
                pending.update(file_id=new_id, adopted=was_adopted)
                entry['pending'] = pending
                state.data['meetings'][key] = entry
                state.save()
                report['adopted'] += 1
            else:
                if not pending:
                    # Save an intent BEFORE upload. Deterministic name supports interrupted-upload recovery.
                    pending = {k: doc[k] for k in ('sha256', 'filename', 'source', 'approval_revision', 'approval_sha256')}
                    pending.update(file_id=None, adopted=False)
                    entry['pending'] = pending
                    state.data['meetings'][key] = entry
                    state.save()
                if pending.get('file_id'):
                    try:
                        client.request('GET', '/api/v1/files/' + quote(pending['file_id'], safe=''))
                    except APIError as exc:
                        if exc.status != 404:
                            raise
                        pending['file_id'] = None
                        state.save()
                if not pending.get('file_id'):
                    # Search the account's uploads for a lost upload response before ever re-uploading.
                    existing = client.stored_files(doc['filename'])
                    recovered = []
                    for row in existing:
                        if row.get('filename') == doc['filename'] and digest(normalized_bytes(client.raw_file(row['id']))) == doc['sha256']:
                            recovered.append(row['id'])
                    if len(recovered) > 1:
                        raise IngestionError('Multiple pending uploads have the deterministic filename; reconcile in Open WebUI')
                    pending['file_id'] = recovered[0] if recovered else client.upload(doc)
                    entry['pending'] = pending
                    state.save()
                new_id = pending['file_id']
                client.wait(new_id, config.get('processing_timeout_seconds', 900))
                if new_id not in remote:
                    try:
                        client.add(config['collection_id'], new_id)
                    except IngestionError:
                        # A timeout/duplicate response may follow a successful server-side attach.
                        remote = {r['id']: r for r in client.files(config['collection_id'])}
                        if new_id not in remote:
                            raise
                    remote = {r['id']: r for r in client.files(config['collection_id'])}
                if new_id not in remote:
                    raise IngestionError('File upload completed but collection membership was not confirmed')
                report['uploaded'] += 1
            old_id = (committed or {}).get('file_id')
            if old_id and old_id != new_id and old_id in remote:
                client.remove(config['collection_id'], old_id)
                remote = {r['id']: r for r in client.files(config['collection_id'])}
                if old_id in remote:
                    raise IngestionError('Old version still attached; pending state retained')
                emit('  Detached previous indexed version; uploaded file resource retained: ' + old_id)
            if committed and committed.get('file_id') != new_id:
                entry.setdefault('history', []).append({**committed, 'superseded_at': now()})
            entry['committed'] = {**pending, 'indexed_at': now()}
            entry.pop('pending', None)
            state.data['meetings'][key] = entry
            state.save()
            emit('INDEXED ' + doc['filename'] + ' | file ID: ' + new_id)
        except (IngestionError, ValueError, OSError, KeyError) as exc:
            # Avoid printing arbitrary remote content or tokens.
            message = str(exc) if isinstance(exc, IngestionError) else type(exc).__name__ + ': invalid/unreadable source or state'
            emit('ERROR ' + folder.name + ': ' + message)
            report['errors'].append({'meeting': folder.name, 'error': message})
            # Stop after first failure to avoid multiplying slow/ambiguous server operations.
            break
    report['finished'] = now()
    emit('SUMMARY ' + json.dumps({k: v for k, v in report.items() if k not in ('errors',)}, ensure_ascii=False))
    return report


def rollback(client, config, state, meeting, apply=False):
    verify_destination(client, config)
    entry = state.data['meetings'].get(meeting)
    if not entry or not entry.get('committed') or entry.get('pending'):
        raise IngestionError('Rollback requires a managed meeting with a committed version and no pending operation')
    current = entry['committed']
    previous = entry.get('history', [])[-1] if entry.get('history') else None
    if not previous and current.get('adopted'):
        emit('Initial version was adopted from a manual upload: rollback will forget management and retain that file')
    else:
        emit('Rollback will restore previous version' if previous else 'Rollback will detach the initial managed upload')
    if not apply:
        emit('Dry run. Add --apply to carry out this rollback.')
        return
    if worker_busy(config['meetings_root']):
        raise IngestionError('Wait until meeting processing/uploads are idle before rollback')
    members = {row['id'] for row in client.files(config['collection_id'])}
    if previous and previous['file_id'] not in members:
        client.request('GET', '/api/v1/files/' + quote(previous['file_id'], safe=''))
        client.add(config['collection_id'], previous['file_id'])
        members = {row['id'] for row in client.files(config['collection_id'])}
        if previous['file_id'] not in members:
            raise IngestionError('Previous version could not be verified in collection; current version retained')
    if (previous or not current.get('adopted')) and current['file_id'] in members:
        client.remove(config['collection_id'], current['file_id'])
        if current['file_id'] in {row['id'] for row in client.files(config['collection_id'])}:
            raise IngestionError('Current version still attached; rollback state was not committed')
    if previous:
        entry['committed'] = entry['history'].pop()
    else:
        del state.data['meetings'][meeting]
    state.save()
    emit('Rollback complete. Global uploaded files and local meeting files were retained.')


def load_config(path):
    config = read_json(path)
    for key in ('base_url', 'collection_id', 'meetings_root'):
        if not isinstance(config.get(key), str) or not config[key]:
            raise IngestionError('Invalid or missing configuration field: ' + key)
    config['base_url'] = config['base_url'].rstrip('/')
    config['meetings_root'] = str(Path(config['meetings_root']).expanduser().resolve())
    for key, default in (('processing_timeout_seconds', 900), ('request_timeout_seconds', 120)):
        value = config.get(key, default)
        if type(value) is not int or not 1 <= value <= 7200:
            raise IngestionError(f'{key} must be an integer between 1 and 7200')
    return config


def load_key(path):
    path = Path(path)
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise IngestionError('API key file permissions must be 600; run chmod 600 on the key file')
    token = path.read_text(encoding='utf-8').strip()
    if not token or any(c.isspace() for c in token):
        raise IngestionError('API key file must contain one nonempty key')
    return token


def configure(config_path):
    home = config_path.parent
    if config_path.exists() or (home / 'api-key.txt').exists() or (home / 'state.json').exists():
        raise IngestionError('Configuration/key/state already exists. Back it up and edit config.json deliberately; configure will not overwrite it.')
    home.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        home.chmod(0o700)
    base = input('Open WebUI base URL [http://127.0.0.1:8080]: ').strip() or 'http://127.0.0.1:8080'
    print('Paste the API key at the next prompt, then press Enter. No characters or dots will appear.', flush=True)
    token = getpass.getpass('Open WebUI API key (hidden; never paste it into chat): ').strip()
    if not token or any(c.isspace() for c in token):
        raise IngestionError('Enter a single API key')
    client = Client(base, token, timeout=15)
    emit('Step 1/2: checking Open WebUI version (15-second socket timeout)...')
    client.version()
    emit('Step 2/2: loading writable knowledge collections (15-second socket timeout per request)...')
    collections = [k for k in client.collections() if k.get('write_access')]
    if not collections:
        raise IngestionError('No writable knowledge collection found; create Meeting Archive in Open WebUI first')
    for index, kb in enumerate(collections, 1):
        print(f'{index}. {kb["name"]} | ID: {kb["id"]}')
    selection = input('Collection number: ').strip()
    if not selection.isdigit() or not 1 <= int(selection) <= len(collections):
        raise IngestionError('Choose a listed collection number')
    kb = collections[int(selection) - 1]
    root = input(f'Meetings root [{Path.home() / "ai-platform/meetings"}]: ').strip()
    root = Path(root).expanduser().resolve() if root else Path.home() / 'ai-platform/meetings'
    if not root.is_dir():
        raise IngestionError('Meetings root does not exist')
    config = {'base_url': client.base, 'collection_id': kb['id'], 'meetings_root': str(root),
              'processing_timeout_seconds': 900, 'request_timeout_seconds': 120}
    atomic(home / 'api-key.txt', token + '\n')
    save_json(config_path, config)
    emit('Configured. Run sync for a read-only remote dry run, then sync --apply to ingest.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_HOME / 'config.json')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('configure', help='Interactive setup; never sends the key to chat')
    commands.add_parser('status', help='Show local last-run and managed-file status; no server requests')
    back = commands.add_parser('rollback', help='Restore a managed meeting previous indexed version; default dry run')
    back.add_argument('--meeting', required=True, help='Exact processed-* folder name from status')
    back.add_argument('--apply', action='store_true')
    scan = commands.add_parser('sync', help='Default dry run; --apply writes to Open WebUI')
    scan.add_argument('--apply', action='store_true')
    scan.add_argument('--include-legacy', action='store_true', help='Include approved legacy snapshots without a job.json; approval still required')
    scan.add_argument('--limit', type=int, help='Limit changed/adopted meetings per run')
    args = parser.parse_args()
    os.umask(0o077)
    config_path = args.config.expanduser().resolve()
    home = config_path.parent
    try:
        with locked(home / 'ingestion.lock'):
            if args.command == 'configure':
                configure(config_path)
                return 0
            config = load_config(config_path)
            state = State(home / 'state.json', config)
            if args.command == 'status':
                print(json.dumps({'last_run': read_json(home / 'last-run.json') if (home / 'last-run.json').exists() else None,
                                  'meetings': state.data['meetings']}, ensure_ascii=False, indent=2))
                return 0
            if args.command == 'sync' and args.limit is not None and args.limit < 1:
                raise IngestionError('--limit must be positive')
            client = Client(config['base_url'], load_key(home / 'api-key.txt'), config.get('request_timeout_seconds', 120))
            if args.command == 'rollback':
                rollback(client, config, state, args.meeting, args.apply)
                return 0
            result = sync(client, config, state, args.apply, args.include_legacy, args.limit)
            save_json(home / 'last-run.json', result)
            return 1 if result['errors'] else (75 if result['deferred'] else 0)
    except KeyboardInterrupt:
        emit('Cancelled. Existing meeting services were not changed. No API key was printed.')
        return 130
    except (IngestionError, ValueError, OSError, KeyError) as exc:
        emit('ERROR: ' + (str(exc) if isinstance(exc, IngestionError) else type(exc).__name__ + ': invalid or missing local configuration/state'))
        return 1


if __name__ == '__main__':
    sys.exit(main())
