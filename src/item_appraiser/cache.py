"""A small on-disk store for model responses, keyed by everything that shaped the request.

Provider-neutral: an appraiser builds a JSON-serializable key from the model,
prompt and listing, and stores whatever record it needs to rebuild an appraisal.
"""

import hashlib
import json
import os
from pathlib import Path


def digest(key: dict) -> str:
    """A stable hex digest of a JSON-serializable key."""
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


class ResponseCache:
    def __init__(self, directory: str | os.PathLike):
        self.directory = Path(directory)

    def path(self, key: dict) -> Path:
        return self.directory / f"{digest(key)}.json"

    def __contains__(self, key: dict) -> bool:
        return self.path(key).exists()

    def get(self, key: dict) -> dict | None:
        path = self.path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: dict, record: dict) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=1), encoding="utf-8")
        os.replace(temporary, path)  # atomic, so a crash never leaves half a record
