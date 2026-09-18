"""Curated profiles. Add models here without changing the API or mixer."""

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
        ),
    )
}


def catalog():
    return [asdict(model) for model in MODELS.values()]
