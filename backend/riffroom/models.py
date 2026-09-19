"""Curated model metadata, kept separate from inference runtime behavior."""

import platform
from dataclasses import asdict, dataclass


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
        ),
    )
}


def catalog():
    platform_key = current_platform_key()
    platform_name = PLATFORM_NAMES.get(platform_key, platform_key)
    result = []
    for model in MODELS.values():
        item = asdict(model)
        compatible = platform_key in model.supported_platforms
        item["compatibility"] = {
            "platform_key": platform_key,
            "platform_name": platform_name,
            "compatible": compatible,
            "label": f"{'Compatible' if compatible else 'Unavailable'} · {platform_name}",
        }
        result.append(item)
    return result
