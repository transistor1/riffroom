"""Real cached-weight regression; opt in on an Apple Silicon host with weights.

RIFFROOM_MLX_TESTS=1 .env/bin/pytest backend/tests/test_demucs_cache.py -q
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RIFFROOM_MLX_TESTS") != "1", reason="Needs MLX GPU and cached weights"
)
CACHE = Path(__file__).resolve().parents[2] / "data" / "models" / "demucs-mlx"


@pytest.mark.parametrize("name", ["htdemucs_6s", "htdemucs_ft"])
def test_every_cached_tensor_is_restored_and_missing_weights_fail(name, tmp_path):
    import mlx.core as mx
    from mlx.utils import tree_flatten
    from mlx_audio_separator.demucs_mlx.mlx_convert import load_mlx_model_from_safetensors
    from riffroom.demucs_cache import restore_cached_demucs_weights

    checkpoint = CACHE / f"{name}.safetensors"
    if not checkpoint.exists():
        pytest.skip(f"Missing {checkpoint}")
    model = load_mlx_model_from_safetensors(name, cache_dir=str(CACHE))
    weights = mx.load(str(checkpoint))
    assert restore_cached_demucs_weights(model, checkpoint) == len(weights)
    for index, child in enumerate(model.models):
        for key, value in tree_flatten(child.parameters()):
            assert mx.array_equal(value, weights[f"model_{index}.{key}"]).item(), key
    incomplete = dict(weights)
    incomplete.pop(next(iter(incomplete)))
    broken = tmp_path / "incomplete.safetensors"
    mx.save_safetensors(str(broken), incomplete)
    with pytest.raises(ValueError):
        restore_cached_demucs_weights(model, broken)
