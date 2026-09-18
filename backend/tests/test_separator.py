import logging

from riffroom.separator import LocalSeparator


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
