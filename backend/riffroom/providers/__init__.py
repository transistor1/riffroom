"""Explicit registry for trusted separation providers."""

from collections.abc import Mapping

from riffroom.providers.base import SeparationProvider
from riffroom.providers.mlx import MlxAudioSeparatorProvider

PROVIDERS: dict[str, SeparationProvider] = {
    "mlx-audio-separator": MlxAudioSeparatorProvider(),
}


def get_provider(
    provider_id: str,
    registry: Mapping[str, SeparationProvider] = PROVIDERS,
) -> SeparationProvider:
    """Resolve a provider only from the server-owned registry."""
    try:
        return registry[provider_id]
    except KeyError:
        raise ValueError(f"Unknown separation provider: {provider_id}") from None


__all__ = ["PROVIDERS", "SeparationProvider", "get_provider"]
