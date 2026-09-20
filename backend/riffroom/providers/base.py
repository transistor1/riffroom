"""Trusted separation-provider contract."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from riffroom.models import ModelProfile


class SeparationProvider(Protocol):
    """Produce the stem files declared by a trusted model profile."""

    def separate(
        self,
        profile: ModelProfile,
        source: Path,
        output: Path,
        cache: Path,
        *,
        on_model_loaded: Callable[[], None],
    ) -> dict[str, Path]: ...
