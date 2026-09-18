"""One subprocess per job: isolates ML memory and makes cancellation immediate."""

import json
import logging
import os
import sys
from pathlib import Path

from riffroom.audio import validate_stems, waveform, write_float_stem
from riffroom.models import MODELS


def event(message: str):
    print("RIFFROOM:" + json.dumps({"message": message}), flush=True)


def run(source: Path, output: Path, cache: Path, model_id: str):
    from riffroom.separator import LocalSeparator, configure_demucs_cache

    profile = MODELS[model_id]
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    event("Loading model · first use downloads and converts the weights")
    configure_demucs_cache(cache)
    separator = LocalSeparator(
        log_level=logging.INFO,
        model_file_dir=str(cache),
        output_dir=str(output),
        output_format="WAV",
        normalization_threshold=1.0,
        amplification_threshold=0.0,
        save_converted_safetensors=True,
        demucs_params={
            "segment_size": "Default",
            "shifts": 1,
            "overlap": 0.25,
            "segments_enabled": True,
            "batch_size": 1,
            "seed": 42,
        },
        mdxc_params={
            "segment_size": 256,
            "override_model_segment_size": False,
            "batch_size": 1,
            "overlap": 2,
            "pitch_shift": 0,
        },
    )
    separator.load_model(profile.filename)
    separator.model_instance.write_audio = lambda path, samples: write_float_stem(output, path, samples)
    event("Separating instruments on your Mac · this can take several minutes")
    names = {name: name for name in profile.stems}
    separator.separate(str(source), custom_output_names=names)
    paths = {name: output / f"{name}.wav" for name in profile.stems}
    # The library uses case-insensitive stem names but model-dependent filename casing.
    for name, path in paths.items():
        if not path.exists():
            matches = [p for p in output.glob("*.wav") if p.stem.lower() == name]
            if len(matches) == 1:
                matches[0].rename(path)
    validate_stems(paths, source)
    event("Preparing waveforms and playback")
    manifest = [{"name": name, "file": path.name, "peaks": waveform(path)} for name, path in paths.items()]
    (output / "stems.json").write_text(json.dumps(manifest))
    event("Ready to practice")


if __name__ == "__main__":
    # Keep all caches inside the app's data folder, including first-run conversions.
    source, output, cache, model_id = sys.argv[1:]
    os.environ.setdefault("TORCH_HOME", str(Path(cache) / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(cache) / "cache"))
    run(Path(source), Path(output), Path(cache), model_id)
