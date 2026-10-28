import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Linking publishes the complete file atomically and refuses overwrites.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
        raise OSError('File verification failed')


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False permits use across the API and test/control
        # threads; it does not make a shared connection/cursor transaction safe.
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'frame.sqlite', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS entities(kind TEXT, id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS frame_position ON entities(json_extract(payload,'$.roll_id'),json_extract(payload,'$.index')) WHERE kind='frames'")
        self.db.execute('PRAGMA user_version=1')
        self.db.commit()

    def all(self, kind):
        with self._lock:
            rows = self.db.execute('SELECT payload FROM entities WHERE kind=? ORDER BY rowid', (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, kind, entity_id):
        with self._lock:
            row = self.db.execute('SELECT payload FROM entities WHERE kind=? AND id=?', (kind, entity_id)).fetchone()
        if not row:
            raise KeyError(entity_id)
        return json.loads(row[0])

    def save(self, kind, item):
        with self._lock, self.db:
            self.db.execute('INSERT INTO entities VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload WHERE kind=excluded.kind', (kind, item['id'], json.dumps(item)))
        return item

    def backup(self):
        target = self.root / 'backups' / f'v1-{uuid.uuid4().hex}.sqlite'
        target.parent.mkdir(exist_ok=True)
        with self._lock, sqlite3.connect(target) as destination:
            self.db.backup(destination)
        return target

    def close(self):
        with self._lock:
            self.db.close()

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Invalid archive path')
        return path
