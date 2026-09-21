from dataclasses import replace

import pytest
from riffroom.models import (
    COMMUNITY_MODELS,
    CURATED_MODELS,
    MLX_PROVIDER,
    MODELS,
    PORTABLE_DRUMSEP_FILENAME,
    PORTABLE_KARAOKE_FILENAME,
    PORTABLE_PILOT_FILENAME,
    PORTABLE_PROVIDER,
    VALIDATED_PORTABLE_VARIANTS,
    ExecutionVariant,
    catalog,
    community_model_id,
    resolve_model_variant,
    variant_for_provider,
)

PORTABLE_FILENAMES = (
    PORTABLE_PILOT_FILENAME,
    PORTABLE_DRUMSEP_FILENAME,
    PORTABLE_KARAOKE_FILENAME,
)
NEW_PORTABLE_FILENAMES = (PORTABLE_DRUMSEP_FILENAME, PORTABLE_KARAOKE_FILENAME)


def portable_model(filename=PORTABLE_PILOT_FILENAME):
    return MODELS[community_model_id(filename)]


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


def test_validated_portable_allowlist_is_explicit_and_portable_only():
    assert tuple(VALIDATED_PORTABLE_VARIANTS) == PORTABLE_FILENAMES
    assert all(
        variant == ExecutionVariant(PORTABLE_PROVIDER, filename, ("macos-arm64",), True)
        for filename, variant in VALIDATED_PORTABLE_VARIANTS.items()
    )


@pytest.mark.parametrize("filename", PORTABLE_FILENAMES)
def test_portable_models_resolve_only_to_validated_portable_provider(filename):
    model = portable_model(filename)
    selected = resolve_model_variant(
        model,
        availability(**{MLX_PROVIDER: True, PORTABLE_PROVIDER: True}),
        platform_key="macos-arm64",
    )

    assert selected is not None
    assert selected.provider_id == PORTABLE_PROVIDER
    assert selected.validated is True
    assert [variant.provider_id for variant in model.variants] == [PORTABLE_PROVIDER]


def test_resolution_skips_an_available_but_unvalidated_variant():
    model = replace(
        portable_model(),
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


@pytest.mark.parametrize("filename", NEW_PORTABLE_FILENAMES)
def test_new_portable_models_are_single_rows_and_runtime_required_without_provider(tmp_path, filename):
    model = portable_model(filename)
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


@pytest.mark.parametrize("filename", PORTABLE_FILENAMES)
def test_portable_models_use_conservative_cache_semantics(tmp_path, filename):
    model = portable_model(filename)
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


def test_new_portable_models_keep_trusted_stems():
    assert portable_model(PORTABLE_DRUMSEP_FILENAME).stems == (
        "kick",
        "snare",
        "toms",
        "hh",
        "ride",
        "crash",
    )
    assert portable_model(PORTABLE_KARAOKE_FILENAME).stems == ("vocals", "instrumental")


def test_unrelated_community_model_does_not_gain_portable_variant():
    unrelated = next(
        model for model in COMMUNITY_MODELS.values() if model.filename not in VALIDATED_PORTABLE_VARIANTS
    )

    assert all(variant.provider_id != PORTABLE_PROVIDER for variant in unrelated.variants)
