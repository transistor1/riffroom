"""One subprocess per job: isolates ML memory and makes cancellation immediate."""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from riffroom.audio import validate_stems, waveform
from riffroom.models import MODELS, variant_for_provider
from riffroom.providers import PROVIDERS, SeparationProvider, get_provider
from riffroom.providers.base import StemPaths, validate_output_directory, validate_selected_paths


def event(message: str):
    print("RIFFROOM:" + json.dumps({"message": message}), flush=True)


def run(
    source: Path,
    output: Path,
    cache: Path,
    model_id: str,
    provider_id: str,
    provider_registry: Mapping[str, SeparationProvider] = PROVIDERS,
):
    profile = MODELS[model_id]
    variant = variant_for_provider(profile, provider_id)
    output.mkdir(parents=True, exist_ok=True)
    validate_output_directory(output)
    # Jobs creates a new UUID directory and opens its log before spawning us.
    # Refuse reuse rather than accepting files left by an earlier invocation.
    if any(path.name != "job.log" for path in output.iterdir()):
        raise ValueError("Separation requires a fresh run output directory.")
    cache.mkdir(parents=True, exist_ok=True)
    event("Loading model · first use downloads and converts the weights")
    provider = get_provider(variant.provider_id, provider_registry)
    produced = provider.separate(
        profile,
        variant,
        source,
        output,
        cache,
        on_model_loaded=lambda: event("Separating instruments · this can take several minutes"),
    )
    warning = produced.output_warning if isinstance(produced, StemPaths) else None
    if warning:
        paths = dict(produced)
    else:
        try:
            paths = {name: produced[name] for name in profile.stems}
        except KeyError as exc:
            raise ValueError(f"The provider did not produce the expected {exc.args[0]} stem.") from None
    validate_selected_paths(paths, output)
    validate_stems(paths, source)
    event("Preparing waveforms and playback")
    manifest = [{"name": name, "file": path.name, "peaks": waveform(path)} for name, path in paths.items()]
    payload = {"stems": manifest, "output_warning": warning} if warning else manifest
    (output / "stems.json").write_text(json.dumps(payload))
    if warning:
        print("Separation output warning: " + json.dumps(warning), flush=True)
    event("Ready to practice")


if __name__ == "__main__":
    # Keep all caches inside the app's data folder, including first-run conversions.
    source, output, cache, model_id, provider_id = sys.argv[1:]
    os.environ.setdefault("TORCH_HOME", str(Path(cache) / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(cache) / "cache"))
    run(Path(source), Path(output), Path(cache), model_id, provider_id)
