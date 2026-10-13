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

    @staticmethod
    def _ensure_take_numbers(track) -> bool:
        """Upgrade legacy run metadata without changing established take numbers."""
        runs = track.get("runs")
        if not isinstance(runs, list):
            return False

        changed = False
        used = set()
        missing = []
        for run in runs:
            take_number = run.get("take_number")
            if (
                isinstance(take_number, int)
                and not isinstance(take_number, bool)
                and take_number > 0
                and take_number not in used
            ):
                used.add(take_number)
            else:
                missing.append(run)

        take_number = 1
        for run in missing:
            while take_number in used:
                take_number += 1
            run["take_number"] = take_number
            used.add(take_number)
            take_number += 1
            changed = True

        minimum_next = max(used, default=0) + 1
        stored_next = track.get("next_take_number")
        if not isinstance(stored_next, int) or isinstance(stored_next, bool) or stored_next < minimum_next:
            track["next_take_number"] = minimum_next
            changed = True
        return changed

    def get(self, track_id: str):
        with self.lock:
            try:
                track = json.loads((self.directory(track_id) / "track.json").read_text())
            except FileNotFoundError:
                raise KeyError(track_id) from None
            if self._ensure_take_numbers(track):
                self.put(track)
            return track

    def put(self, track):
        with self.lock:
            self._ensure_take_numbers(track)
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
                    track = json.loads(path.read_text())
                    if self._ensure_take_numbers(track):
                        self.put(track)
                    tracks.append(track)
                except (ValueError, OSError):
                    continue
            return sorted(tracks, key=lambda t: t["created_at"], reverse=True)
