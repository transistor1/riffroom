"""Trusted model metadata, kept separate from inference runtime behavior."""

import hashlib
import json
import platform
import re
import stat
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    id: str
    name: str
    filename: str
    stems: tuple[str, ...]
    description: str
    badge: str
    license: str
    source: str
    provider: str
    architecture: str
    supported_platforms: tuple[str, ...]
    terms_status: str
    cache_files: tuple[str, ...]
    curated: bool = True
    catalog_origin: str = "Riffroom curated catalog"
    catalog_group: str = "curated"
    cache_cleanup_supported: bool = True


PLATFORM_NAMES = {
    "macos-arm64": "macOS (Apple Silicon)",
    "macos-x86_64": "macOS (Intel)",
    "windows-arm64": "Windows (ARM64)",
    "windows-x86_64": "Windows (x86-64)",
    "linux-arm64": "Linux (ARM64)",
    "linux-x86_64": "Linux (x86-64)",
}


def current_platform_key() -> str:
    """Return a stable catalog key for the host operating system and CPU."""
    system = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    return f"{system}-{machine}"


SIX_STEMS = ("guitar", "vocals", "drums", "bass", "piano", "other")
CURATED_MODELS = {
    model.id: model
    for model in (
        ModelProfile(
            "demucs-6",
            "Demucs · 6 stems",
            "htdemucs_6s.yaml",
            SIX_STEMS,
            "A practical starting point for guitar practice. Separates guitar, vocals, drums, bass, piano and other instruments. Piano separation is experimental.",
            "Start here",
            "MIT",
            "https://github.com/facebookresearch/demucs",
            "mlx-audio-separator",
            "Demucs",
            ("macos-arm64",),
            "open",
            (
                "htdemucs_6s.yaml",
                "5c90dfd2-34c22ccb.th",
                "demucs-mlx/htdemucs_6s.safetensors",
                "demucs-mlx/htdemucs_6s_config.json",
            ),
        ),
        ModelProfile(
            "roformer-6",
            "RoFormer · 6 stems",
            "BS-Roformer-SW.ckpt",
            SIX_STEMS,
            "An alternative six-stem model worth comparing on difficult guitar parts. Uses more memory and may take longer. Community weights have no clear redistribution license.",
            "Compare quality",
            "Community weights; redistribution terms unverified",
            "https://github.com/ssmall256/mlx-audio-separator",
            "mlx-audio-separator",
            "RoFormer",
            ("macos-arm64",),
            "unverified",
            ("BS-Roformer-SW.ckpt", "BS-Roformer-SW.yaml"),
        ),
        ModelProfile(
            "guitar-focus",
            "RoFormer · guitar focus",
            "becruily_guitar.ckpt",
            ("guitar", "other"),
            "A specialist guitar extractor: all guitars plus the rest of the band. Compare it when six-stem guitar extraction has too much bleed. Weights are for non-commercial use.",
            "Guitar specialist",
            "Author permits non-commercial use",
            "https://huggingface.co/becruily/mel-band-roformer-guitar",
            "mlx-audio-separator",
            "RoFormer",
            ("macos-arm64",),
            "non-commercial",
            ("becruily_guitar.ckpt", "config_guitar_becruily.yaml"),
        ),
        ModelProfile(
            "demucs-ft",
            "Demucs · detailed 4 stems",
            "htdemucs_ft.yaml",
            ("vocals", "drums", "bass", "other"),
            "Fine-tuned four-model ensemble for drums, bass and vocals. Guitar stays in Other. Expect a longer processing time.",
            "Drums & bass",
            "MIT",
            "https://github.com/facebookresearch/demucs",
            "mlx-audio-separator",
            "Demucs",
            ("macos-arm64",),
            "open",
            (
                "htdemucs_ft.yaml",
                "f7e0c4bc-ba3fe64a.th",
                "d12395a8-e57c48e6.th",
                "92cfc3b6-ef3bcb9c.th",
                "04573f0d-f3cf25b2.th",
                "demucs-mlx/htdemucs_ft.safetensors",
                "demucs-mlx/htdemucs_ft_config.json",
            ),
        ),
    )
}

