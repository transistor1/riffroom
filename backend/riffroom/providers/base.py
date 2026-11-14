"""Trusted separation-provider contract."""

import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypedDict

from riffroom.models import SAFE_STEM_NAME, ExecutionVariant, ModelProfile

MAX_OUTPUT_STEMS = 32
MAX_STEM_NAME = 80
OUTPUT_WARNING_MESSAGE = (
    "The separation model's output differed from what Riffroom expected. "
    "The results are available using their output filenames. "
    "This may indicate a model compatibility mismatch. Please notify the developer."
)


class OutputWarning(TypedDict):
    code: str
    message: str
    expected_stems: list[str]
    actual_files: list[str]


class StemPaths(dict[str, Path]):
    """A mapping compatible with older providers, with optional result metadata."""

    def __init__(self, paths: dict[str, Path], warning: OutputWarning):
        super().__init__(paths)
        self.output_warning = warning


class StemNamingMismatch(ValueError):
    """Successful runtime outputs could not be assigned trusted logical names."""


def generated_wav_paths(output: Path) -> dict[str, Path]:
    """Inventory only direct, safe WAV files; reject unsafe entries, never follow links."""
    validate_output_directory(output)
    paths = {}
    names = set()
    identities = set()
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path.suffix.casefold() != ".wav":
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"Unsafe WAV output {path.name!r}: regular files required; symlinks are forbidden.")
        identity = (metadata.st_dev, metadata.st_ino)
        if metadata.st_nlink != 1 or identity in identities:
            raise ValueError(f"Unsafe WAV output {path.name!r}: hardlinked or duplicate file.")
        name = path.stem
        if (
            not name.strip() or name in {".", "..", "__proto__", "constructor", "prototype"}
            or any(char in name for char in "\\/:")
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
        ):
            raise ValueError(f"Unsafe WAV output name: {path.name!r}")
        if name.casefold() in names:
            raise ValueError(f"Colliding WAV output names: {path.name!r}")
        paths[name] = path
        names.add(name.casefold())
        identities.add(identity)
        if len(paths) > MAX_OUTPUT_STEMS:
            raise ValueError(f"The separator produced more than {MAX_OUTPUT_STEMS} WAV outputs.")
    if not paths:
        raise ValueError("The separator produced no WAV files.")
    return paths


def completed_stem_paths(
    stems: tuple[str, ...], output: Path, *,
    output_aliases: tuple[tuple[str, str], ...] = (),
    source: Path | None = None, model_filename: str | None = None,
) -> dict[str, Path]:
    """After successful inference, keep every safe output if strict naming differs.

    This fallback must remain even when model metadata discovery is added later.
    The worker must still validate all audio before persisting the result.
    """
    names = custom_output_names(stems, output_aliases=output_aliases)
    actual = generated_wav_paths(output)
    if len(actual) == len(stems):
        try:
            return normalized_stem_paths(
                stems, output, output_aliases=output_aliases, source=source, model_filename=model_filename,
            )
        except StemNamingMismatch:
            pass

    # Resolve only unique trusted identities. Ambiguous candidates keep filename
    # labels, even when one candidate happens to have a canonical filename.
    accepted = {name.casefold(): name for name in stems}
    accepted.update((upstream.casefold(), logical) for upstream, logical in names.items())
    tokens = {path: output_token(path, source, model_filename) for path in actual.values()}
    candidates = {name: [] for name in stems}
    for path, token in tokens.items():
        logical = accepted.get(token.casefold())
        if logical is not None:
            candidates[logical].append(path)
    confident = {paths[0]: name for name, paths in candidates.items() if len(paths) == 1}
    paths = dict((name, path) for path, name in confident.items())
    used = {name.casefold() for name in stems}
    for path, token in tokens.items():
        if path in confident:
            continue
        label = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_-]+", "_", token))
        label = label.strip("_-").lower()[:MAX_STEM_NAME] or "output"
        if label.casefold() in used or label in {"constructor", "prototype", "__proto__"}:
            label = "output_" + label
        label = label[:MAX_STEM_NAME]
        base, index = label, 2
        while (
            label.casefold() in used
            or ((output / f"{label}.wav").exists() and not (output / f"{label}.wav").samefile(path))
            or (output / f"{label}.wav").is_symlink()
        ):
            suffix = f"_{index}"
            label = base[:MAX_STEM_NAME - len(suffix)] + suffix
            index += 1
        used.add(label.casefold())
        paths[label] = path
    # Plan every destination before mutating anything. Never overwrite another
    # output, including auxiliary files, or silently merge two filename labels.
    normalized = rename_stems(paths, output)
    return StemPaths(normalized, {
        "code": "unexpected_model_outputs",
        "message": OUTPUT_WARNING_MESSAGE,
        "expected_stems": list(stems),
        "actual_files": [path.name for path in actual.values()],
    })


