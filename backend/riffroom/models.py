"""Curated model metadata, kept separate from inference runtime behavior."""

import platform
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


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
MODELS = {
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
        "cache_cleanup_supported": True,
    }


def clear_model_cache(model: ModelProfile, cache_root: Path) -> None:
    """Delete only the model's declared files and their atomic-download remnants."""
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
    for model in MODELS.values():
        item = asdict(model)
        item.pop("cache_files")
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
