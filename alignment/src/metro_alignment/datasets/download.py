from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import requests
from tqdm import tqdm

from .registry import get_dataset_spec

LOGGER = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1 << 20


@dataclass(frozen=True)
class DownloadResult:
    dataset_id: str
    file_name: str
    path: Path
    expected_bytes: int
    downloaded_bytes: int
    skipped: bool


def verify_md5(path: Path, expected: str) -> bool:
    if not path.exists():
        return False
    hasher = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(DEFAULT_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest() == expected.lower()


def download_file(
    *,
    dataset_id: str,
    url: str,
    destination: Path,
    expected_md5: str,
    timeout: int = 60,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> DownloadResult:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")

    if destination.exists() and verify_md5(destination, expected_md5):
        LOGGER.info("skip verified file: %s", destination)
        return DownloadResult(
            dataset_id=dataset_id,
            file_name=destination.name,
            path=destination,
            expected_bytes=destination.stat().st_size,
            downloaded_bytes=0,
            skipped=True,
        )

    headers = {}
    if partial.exists():
        partial_size = partial.stat().st_size
        headers["Range"] = f"bytes={partial_size}-"
    else:
        partial_size = 0

    response = requests.get(url, headers=headers, stream=True, timeout=timeout)
    status = response.status_code
    download_target = partial
    progress_offset = partial_size
    mode = "ab" if partial_size > 0 and status == 206 else "wb"
    if partial_size > 0 and status == 206:
        content_range = str(response.headers.get("Content-Range", ""))
        if not content_range.startswith(f"bytes {partial_size}-"):
            response.close()
            raise ValueError(f"invalid Content-Range for resume: {content_range!r}")
    elif partial_size > 0 and status == 200:
        # The server ignored Range but already returned a complete body. Preserve
        # the resumable partial until this replacement has passed length and MD5.
        download_target = destination.with_suffix(destination.suffix + ".restart")
        progress_offset = 0
        mode = "wb"
    elif partial_size > 0 and status == 416:
        # A second request is necessary, but the old partial remains recoverable
        # if that request or its stream fails.
        response.close()
        response = requests.get(url, headers={}, stream=True, timeout=timeout)
        status = response.status_code
        download_target = destination.with_suffix(destination.suffix + ".restart")
        progress_offset = 0
        mode = "wb"

    try:
        response.raise_for_status()
        remaining = int(response.headers.get("Content-Length", "0"))
        total = remaining + progress_offset if remaining else 0
        written = 0
        with (
            download_target.open(mode) as stream,
            tqdm(
                total=total or None,
                initial=progress_offset,
                unit="B",
                unit_scale=True,
                desc=f"download {destination.name}",
            ) as bar,
        ):
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                stream.write(chunk)
                written += len(chunk)
                bar.update(len(chunk))
        if remaining and written != remaining:
            raise OSError(
                f"download truncated for {destination.name}: expected {remaining}, got {written}"
            )
    finally:
        response.close()

    if expected_md5 and not verify_md5(download_target, expected_md5):
        download_target.unlink(missing_ok=True)
        raise ValueError(f"md5 mismatch: {destination.name}")

    download_target.replace(destination)
    if download_target != partial:
        partial.unlink(missing_ok=True)
    return DownloadResult(
        dataset_id=dataset_id,
        file_name=destination.name,
        path=destination,
        expected_bytes=total or destination.stat().st_size,
        downloaded_bytes=written,
        skipped=False,
    )


def download_dataset(dataset_id: str, root: Path, timeout: int = 60) -> list[DownloadResult]:
    spec = get_dataset_spec(dataset_id)
    if spec.status != "active":
        raise RuntimeError(f"dataset {dataset_id} is pending: {spec.notes}")
    dataset_root = root / spec.dataset_id
    dataset_root.mkdir(parents=True, exist_ok=True)
    results: list[DownloadResult] = []
    for file_spec in spec.files:
        destination = dataset_root / file_spec.name
        result = download_file(
            dataset_id=spec.dataset_id,
            url=file_spec.url,
            destination=destination,
            expected_md5=file_spec.md5,
            timeout=timeout,
        )
        results.append(result)
    return results


def download_all(dataset_ids: Iterable[str], root: Path) -> list[DownloadResult]:
    all_results: list[DownloadResult] = []
    for dataset_id in dataset_ids:
        all_results.extend(download_dataset(dataset_id, root=root))
    return all_results
