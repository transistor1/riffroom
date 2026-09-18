"""Compatibility adapter for mlx-audio-separator 0.1.7.

Keep upstream inference untouched, but use atomic downloads, app-local Demucs
caches, and float WAV writing without per-stem peak normalization.
"""

import os
from pathlib import Path

import requests
from mlx_audio_separator import Separator


class LocalSeparator(Separator):
    def load_model(self, model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt"):
        super().load_model(model_filename)
        if self.model_type == "Demucs":
            from riffroom.demucs_cache import restore_cached_demucs_weights

            model = self.model_instance._demucs_separator.model
            checkpoint = Path(self.model_file_dir) / "demucs-mlx" / f"{Path(model_filename).stem}.safetensors"
            count = restore_cached_demucs_weights(model, checkpoint)
            self.logger.info("Restored all %s cached Demucs tensors using strict MLX names", count)

    def download_file_if_not_exists(self, url, output_path):
        target = Path(output_path)
        if target.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        last_error = None
        for attempt in range(3):
            temporary.unlink(missing_ok=True)
            try:
                # Ask for identity encoding so Content-Length describes the bytes
                # written to disk. Some hosts still compress anyway, so only use
                # Content-Length as an integrity check when the response is
                # actually unencoded.
                with requests.get(
                    url,
                    stream=True,
                    timeout=(30, 120),
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as stream:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            stream.write(chunk)
                            size += len(chunk)
                    expected = response.headers.get("Content-Length")
                    encoding = response.headers.get("Content-Encoding", "identity").lower()
                    if expected and encoding in {"", "identity"} and size != int(expected):
                        raise ValueError(
                            f"Model download was incomplete ({size} of {expected} bytes)."
                        )
                    if size == 0:
                        raise ValueError("Model download was empty.")
                    temporary.replace(target)
                    return
            except (requests.RequestException, OSError, ValueError) as exc:
                last_error = exc
                temporary.unlink(missing_ok=True)
                if attempt < 2:
                    self.logger.warning(
                        "Model download failed for %s (attempt %s/3): %s. Retrying.",
                        target.name,
                        attempt + 1,
                        exc,
                    )
        raise RuntimeError(
            f"Could not download {target.name} after 3 attempts: {last_error}"
        ) from last_error

    def download_model_files(self, model_filename):
        if model_filename == "becruily_guitar.ckpt":
            root = Path(self.model_file_dir)
            base = "https://huggingface.co/becruily/mel-band-roformer-guitar/resolve/main"
            config = "config_guitar_becruily.yaml"
            self.download_file_if_not_exists(f"{base}/{model_filename}", root / model_filename)
            self.download_file_if_not_exists(f"{base}/{config}", root / config)
            self.model_is_uvr_vip = False
            self.model_friendly_name = "Mel-Band RoFormer Guitar by becruily"
            return model_filename, "MDXC", self.model_friendly_name, str(root / model_filename), config
        return super().download_model_files(model_filename)


def configure_demucs_cache(cache: Path):
    from mlx_audio_separator.demucs_mlx import model_converter

    directory = cache / "demucs-mlx"
    directory.mkdir(parents=True, exist_ok=True)
    # Upstream hardcodes Path.home(); confine this worker's conversion cache.
    model_converter.get_mlx_cache_dir = lambda: directory
    os.environ.setdefault("TORCH_HOME", str(cache / "torch"))
