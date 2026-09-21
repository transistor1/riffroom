from dataclasses import replace

import pytest
from riffroom.models import (
    CURATED_MODELS,
    MLX_PROVIDER,
    MODELS,
    PORTABLE_PILOT_FILENAME,
    PORTABLE_PROVIDER,
    ExecutionVariant,
    catalog,
    resolve_model_variant,
    variant_for_provider,
)


def pilot_model():
    return next(model for model in MODELS.values() if model.filename == PORTABLE_PILOT_FILENAME)


def availability(**overrides):
    runtimes = {MLX_PROVIDER: False, PORTABLE_PROVIDER: False, **overrides}
    return lambda provider_id: runtimes.get(provider_id, False)


def test_single_variant_resolution_keeps_existing_models_on_mlx():
    model = CURATED_MODELS["demucs-6"]

    selected = resolve_model_variant(
        model,
        availability(**{MLX_PROVIDER: True}),
        platform_key="macos-arm64",
    )

    assert len(model.variants) == 1
    assert selected == model.variants[0]
    assert selected.provider_id == MLX_PROVIDER
    assert selected.validated is True
    assert model.cache_cleanup_supported is True
    assert model.cache_files


def test_pilot_resolves_only_to_validated_portable_provider():
    selected = resolve_model_variant(
        pilot_model(),
        availability(**{MLX_PROVIDER: True, PORTABLE_PROVIDER: True}),
        platform_key="macos-arm64",
    )

    assert selected is not None
    assert selected.provider_id == PORTABLE_PROVIDER
    assert selected.validated is True
    assert [variant.provider_id for variant in pilot_model().variants] == [PORTABLE_PROVIDER]


def test_resolution_skips_an_available_but_unvalidated_variant():
    model = replace(
        pilot_model(),
        variants=(
            ExecutionVariant(MLX_PROVIDER, PORTABLE_PILOT_FILENAME, ("macos-arm64",), False),
            ExecutionVariant(PORTABLE_PROVIDER, PORTABLE_PILOT_FILENAME, ("macos-arm64",), True),
        ),
    )
    selected = resolve_model_variant(
        model,
        availability(**{MLX_PROVIDER: True, PORTABLE_PROVIDER: True}),
        platform_key="macos-arm64",
    )

    assert selected is not None
    assert selected.provider_id == PORTABLE_PROVIDER
    with pytest.raises(ValueError, match="not a trusted variant"):
        variant_for_provider(model, MLX_PROVIDER)


def test_portable_pilot_is_runtime_required_when_provider_is_unavailable(tmp_path):
    model = pilot_model()
    models = catalog(
        tmp_path,
        provider_availability={MLX_PROVIDER: False, PORTABLE_PROVIDER: False},
        platform_key="macos-arm64",
    )
    rows = [item for item in models if item["id"] == model.id]

    assert (
        resolve_model_variant(
            model,
            availability(),
            platform_key="macos-arm64",
        )
        is None
    )
    assert len(rows) == 1
    assert rows[0]["provider"] is None
    assert rows[0]["provider_options"] == [PORTABLE_PROVIDER]
    assert rows[0]["compatibility"] == {
        "platform_key": "macos-arm64",
        "platform_name": "macOS (Apple Silicon)",
        "platform_supported": True,
        "runtime_available": False,
        "compatible": False,
        "label": "Runtime required · macOS (Apple Silicon)",
    }


def test_portable_pilot_uses_conservative_cache_semantics(tmp_path):
    model = pilot_model()
    row = next(
        item
        for item in catalog(
            tmp_path,
            provider_availability={MLX_PROVIDER: True, PORTABLE_PROVIDER: True},
            platform_key="macos-arm64",
        )
        if item["id"] == model.id
    )

    assert model.cache_cleanup_supported is False
    assert model.cache_files == ()
    assert row["prepared"] is False
    assert row["cache_cleanup_supported"] is False