COMMUNITY_ORIGIN = "mlx-audio-separator 0.1.7 bundled models.json + models-scores.json"
RUNTIME_SOURCE = "https://github.com/ssmall256/mlx-audio-separator"
COMMUNITY_ARCHITECTURES = {
    "vr_download_list": "VR",
    "mdx_download_list": "MDX",
    "mdx23c_download_list": "MDXC",
    "roformer_download_list": "RoFormer",
}
COMMUNITY_CHECKPOINT_SUFFIXES = {
    "vr_download_list": {".pth"},
    "mdx_download_list": {".onnx"},
    "mdx23c_download_list": {".ckpt"},
    "roformer_download_list": {".ckpt"},
}
SAFE_STEM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")


def community_model_id(filename: str) -> str:
    """Derive a stable ID without exposing a filename as a client-selectable ID."""
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    return f"community-{digest}"


def _trusted_filename(value: Any, suffixes: set[str]) -> str | None:
    """Accept only registry-owned basenames, never URLs or filesystem paths."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return None
    relative = PurePosixPath(value)
    if (
        relative.name != value
        or relative.is_absolute()
        or value in {".", ".."}
        or relative.suffix.lower() not in suffixes
    ):
        return None
    return value


def community_profiles_from_metadata(
    model_registry: dict[str, Any], model_scores: dict[str, Any]
) -> tuple[ModelProfile, ...]:
    """Build runnable profiles only where bundled metadata explicitly declares stems."""
    candidates: list[dict[str, Any]] = []
    cache_owners: dict[str, int] = {}
    for group, architecture in COMMUNITY_ARCHITECTURES.items():
        entries = model_registry.get(group, {})
        if not isinstance(entries, dict):
            continue
        for friendly_name, registry_value in entries.items():
            if not isinstance(friendly_name, str) or not friendly_name:
                continue
            if isinstance(registry_value, str):
                filename = _trusted_filename(registry_value, COMMUNITY_CHECKPOINT_SUFFIXES[group])
                cache_files = (filename,) if filename else ()
            elif isinstance(registry_value, dict) and len(registry_value) == 1:
                raw_filename, raw_config = next(iter(registry_value.items()))
                filename = _trusted_filename(raw_filename, COMMUNITY_CHECKPOINT_SUFFIXES[group])
                config = _trusted_filename(raw_config, {".yaml", ".yml"})
                cache_files = (filename, config) if filename and config else ()
            else:
                continue
            if filename is None or not cache_files:
                continue
            for cache_file in cache_files:
                cache_owners[cache_file] = cache_owners.get(cache_file, 0) + 1
            score_entry = model_scores.get(filename, {})
            raw_stems = score_entry.get("stems") if isinstance(score_entry, dict) else None
            if not isinstance(raw_stems, list) or not raw_stems:
                continue
            if not all(
                isinstance(stem, str) and SAFE_STEM_NAME.fullmatch(stem.strip())
                for stem in raw_stems
            ):
                continue
            candidates.append(
                {
                    "name": friendly_name,
                    "filename": filename,
                    "stems": tuple(stem.strip() for stem in raw_stems),
                    "architecture": architecture,
                    "cache_files": cache_files,
                }
            )

    # One trusted checkpoint gets one ID even if a future registry repeats it under another heading.
    unique: dict[str, dict[str, Any]] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item["name"].casefold(),
            item["filename"].casefold(),
            item["architecture"],
        ),
    ):
        unique.setdefault(candidate["filename"], candidate)

    profiles = []
    for candidate in unique.values():
        cache_files = candidate["cache_files"]
        profiles.append(
            ModelProfile(
                id=community_model_id(candidate["filename"]),
                name=candidate["name"],
                filename=candidate["filename"],
                stems=candidate["stems"],
                description=(
                    "A trusted community checkpoint exposed by the pinned local runtime. "
                    "Review its results and checkpoint terms before relying on it."
                ),
                badge="Community",
                license="Checkpoint terms unverified; the runtime code license does not cover these weights.",
                source=RUNTIME_SOURCE,
                provider="mlx-audio-separator",
                architecture=candidate["architecture"],
                supported_platforms=("macos-arm64",),
                terms_status="unverified",
                cache_files=cache_files,
                curated=False,
                catalog_origin=COMMUNITY_ORIGIN,
                catalog_group="community",
                cache_cleanup_supported=all(cache_owners[item] == 1 for item in cache_files),
            )
        )
    return tuple(profiles)


def _load_bundled_community_metadata() -> tuple[dict[str, Any], dict[str, Any]]:
    package = resources.files("mlx_audio_separator")
    try:
        registry = json.loads(package.joinpath("models.json").read_text(encoding="utf-8"))
        scores = json.loads(package.joinpath("models-scores.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return {}, {}
    return registry, scores


_COMMUNITY_REGISTRY, _COMMUNITY_SCORES = _load_bundled_community_metadata()
COMMUNITY_MODELS = {
    profile.id: profile
    for profile in community_profiles_from_metadata(_COMMUNITY_REGISTRY, _COMMUNITY_SCORES)
    if profile.id not in CURATED_MODELS
}
MODELS = {**CURATED_MODELS, **COMMUNITY_MODELS}


def filter_models(
    *, catalog_group: str | None = None, architecture: str | None = None, query: str = ""
) -> tuple[ModelProfile, ...]:
    """Return the catalog in stable UI order with optional catalog filters."""
    community = sorted(
        COMMUNITY_MODELS.values(), key=lambda model: (model.name.casefold(), model.filename.casefold())
    )
    ordered = (*CURATED_MODELS.values(), *community)
    needle = query.casefold().strip()
    return tuple(
        model
        for model in ordered
        if (catalog_group is None or model.catalog_group == catalog_group)
        and (architecture is None or model.architecture == architecture)
        and (
            not needle
            or needle in model.name.casefold()
            or needle in model.filename.casefold()
            or any(needle in stem.casefold() for stem in model.stems)
        )
    )


def _cache_paths(model: ModelProfile, cache_root: Path) -> tuple[Path, ...]:
    """Resolve only trusted, profile-owned paths below the configured model root."""
    root = cache_root.resolve()
    paths = []
    for filename in model.cache_files:
        relative = PurePosixPath(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe cache metadata for {model.id}: {filename}")
        paths.append(root.joinpath(*relative.parts))
    return tuple(paths)


def _inside_cache_root(path: Path, cache_root: Path) -> bool:
    """Reject traversal through an intermediate symlink outside the model root."""
    try:
        path.parent.resolve().relative_to(cache_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def model_cache_state(model: ModelProfile, cache_root: Path) -> dict:
    paths = _cache_paths(model, cache_root)
    occupied_paths = (*paths, *(item.with_name(item.name + ".part") for item in paths))
    sizes = []
    complete = []
    for path in occupied_paths:
        if not _inside_cache_root(path, cache_root):
            continue
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(metadata.st_mode):
            sizes.append(metadata.st_size)
            if path in paths and metadata.st_size > 0:
                complete.append(path)
    prepared = len(complete) == len(paths)
    return {
        "prepared": prepared,
        "cache_bytes": sum(sizes),
        "cache_label": "Prepared" if prepared else "Downloads on first use",
        "cache_cleanup_supported": model.cache_cleanup_supported,
    }


def clear_model_cache(model: ModelProfile, cache_root: Path) -> None:
    """Delete only the model's declared files and their atomic-download remnants."""
    if not model.cache_cleanup_supported:
        raise ValueError(f"Cache cleanup is unavailable for {model.id} because it uses shared files.")
    paths = _cache_paths(model, cache_root)
    for path in (*paths, *(item.with_name(item.name + ".part") for item in paths)):
        if not _inside_cache_root(path, cache_root):
            continue
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            path.unlink()


def catalog(cache_root: Path):
    platform_key = current_platform_key()
    platform_name = PLATFORM_NAMES.get(platform_key, platform_key)
    result = []
    for model in filter_models():
        item = asdict(model)
        item.pop("cache_files")
        item.pop("cache_cleanup_supported")
        compatible = platform_key in model.supported_platforms
        item["compatibility"] = {
            "platform_key": platform_key,
            "platform_name": platform_name,
            "compatible": compatible,
            "label": f"{'Compatible' if compatible else 'Unavailable'} · {platform_name}",
        }
        item.update(model_cache_state(model, cache_root))
        result.append(item)
    return result
