"""Atomic, human-readable project storage. Audio stays beside its manifest."""

import json
import threading
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def directory(self, track_id: str) -> Path:
        if len(track_id) != 32 or any(c not in "0123456789abcdef" for c in track_id):
            raise KeyError(track_id)
        return self.root / track_id

    def get(self, track_id: str):
        with self.lock:
            try:
                return json.loads((self.directory(track_id) / "track.json").read_text())
            except FileNotFoundError:
                raise KeyError(track_id) from None

    def put(self, track):
        with self.lock:
            folder = self.directory(track["id"])
            folder.mkdir(parents=True, exist_ok=True)
            temp = folder / "track.tmp"
            temp.write_text(json.dumps(track, indent=2))
            temp.replace(folder / "track.json")
        return track

    def update(self, track_id: str, **changes):
        with self.lock:
            track = self.get(track_id)
            track.update(changes)
            return self.put(track)

    def list(self):
        with self.lock:
            tracks = []
            for path in self.root.glob("*/track.json"):
                try:
                    tracks.append(json.loads(path.read_text()))
                except (ValueError, OSError):
                    continue
            return sorted(tracks, key=lambda t: t["created_at"], reverse=True)