def output_token(path: Path, source: Path | None, model_filename: str | None) -> str:
    """Strip only the exact runtime source/model wrapper, retaining its token."""
    if source is not None and model_filename is not None:
        model = Path(model_filename)
        if model.name != model_filename or "\\" in model_filename or not model.stem:
            raise ValueError("Cannot normalize separation outputs: unsafe model filename")
        prefix, suffix = source.stem + "_(", ")_" + model.stem
        token = path.stem
        if token.casefold().startswith(prefix.casefold()) and token.casefold().endswith(suffix.casefold()):
            middle = token[len(prefix):-len(suffix)]
            if middle and "(" not in middle and ")" not in middle:
                return middle
    return path.stem


def rename_stems(selected: dict[str, Path], output: Path) -> dict[str, Path]:
    paths = {name: output / f"{name}.wav" for name in selected}
    for name, path in selected.items():
        target = paths[name]
        if target.is_symlink() or (target.exists() and not target.samefile(path)):
            raise ValueError(f"Cannot normalize separation outputs: destination {target.name!r} is occupied")
    for name, path in selected.items():
        if path != paths[name]:
            path.rename(paths[name])
    return paths


def validate_selected_paths(paths: dict[str, Path], output: Path) -> None:
    """Independently enforce the provider boundary before reading any audio."""
    actual = generated_wav_paths(output)
    if not paths or len(paths) > MAX_OUTPUT_STEMS:
        raise ValueError("The separator produced an invalid number of stems.")
    labels = set()
    selected = set()
    for name, path in paths.items():
        if (
            not SAFE_STEM_NAME.fullmatch(name) or len(name) > MAX_STEM_NAME
            or name.casefold() in labels or name.casefold() in {"constructor", "prototype", "__proto__"}
            or path.parent.resolve() != output.resolve() or path not in actual.values()
        ):
            raise ValueError("Unsafe or duplicate separation output mapping.")
        labels.add(name.casefold())
        selected.add(path)
    if len(selected) != len(paths) or selected != set(actual.values()):
        raise ValueError("The provider did not select every distinct WAV output.")


def custom_output_names(
    stems: tuple[str, ...],
    *,
    output_aliases: tuple[tuple[str, str], ...] = (),
) -> dict[str, str]:
    """Build upstream names only from safe, non-overlapping trusted metadata."""
    if not stems or len(stems) > MAX_OUTPUT_STEMS or any(
        not SAFE_STEM_NAME.fullmatch(name) or len(name) > MAX_STEM_NAME
        or name.casefold() in {"constructor", "prototype", "__proto__"} for name in stems
    ):
        raise ValueError(f"Invalid trusted output stems: {stems!r}")
    tokens = {name.casefold() for name in stems}
    if len(tokens) != len(stems):
        raise ValueError(f"Duplicate trusted output stems: {stems!r}")
    names = {name: name for name in stems}
    for upstream, logical in output_aliases:
        if (
            not SAFE_STEM_NAME.fullmatch(upstream)
            or logical not in stems
            or upstream.casefold() in tokens
        ):
            raise ValueError(f"Invalid trusted output alias: {upstream!r} -> {logical!r}")
        tokens.add(upstream.casefold())
        names.pop(logical, None)
        names[upstream] = logical
    return names


