"""Authenticated, single-PVC artifact service for Krkn-AI runs."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import quote

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from krkn_ai.cli.cmd import DiscoveryError, discover_config
from krkn_ai.models.custom_errors import PrometheusConnectionError

DEFAULT_ARTIFACT_ROOT = "/var/lib/krkn-ai"
MANIFEST_NAME = "manifest.json"
COMPLETE_MARKER = ".krkn-ai-complete"


class DiscoveryRequest(BaseModel):
    kubeconfig: str
    namespacePattern: str = ".*"
    podLabelPattern: str = ".*"
    nodeLabelPattern: str = ".*"
    skipPodName: str | None = None


class ManifestFile(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class CommitRequest(BaseModel):
    files: list[ManifestFile]


def _safe_uid(uid: str) -> str:
    if (
        not uid
        or len(uid) > 253
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for c in uid
        )
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid run UID")
    return uid


def _safe_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or candidate.is_absolute()
        or any(part in ("", ".", "..") for part in candidate.parts)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid artifact path"
        )
    return candidate


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def run_dir(self, uid: str) -> Path:
        return self.root / "runs" / _safe_uid(uid)

    def _manifest_path(self, uid: str) -> Path:
        return self.run_dir(uid) / MANIFEST_NAME

    async def upload(
        self, uid: str, path: str, stream: Any, expected_sha256: str
    ) -> int:
        relative_path = _safe_path(path)
        if (
            not expected_sha256
            or len(expected_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha256)
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid SHA-256 checksum"
            )
        run_dir = self.run_dir(uid)
        destination = run_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-", dir=destination.parent
        )
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                async for chunk in stream:
                    digest.update(chunk)
                    size += len(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "checksum mismatch"
                )
            os.replace(temporary_name, destination)
            return size
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def commit(self, uid: str, request: CommitRequest) -> dict[str, Any]:
        run_dir = self.run_dir(uid)
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in request.files:
            relative_path = _safe_path(entry.path)
            normalized = str(relative_path)
            if normalized in seen:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "duplicate manifest path"
                )
            seen.add(normalized)
            file_path = run_dir / relative_path
            if not file_path.is_file():
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"artifact {normalized} has not been uploaded",
                )
            actual_sha256, actual_size = _sha256(file_path)
            if actual_size != entry.size or not hmac.compare_digest(
                actual_sha256, entry.sha256
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"artifact {normalized} does not match manifest",
                )
            files.append(
                {"path": normalized, "sha256": entry.sha256, "size": entry.size}
            )
        manifest = {"files": sorted(files, key=lambda entry: entry["path"])}
        manifest_path = self._manifest_path(uid)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        if manifest_path.exists():
            if manifest_path.read_bytes() == encoded:
                return manifest
            raise HTTPException(
                status.HTTP_409_CONFLICT, "run artifacts are already committed"
            )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".manifest-", dir=manifest_path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_name, manifest_path)
            except FileExistsError:
                if manifest_path.read_bytes() == encoded:
                    return manifest
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "run artifacts are already committed"
                )
            return manifest
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def manifest(self, uid: str) -> dict[str, Any]:
        try:
            return json.loads(self._manifest_path(uid).read_text())
        except FileNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "run artifacts are not committed"
            ) from exc

    def file(self, uid: str, path: str) -> Path:
        relative_path = _safe_path(path)
        manifest = self.manifest(uid)
        if str(relative_path) not in {entry["path"] for entry in manifest["files"]}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")
        candidate = self.run_dir(uid) / relative_path
        if not candidate.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")
        return candidate


def create_app(root: str | Path | None = None, token: str | None = None) -> FastAPI:
    store = ArtifactStore(
        root or os.environ.get("KRKNAI_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT)
    )
    service_token = (
        token if token is not None else os.environ.get("KRKNAI_SERVICE_TOKEN", "")
    )
    app = FastAPI(title="Krkn-AI artifact service")

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {service_token}"
        if (
            not service_token
            or authorization is None
            or not hmac.compare_digest(authorization, expected)
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid service token")

    @app.post("/v1/discoveries", dependencies=[Depends(authenticate)])
    def discover(request: DiscoveryRequest) -> dict[str, Any]:
        try:
            kubeconfig = base64.b64decode(request.kubeconfig, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid kubeconfig encoding"
            ) from exc
        descriptor, temporary_name = tempfile.mkstemp(prefix="krkn-ai-kubeconfig-")
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(kubeconfig)
            try:
                config_yaml = discover_config(
                    temporary_name,
                    namespace=request.namespacePattern,
                    pod_label=request.podLabelPattern,
                    node_label=request.nodeLabelPattern,
                    skip_pod_name=request.skipPodName,
                    rendered_kubeconfig="/input/kubeconfig",
                )
                warnings: list[str] = []
            except PrometheusConnectionError:
                config_yaml = "kubeconfig_file_path: /input/kubeconfig\n"
                warnings = [
                    "Prometheus discovery failed; generated configuration omits Prometheus data."
                ]
            except DiscoveryError as exc:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
            return {"configYaml": config_yaml, "warnings": warnings}
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @app.put("/v1/runs/{uid}/files/{path:path}", dependencies=[Depends(authenticate)])
    async def upload(
        uid: str,
        path: str,
        request: Request,
        x_checksum_sha256: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        size = await store.upload(uid, path, request.stream(), x_checksum_sha256 or "")
        return JSONResponse({"size": size}, status_code=status.HTTP_201_CREATED)

    @app.post("/v1/runs/{uid}/commit", dependencies=[Depends(authenticate)])
    def commit(uid: str, request: CommitRequest) -> dict[str, Any]:
        return store.commit(uid, request)

    @app.get("/v1/runs/{uid}/results", dependencies=[Depends(authenticate)])
    def results(uid: str) -> dict[str, Any]:
        return store.manifest(uid)

    @app.get("/v1/runs/{uid}/files/{path:path}", dependencies=[Depends(authenticate)])
    def artifact(uid: str, path: str) -> FileResponse:
        return FileResponse(store.file(uid, path))

    return app


app = create_app()


def _state_file() -> Path:
    directory = Path(os.environ.get("KRKNAI_UPLOAD_STATE_DIR", "/upload-state"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "uploaded.json"


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    state_file = _state_file()
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True))
    os.replace(temporary, state_file)


def _load_state() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_state_file().read_text())
    except FileNotFoundError:
        return {}


def _request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    while True:
        try:
            response = requests.request(method, url, timeout=(5, 30), **kwargs)
            if response.status_code < 500:
                response.raise_for_status()
                return response
        except requests.RequestException:
            pass
        time.sleep(2)


def upload_results() -> None:
    output = Path(os.environ.get("KRKNAI_OUTPUT_DIR", "/output"))
    uid = _safe_uid(os.environ["KRKNAI_RUN_UID"])
    service_url = os.environ["KRKNAI_SERVICE_URL"].rstrip("/")
    token = os.environ["KRKNAI_SERVICE_TOKEN"]
    marker = output / COMPLETE_MARKER
    while not marker.exists():
        time.sleep(1)
    headers = {"Authorization": f"Bearer {token}"}
    state = _load_state()
    files: list[dict[str, Any]] = []
    for source in sorted(
        path for path in output.rglob("*") if path.is_file() and path != marker
    ):
        relative_path = source.relative_to(output).as_posix()
        checksum, size = _sha256(source)
        entry = {"path": relative_path, "sha256": checksum, "size": size}
        if state.get(relative_path) != entry:
            with source.open("rb") as body:
                _request_with_retry(
                    "PUT",
                    f"{service_url}/v1/runs/{quote(uid, safe='')}/files/{quote(relative_path, safe='/')}",
                    headers={**headers, "X-Checksum-SHA256": checksum},
                    data=body,
                )
            state[relative_path] = entry
            _save_state(state)
        files.append(entry)
    _request_with_retry(
        "POST",
        f"{service_url}/v1/runs/{quote(uid, safe='')}/commit",
        headers=headers,
        json={"files": files},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["uploader"])
    args = parser.parse_args()
    if args.mode == "uploader":
        upload_results()


if __name__ == "__main__":
    main()
