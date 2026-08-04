from __future__ import annotations

import hashlib

import pytest

from metro_alignment.datasets import download as download_module


class FakeResponse:
    def __init__(self, body: bytes, *, status: int, headers: dict[str, str]) -> None:
        self.body = body
        self.status_code = status
        self.headers = headers
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self.body

    def close(self) -> None:
        self.closed = True


def _md5(value: bytes) -> str:
    return hashlib.md5(value).hexdigest()


def test_download_resumes_a_valid_206(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "data.bin"
    destination.with_suffix(".bin.partial").write_bytes(b"abc")
    calls = []

    def fake_get(url, *, headers, stream, timeout):
        calls.append((url, headers, stream, timeout))
        return FakeResponse(
            b"def", status=206, headers={"Content-Length": "3", "Content-Range": "bytes 3-5/6"}
        )

    monkeypatch.setattr(download_module.requests, "get", fake_get)
    result = download_module.download_file(
        dataset_id="fixture",
        url="https://example.test/data",
        destination=destination,
        expected_md5=_md5(b"abcdef"),
    )
    assert destination.read_bytes() == b"abcdef"
    assert calls[0][1] == {"Range": "bytes=3-"}
    assert result.downloaded_bytes == 3


def test_download_restarts_when_range_is_ignored(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "data.bin"
    destination.with_suffix(".bin.partial").write_bytes(b"abc")
    response = FakeResponse(b"abcdef", status=200, headers={"Content-Length": "6"})
    headers_seen = []

    def fake_get(url, *, headers, stream, timeout):
        del url, stream, timeout
        headers_seen.append(headers)
        return response

    monkeypatch.setattr(download_module.requests, "get", fake_get)
    download_module.download_file(
        dataset_id="fixture",
        url="https://example.test/data",
        destination=destination,
        expected_md5=_md5(b"abcdef"),
    )
    assert destination.read_bytes() == b"abcdef"
    assert headers_seen == [{"Range": "bytes=3-"}]


def test_download_preserves_partial_when_416_restart_request_fails(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "data.bin"
    partial = destination.with_suffix(".bin.partial")
    partial.write_bytes(b"abc")
    calls = 0

    def fake_get(url, *, headers, stream, timeout):
        nonlocal calls
        del url, headers, stream, timeout
        calls += 1
        if calls == 1:
            return FakeResponse(b"", status=416, headers={})
        raise OSError("network disconnected")

    monkeypatch.setattr(download_module.requests, "get", fake_get)
    with pytest.raises(OSError, match="disconnected"):
        download_module.download_file(
            dataset_id="fixture",
            url="https://example.test/data",
            destination=destination,
            expected_md5=_md5(b"abcdef"),
        )
    assert partial.read_bytes() == b"abc"


def test_download_replaces_partial_after_successful_416_restart(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "data.bin"
    partial = destination.with_suffix(".bin.partial")
    partial.write_bytes(b"stale")
    responses = iter(
        [
            FakeResponse(b"", status=416, headers={}),
            FakeResponse(b"abcdef", status=200, headers={"Content-Length": "6"}),
        ]
    )

    monkeypatch.setattr(
        download_module.requests,
        "get",
        lambda *args, **kwargs: next(responses),
    )
    download_module.download_file(
        dataset_id="fixture",
        url="https://example.test/data",
        destination=destination,
        expected_md5=_md5(b"abcdef"),
    )
    assert destination.read_bytes() == b"abcdef"
    assert not partial.exists()


def test_download_skips_verified_file(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "data.bin"
    destination.write_bytes(b"abcdef")
    monkeypatch.setattr(
        download_module.requests,
        "get",
        lambda *args, **kwargs: pytest.fail("network must not be called"),
    )
    result = download_module.download_file(
        dataset_id="fixture",
        url="https://example.test/data",
        destination=destination,
        expected_md5=_md5(b"abcdef"),
    )
    assert result.skipped is True
    assert result.downloaded_bytes == 0
