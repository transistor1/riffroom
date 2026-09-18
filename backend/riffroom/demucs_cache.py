"""Restore MLX-native Demucs caches without applying Torch key conversions twice.

mlx-audio-separator 0.1.7 saves flattened MLX parameter names, then reloads them
through a mapper intended for Torch names. Nested conv/Sequential weights are
silently skipped. The model appears to load but retains random parameters.
Keep this repair scoped to the pinned adapter and require an exact key/shape
match, rather than allowing partial restoration.
"""

from pathlib import Path


def restore_cached_demucs_weights(model, checkpoint: Path) -> int:
    import mlx.core as mx

    weights = mx.load(str(checkpoint))
    if not isinstance(weights, dict):
        raise ValueError("Demucs cache must contain named parameter tensors.")
    children = getattr(model, "models", None)
    if children is None:
        model.load_weights(list(weights.items()), strict=True)
        return len(weights)

    restored = 0
    expected_prefixes = tuple(f"model_{i}." for i in range(len(children)))
    if any(not key.startswith(expected_prefixes) for key in weights):
        raise ValueError("Demucs cache contains weights for an unexpected model.")
    for i, child in enumerate(children):
        prefix = f"model_{i}."
        state = [
            (key.removeprefix(prefix), value) for key, value in weights.items() if key.startswith(prefix)
        ]
        # These are already MLX names/layouts. No convolution wrapper stripping,
        # Sequential path rewrites, or Torch-to-MLX transposition belongs here.
        child.load_weights(state, strict=True)
        restored += len(state)
    return restored
