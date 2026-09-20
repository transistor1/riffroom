"""Trusted separation-provider contract."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from riffroom.models import ModelProfile


def normalized_stem_paths(stems: tuple[str, ...], output: Path) -> dict[str, Path]:
    """Return deterministic WAV paths, normalizing provider filename casing."""
    paths = {name: output / f"{name}.wav" for name in stems}
    for name, path in paths.items():
        if not path.exists():
            matches = [
                candidate
                for candidate in output.glob("*.wav")
                if candidate.stem.casefold() == name.casefold()
            ]
            if len(matches) == 1:
                matches[0].rename(path)
    return paths


class SeparationProvider(Protocol):
    """Produce the stem files declared by a trusted model profile."""

    def is_available(self) -> bool: ...

    def separate(
        self,
        profile: ModelProfile,
        source: Path,
        output: Path,
        cache: Path,
        *,
        on_model_loaded: Callable[[], None],
    ) -> dict[str, Path]: ...
