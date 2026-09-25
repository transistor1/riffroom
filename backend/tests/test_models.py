import os
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
from riffroom.models import (
    COMMUNITY_MODELS,
    CURATED_MODELS,
    DEMUCS_6_FILENAME,
    MLX_PROVIDER,
    MODELS,
    PORTABLE_COMMUNITY_MODELS,
    PORTABLE_DRUMSEP_FILENAME,
    PORTABLE_KARAOKE_FILENAME,
    PORTABLE_PILOT_FILENAME,
    PORTABLE_PROVIDER,
    VALIDATED_PORTABLE_VARIANTS,
    ExecutionVariant,
    _community_models_from_metadata,
    catalog,
    clear_model_cache,
    community_model_id,
    model_cache_state,
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


def test_kimberley_vocals_is_a_trusted_curated_profile(tmp_path):
    model = CURATED_MODELS["roformer-vocals"]

    assert MODELS[model.id] is model
    assert model.name == "RoFormer · Kimberley vocals"
    assert model.stems == ("vocals", "instrumental")
    assert model.architecture == "RoFormer"
    assert model.source == "https://huggingface.co/KimberleyJSN/melbandroformer"
    assert (model.license, model.terms_status) == ("MIT", "open")
    assert model.variants == (
        ExecutionVariant(MLX_PROVIDER, "vocals_mel_band_roformer.ckpt", ("macos-arm64",), True),
    )
    assert model.filename not in VALIDATED_PORTABLE_VARIANTS
    rows = [row for row in catalog(tmp_path, platform_key="macos-arm64") if row["id"] == model.id]
    assert len(rows) == 1
    assert rows[0]["curated"] is True
    assert rows[0]["catalog_group"] == "curated"
    assert rows[0]["catalog_origin"] == "Riffroom curated catalog"
    assert rows[0]["filename"] == "vocals_mel_band_roformer.ckpt"
    assert rows[0]["provider_options"] == [MLX_PROVIDER]


@pytest.mark.parametrize(
    ("platform_key", "mlx_available", "compatible"),
    [
        ("macos-arm64", True, True),
        ("macos-arm64", False, False),
        ("macos-x86_64", True, False),
        ("windows-x86_64", True, False),
        ("windows-arm64", True, False),
        ("linux-x86_64", True, False),
        ("linux-arm64", True, False),
    ],
)
def test_kimberley_vocals_requires_mlx_on_apple_silicon(tmp_path, platform_key, mlx_available, compatible):
    model = CURATED_MODELS["roformer-vocals"]
    runtimes = {MLX_PROVIDER: mlx_available, PORTABLE_PROVIDER: True}
    selected = resolve_model_variant(model, availability(**runtimes), platform_key=platform_key)
    assert selected == (model.variants[0] if compatible else None)
    with pytest.raises(ValueError, match="not a trusted variant"):
        variant_for_provider(model, PORTABLE_PROVIDER)
    row = next(
        row
        for row in catalog(tmp_path, provider_availability=runtimes, platform_key=platform_key)
        if row["id"] == model.id
    )
    assert row["provider"] == (MLX_PROVIDER if compatible else None)
    assert row["supported_platforms"] == ["macos-arm64"]
    assert row["compatibility"]["compatible"] is compatible
    assert row["compatibility"]["platform_supported"] is (platform_key == "macos-arm64")


def test_kimberley_vocals_owns_checkpoint_config_and_partial_downloads(tmp_path):
    model = CURATED_MODELS["roformer-vocals"]
    assert model.cache_cleanup_supported is True
    assert model.cache_files == ("vocals_mel_band_roformer.ckpt", "vocals_mel_band_roformer.yaml")
    checkpoint, config = (tmp_path / filename for filename in model.cache_files)
    assert model_cache_state(model, tmp_path)["prepared"] is False
    checkpoint.write_bytes(b"checkpoint fixture")
    assert model_cache_state(model, tmp_path)["prepared"] is False
    config.touch()
    assert model_cache_state(model, tmp_path)["prepared"] is False
    config.write_bytes(b"config fixture")
    partials = [path.with_name(path.name + ".part") for path in (checkpoint, config)]
    for path in partials:
        path.write_bytes(b"partial fixture")
    shared = tmp_path / "download_checks.json"
    shared.write_bytes(b"shared fixture")
    unrelated = tmp_path / "BS-Roformer-SW.ckpt"
    unrelated.write_bytes(b"unrelated fixture")
    state = model_cache_state(model, tmp_path)
    assert state["prepared"] is True
    assert state["cache_bytes"] == sum(path.stat().st_size for path in (checkpoint, config, *partials))

    clear_model_cache(model, tmp_path)
    clear_model_cache(model, tmp_path)

    assert all(not path.exists() for path in (checkpoint, config, *partials))
    assert model_cache_state(model, tmp_path)["prepared"] is False
    assert model_cache_state(model, tmp_path)["cache_bytes"] == 0
    assert shared.read_bytes() == b"shared fixture"
    assert unrelated.read_bytes() == b"unrelated fixture"


def test_demucs_6_prefers_mlx_then_resolves_portable_without_fallback_guessing():
    model = CURATED_MODELS["demucs-6"]

    preferred = resolve_model_variant(
        model,
        availability(**{MLX_PROVIDER: True, PORTABLE_PROVIDER: True}),
        platform_key="macos-arm64",
    )
    portable = resolve_model_variant(
        model,
        availability(**{PORTABLE_PROVIDER: True}),
        platform_key="macos-arm64",
    )
    unavailable = resolve_model_variant(model, availability(), platform_key="macos-arm64")

    assert [variant.provider_id for variant in model.variants] == [MLX_PROVIDER, PORTABLE_PROVIDER]
    assert preferred == model.variants[0]
    assert portable == model.variants[1]
    assert portable.filename == DEMUCS_6_FILENAME
    assert portable == VALIDATED_PORTABLE_VARIANTS[DEMUCS_6_FILENAME]
    assert unavailable is None
    assert model.cache_cleanup_supported is True
    assert model.cache_files


def test_validated_portable_allowlist_is_explicit_and_portable_only():
    assert tuple(VALIDATED_PORTABLE_VARIANTS) == (DEMUCS_6_FILENAME, *PORTABLE_FILENAMES)
    assert all(
        variant == ExecutionVariant(PORTABLE_PROVIDER, filename, ("macos-arm64",), True)
        for filename, variant in VALIDATED_PORTABLE_VARIANTS.items()
    )


def test_portable_profiles_have_stable_server_owned_metadata():
    expected = {
        PORTABLE_PILOT_FILENAME: (
            "community-1d16a41dda1ff0f680e1ffcda8ea3a4d73a1f9b3c484f3e16dc2afef7c34ad48",
            "MDX-Net Model: UVR-MDX-NET Inst HQ 5",
            ("instrumental", "vocals"),
            "MDX",
        ),
        PORTABLE_DRUMSEP_FILENAME: (
            "community-6cbb86284613af448231fa205efc8b89e57de2ad63af9514ad18ce26419c53df",
            "MDX23C Model: MDX23C DrumSep by aufr33-jarredou",
            ("kick", "snare", "toms", "hh", "ride", "crash"),
            "MDXC",
        ),
        PORTABLE_KARAOKE_FILENAME: (
            "community-bfc6a33361639cad7b7e2b01d5a71a312057d6ee026ad573febcb1dc200a5c75",
            "Roformer Model: Mel-Roformer-Karaoke-Aufr33-Viperx",
            ("vocals", "instrumental"),
            "RoFormer",
        ),
    }

    assert len(PORTABLE_COMMUNITY_MODELS) == 3
    for filename, (model_id, name, stems, architecture) in expected.items():
        model = PORTABLE_COMMUNITY_MODELS[model_id]
        assert community_model_id(filename) == model_id
        assert (model.name, model.stems, model.architecture) == (name, stems, architecture)
        assert model.terms_status == "unverified"
        assert model.variants == (VALIDATED_PORTABLE_VARIANTS[filename],)


def test_optional_metadata_is_merged_and_portable_profile_wins():
    registry = {
        "mdx_download_list": {
            "Stale portable name": PORTABLE_PILOT_FILENAME,
            "Additional bundled model": "additional.onnx",
        }
    }
    scores = {
        PORTABLE_PILOT_FILENAME: {"stems": ["wrong"]},
        "additional.onnx": {"stems": ["vocals", "instrumental"]},
    }

    models = _community_models_from_metadata(registry, scores)

    assert len(models) == 4
    portable = models[community_model_id(PORTABLE_PILOT_FILENAME)]
    assert portable == PORTABLE_COMMUNITY_MODELS[portable.id]
    assert portable.name == "MDX-Net Model: UVR-MDX-NET Inst HQ 5"
    assert portable.stems == ("instrumental", "vocals")
    bundled = models[community_model_id("additional.onnx")]
    assert bundled.name == "Additional bundled model"
    assert bundled.variants[0].provider_id == MLX_PROVIDER


def test_installed_bundled_metadata_preserves_broader_27_model_catalog():
    if len(COMMUNITY_MODELS) == len(PORTABLE_COMMUNITY_MODELS):
        pytest.skip("optional MLX community metadata is not installed")

    assert len(COMMUNITY_MODELS) == 27
    assert sum(model.filename in VALIDATED_PORTABLE_VARIANTS for model in COMMUNITY_MODELS.values()) == len(
        PORTABLE_COMMUNITY_MODELS
    )


def test_modules_import_and_catalog_survives_without_optional_mlx_stack(tmp_path):
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path

        blocked = ("mlx_audio_separator", "mlx", "demucs", "torch", "torchaudio")

        class OptionalRuntimeBlocker:
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
                    raise ModuleNotFoundError(f"blocked optional runtime: {fullname}", name=fullname)
                return None

        sys.meta_path.insert(0, OptionalRuntimeBlocker())

        import riffroom.app
        from riffroom.models import (
            COMMUNITY_MODELS,
            CURATED_MODELS,
            MLX_PROVIDER,
            PORTABLE_PROVIDER,
            catalog,
        )
        from riffroom.providers import get_provider
        from riffroom.providers.mlx import MlxRuntimeUnavailableError

        assert "riffroom.separator" not in sys.modules
        assert len(COMMUNITY_MODELS) == 3
        expected = {
            "UVR-MDX-NET-Inst_HQ_5.onnx": (
                "community-1d16a41dda1ff0f680e1ffcda8ea3a4d73a1f9b3c484f3e16dc2afef7c34ad48",
                ("instrumental", "vocals"),
                "MDX",
            ),
            "MDX23C-DrumSep-aufr33-jarredou.ckpt": (
                "community-6cbb86284613af448231fa205efc8b89e57de2ad63af9514ad18ce26419c53df",
                ("kick", "snare", "toms", "hh", "ride", "crash"),
                "MDXC",
            ),
            "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt": (
                "community-bfc6a33361639cad7b7e2b01d5a71a312057d6ee026ad573febcb1dc200a5c75",
                ("vocals", "instrumental"),
                "RoFormer",
            ),
        }
        actual = {model.filename: (model.id, model.stems, model.architecture) for model in COMMUNITY_MODELS.values()}
        assert actual == expected

        provider = get_provider(MLX_PROVIDER)
        assert provider.is_available() is False
        try:
            provider.separate(
                CURATED_MODELS["demucs-6"],
                CURATED_MODELS["demucs-6"].variants[0],
                Path("source.wav"),
                Path("output"),
                Path("cache"),
                on_model_loaded=lambda: None,
            )
        except MlxRuntimeUnavailableError as exc:
            assert "Install this checkout with the 'mlx' optional dependencies" in str(exc)
        else:
            raise AssertionError("unavailable MLX provider did not fail")

        rows = catalog(
            Path("cache"),
            provider_availability={MLX_PROVIDER: False, PORTABLE_PROVIDER: False},
            platform_key="macos-arm64",
        )
        curated = {row["id"]: row for row in rows if row["curated"]}
        assert set(curated) == set(CURATED_MODELS)
        assert all(row["compatibility"]["runtime_available"] is False for row in curated.values())
        assert all(row["compatibility"]["label"].startswith("Runtime required") for row in curated.values())
        """
    )
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])}

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
    models = _community_models_from_metadata(
        {"mdx_download_list": {"Unrelated model": "unrelated.onnx"}},
        {"unrelated.onnx": {"stems": ["vocals", "instrumental"]}},
    )
    unrelated = models[community_model_id("unrelated.onnx")]

    assert all(variant.provider_id != PORTABLE_PROVIDER for variant in unrelated.variants)
