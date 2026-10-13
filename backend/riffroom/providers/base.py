"""Trusted separation-provider contract."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from riffroom.models import ExecutionVariant, ModelProfile


def normalized_stem_paths(
    stems: tuple[str, ...],
    output: Path,
    *,
    output_aliases: tuple[tuple[str, str], ...] = (),
) -> dict[str, Path]:
    """Return logical WAV paths, normalizing exact trusted aliases and filename casing."""
    paths = {name: output / f"{name}.wav" for name in stems}
    for name, path in paths.items():
        if not path.exists():
            accepted_names = {
                name.casefold(),
                *(upstream.casefold() for upstream, logical in output_aliases if logical == name),
            }
            matches = [
                candidate
                for candidate in output.glob("*.wav")
                if candidate.stem.casefold() in accepted_names
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
        variant: ExecutionVariant,
        source: Path,
        output: Path,
        cache: Path,
        *,
        on_model_loaded: Callable[[], None],
    ) -> dict[str, Path]: ...
