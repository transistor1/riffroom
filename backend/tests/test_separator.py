import logging
from types import SimpleNamespace

import pytest
from riffroom.models import CURATED_MODELS
from riffroom.providers.mlx import MlxAudioSeparatorProvider
from riffroom.separator import TRUSTED_MODEL_FILENAMES, LocalSeparator


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield from self._chunks


def separator():
    instance = LocalSeparator.__new__(LocalSeparator)
    instance.logger = logging.getLogger("test")
    return instance


def test_download_ignores_content_length_for_encoded_response(tmp_path, monkeypatch):
    target = tmp_path / "models.json"
    response = FakeResponse(
        [b"decoded", b"-content"],
        headers={"Content-Length": "5", "Content-Encoding": "gzip"},
    )

    def fake_get(*args, **kwargs):
        assert kwargs["headers"] == {"Accept-Encoding": "identity"}
        return response

    monkeypatch.setattr("riffroom.separator.requests.get", fake_get)
    separator().download_file_if_not_exists("https://example.test/models.json", target)

    assert target.read_bytes() == b"decoded-content"
    assert not target.with_name(target.name + ".part").exists()


def test_download_retries_incomplete_identity_response(tmp_path, monkeypatch):
    target = tmp_path / "model.bin"
    responses = iter(
        [
            FakeResponse([b"short"], headers={"Content-Length": "10"}),
            FakeResponse([b"complete"], headers={"Content-Length": "8"}),
        ]
    )
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr("riffroom.separator.requests.get", fake_get)
    separator().download_file_if_not_exists("https://example.test/model.bin", target)

    assert len(calls) == 2
    assert target.read_bytes() == b"complete"
    assert not target.with_name(target.name + ".part").exists()


@pytest.mark.parametrize(
    ("filename", "config", "base", "query", "friendly_name"),
    [
        (
            "becruily_guitar.ckpt",
            "config_guitar_becruily.yaml",
            "https://huggingface.co/becruily/mel-band-roformer-guitar/resolve/main",
            "",
            "Mel-Band RoFormer Guitar by becruily",
        ),
        (
            "bs_mega_53stem_guitar_mvsep.ckpt",
            "bs_mega_53stem_guitar_mvsep_config.yaml",
            "https://huggingface.co/noblebarkrr/BS-Roformer-MVSep-Mega-53-stems/resolve/main/v1",
            "?download=true",
            "BS-RoFormer MVSep Mega 53 Guitar",
        ),
        (
            "bs_mega_53stem_electric-guitar_mvsep.ckpt",
            "bs_mega_53stem_electric-guitar_mvsep_config.yaml",
            "https://huggingface.co/noblebarkrr/BS-Roformer-MVSep-Mega-53-stems/resolve/main/v1",
            "?download=true",
            "BS-RoFormer MVSep Mega 53 Electric Guitar",
        ),
        (
            "bs_mega_53stem_acoustic-guitar_mvsep.ckpt",
            "bs_mega_53stem_acoustic-guitar_mvsep_config.yaml",
            "https://huggingface.co/noblebarkrr/BS-Roformer-MVSep-Mega-53-stems/resolve/main/v1",
            "?download=true",
            "BS-RoFormer MVSep Mega 53 Acoustic Guitar",
        ),
    ],
)
def test_custom_roformer_download_contract(tmp_path, monkeypatch, filename, config, base, query, friendly_name):
    instance = separator()
    instance.model_file_dir = str(tmp_path)
    instance.model_is_uvr_vip = True
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse([b"model fixture"])

    monkeypatch.setattr("riffroom.separator.requests.get", fake_get)
    assert filename in TRUSTED_MODEL_FILENAMES
    expected = (filename, "MDXC", friendly_name, str(tmp_path / filename), config)
    assert instance.download_model_files(filename) == expected
    assert instance.model_friendly_name == friendly_name
    assert instance.model_is_uvr_vip is False
    assert calls == [f"{base}/{filename}{query}", f"{base}/{config}{query}"]
    for name in (filename, config):
        assert (tmp_path / name).read_bytes() == b"model fixture"
        assert not (tmp_path / (name + ".part")).exists()
    assert instance.download_model_files(filename) == expected
    assert len(calls) == 2


def test_registry_downloads_still_delegate_to_upstream(monkeypatch):
    instance = separator()
    expected = ("BS-Roformer-SW.ckpt", "MDXC", "upstream", "/cache/model.ckpt", "model.yaml")
    calls = []

    def download(self, filename):
        calls.append((self, filename))
        return expected

    monkeypatch.setattr("riffroom.separator.Separator.download_model_files", download)
    assert instance.download_model_files(expected[0]) == expected
    assert calls == [(instance, expected[0])]


@pytest.mark.parametrize("stem", ["guitar", "electric-guitar", "acoustic-guitar"])
def test_mvsep_custom_output_names_preserve_upstream_stems(tmp_path, monkeypatch, stem):
    profile = CURATED_MODELS[f"mvsep-{stem}"]
    output = tmp_path / "output"
    output.mkdir()
    captured = {}

    class FakeSeparator:
        def __init__(self, **kwargs):
            self.model_instance = SimpleNamespace()

        def load_model(self, filename):
            captured["filename"] = filename

        def separate(self, source, *, custom_output_names):
            captured["names"] = custom_output_names
            for name in custom_output_names.values():
                (output / f"{name}.wav").touch()

    runtime = SimpleNamespace(LocalSeparator=FakeSeparator, configure_demucs_cache=lambda cache: None)
    monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: runtime)
    paths = MlxAudioSeparatorProvider().separate(
        profile, profile.variants[0], tmp_path / "source.wav", output, tmp_path / "cache",
        on_model_loaded=lambda: None,
    )
    assert captured["filename"] == f"bs_mega_53stem_{stem}_mvsep.ckpt"
    assert captured["names"] == {stem: stem, "other": "other"}
    assert paths == {stem: output / f"{stem}.wav", "other": output / "other.wav"}