def validate_output_directory(output: Path) -> None:
    """Require a real output directory before allowing a runtime to write."""
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Separation output must be a directory, not a symlink.")


def restricted_output_path(output: Path, stem_path: str) -> Path:
    """Confine MLX's write callback to regular files directly in its output folder."""
    validate_output_directory(output)
    path = Path(stem_path)
    if (
        ".." in path.parts
        or "\\" in stem_path
        or (path.parent != Path(".") and path.parent.resolve() != output.resolve())
    ):
        raise ValueError(f"Unsafe separation output path: {stem_path!r}")
    target = output / path.name
    if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink > 1)):
        raise ValueError(f"Unsafe separation output file: {target.name!r}")
    return target


def normalized_stem_paths(
    stems: tuple[str, ...],
    output: Path,
    *,
    output_aliases: tuple[tuple[str, str], ...] = (),
    source: Path | None = None,
    model_filename: str | None = None,
) -> dict[str, Path]:
    """Resolve every stem before renaming; never guess from source/model words.

    Besides bare logical names and trusted aliases, accept the exact upstream
    grammar <source>_(<token>)_<model>.wav when source/model context is supplied.
    Audio contents and alignment remain the worker's validation responsibility.
    """
    names = custom_output_names(stems, output_aliases=output_aliases)
    accepted = {name.casefold(): name for name in stems}
    accepted.update((upstream.casefold(), logical) for upstream, logical in names.items())
    entries = (
        sorted(output.iterdir(), key=lambda path: path.name)
        if not output.is_symlink() and output.is_dir()
        else []
    )

    def fail(detail: str, error_type: type[ValueError] = ValueError) -> None:
        raise error_type(
            f"Cannot normalize separation outputs: {detail}. "
            f"Expected stems: {', '.join(stems)}. "
            f"Observed files: {', '.join(repr(path.name) for path in entries) or '(none)'}"
        )

    if output.is_symlink() or not output.is_dir():
        fail("output must be a directory, not a symlink")
    prefix = suffix = ""
    if source is not None and model_filename is not None:
        model = Path(model_filename)
        if model.name != model_filename or "\\" in model_filename or not model.stem:
            fail("unsafe model filename")
        prefix = source.stem.casefold() + "_("
        suffix = ")_" + model.stem.casefold()

    candidates: dict[str, list[Path]] = {name: [] for name in stems}
    identities = {}
    for path in entries:
        if path.suffix.casefold() != ".wav":
            continue
        token = path.stem.casefold()
        if prefix and token.startswith(prefix) and token.endswith(suffix):
            token = token[len(prefix):-len(suffix)]
        logical = accepted.get(token)
        if logical is None:
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            fail(f"{path.name!r} is not a regular file (symlinks are forbidden)")
        candidates[logical].append(path)
        identities[path] = (metadata.st_dev, metadata.st_ino)

    selected = {}
    problems = []
    for name, matches in candidates.items():
        exact = next((path for path in matches if path.name == f"{name}.wav"), None)
        if exact is not None:
            selected[name] = exact
        elif len(matches) == 1:
            selected[name] = matches[0]
        elif matches:
            problems.append(f"ambiguous {name!r}: {', '.join(repr(path.name) for path in matches)}")
        else:
            problems.append(f"missing {name!r}")
    if problems:
        fail("; ".join(problems), StemNamingMismatch)
    if len({identities[path] for path in selected.values()}) != len(stems):
        fail("duplicate stems refer to the same file")

    return rename_stems(selected, output)


class SeparationProvider(Protocol):
    """Produce trusted logical stems, or safe actual outputs with a result warning."""

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
