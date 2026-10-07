"""Authenticated, single-PVC artifact service for Krkn-AI runs."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, BinaryIO, Literal
from urllib.parse import quote

import requests
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from krkn_ai.cli.cmd import DiscoveryError, discover_config
from krkn_ai.models.config import ConfigFile
from krkn_ai.run_results import (
    completed_generation_count,
    parse_run_artifacts,
    scenario_detail,
    scenario_index_row,
    _completed_fitness,
)


DEFAULT_ARTIFACT_ROOT = "/var/lib/krkn-ai"
MANIFEST_NAME = "manifest.json"
COMPLETE_MARKER = ".krkn-ai-complete"
DEFAULT_MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_RUN_BYTES = 1024 * 1024 * 1024
MAX_REQUEST_ATTEMPTS = 5
MAX_RETRY_DELAY_SECONDS = 30
DEFAULT_UPLOAD_INTERVAL_SECONDS = 150


def _configured_limit(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if limit <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return limit


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
    status: Literal["in_progress", "succeeded", "failed"] = "succeeded"


def _safe_uid(uid: str) -> str:
    if (
        not uid
        or uid in (".", "..")
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
    def __init__(
        self,
        root: str | Path,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
        max_run_bytes: int = DEFAULT_MAX_RUN_BYTES,
    ):
        if max_artifact_bytes <= 0 or max_run_bytes <= 0:
            raise ValueError("artifact size limits must be positive")
        self.root = Path(root)
        self.max_artifact_bytes = max_artifact_bytes
        self.max_run_bytes = max_run_bytes
        self._commit_lock = threading.Lock()

    def run_dir(self, uid: str) -> Path:
        return self.root / "runs" / _safe_uid(uid)

    def _manifest_path(self, uid: str) -> Path:
        return self.run_dir(uid) / MANIFEST_NAME

    @staticmethod
    def _run_size(run_dir: Path) -> int:
        if not run_dir.exists():
            return 0
        return sum(
            file.stat().st_size
            for file in run_dir.rglob("*")
            if file.is_file()
            and file.name != MANIFEST_NAME
            and not file.name.startswith(".upload-")
        )

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
        existing_size = destination.stat().st_size if destination.is_file() else 0
        run_size = self._run_size(run_dir)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-", dir=destination.parent
        )
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                async for chunk in stream:
                    size += len(chunk)
                    if (
                        size > self.max_artifact_bytes
                        or run_size - existing_size + size > self.max_run_bytes
                    ):
                        raise HTTPException(
                            status.HTTP_413_CONTENT_TOO_LARGE,
                            "artifact upload exceeds configured storage limit",
                        )
                    digest.update(chunk)
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
        manifest = {
            "status": request.status,
            "files": sorted(files, key=lambda entry: entry["path"]),
        }
        manifest_path = self._manifest_path(uid)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        with self._commit_lock:
            if manifest_path.exists():
                existing = json.loads(manifest_path.read_text())
                if existing.get("status", "succeeded") in {"succeeded", "failed"}:
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
                os.replace(temporary_name, manifest_path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        return manifest

    def manifest(self, uid: str) -> dict[str, Any]:
        try:
            value = json.loads(self._manifest_path(uid).read_text())
        except FileNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "run artifacts are not committed"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "invalid committed manifest"
            ) from exc
        if not isinstance(value, dict) or not isinstance(value.get("files"), list):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "invalid committed manifest"
            )
        return value

    @staticmethod
    def _manifest_entry(manifest: dict[str, Any], relative_path: PurePosixPath):
        normalized = str(relative_path)
        for entry in manifest["files"]:
            if isinstance(entry, dict) and entry.get("path") == normalized:
                if (
                    not isinstance(entry.get("sha256"), str)
                    or not isinstance(entry.get("size"), int)
                    or entry["size"] < 0
                ):
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY, "invalid committed manifest"
                    )
                return entry
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")

    def read_verified(
        self, uid: str, path: str, manifest: dict[str, Any]
    ) -> tuple[bytes, str]:
        relative_path = _safe_path(path)
        entry = self._manifest_entry(manifest, relative_path)
        candidate = self.run_dir(uid) / relative_path
        try:
            with candidate.open("rb") as source:
                content = source.read()
        except OSError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "artifact_updating"
            ) from exc
        actual_checksum = hashlib.sha256(content).hexdigest()
        if len(content) != entry["size"] or not hmac.compare_digest(
            actual_checksum, entry["sha256"]
        ):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "artifact_updating"
            )
        return content, actual_checksum

    def open_verified(
        self, uid: str, path: str, manifest: dict[str, Any]
    ) -> tuple[BinaryIO, int]:
        relative_path = _safe_path(path)
        entry = self._manifest_entry(manifest, relative_path)
        candidate = self.run_dir(uid) / relative_path
        try:
            source = candidate.open("rb")
        except OSError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "artifact_updating"
            ) from exc
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            if size != entry["size"] or not hmac.compare_digest(
                digest.hexdigest(), entry["sha256"]
            ):
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "artifact_updating"
                )
            source.seek(0)
            return source, size
        except Exception:
            source.close()
            raise


def create_app(
    root: str | Path | None = None,
    token: str | None = None,
    max_artifact_bytes: int | None = None,
    max_run_bytes: int | None = None,
) -> FastAPI:
    store = ArtifactStore(
        root or os.environ.get("KRKNAI_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT),
        max_artifact_bytes
        if max_artifact_bytes is not None
        else _configured_limit("KRKNAI_MAX_ARTIFACT_BYTES", DEFAULT_MAX_ARTIFACT_BYTES),
        max_run_bytes
        if max_run_bytes is not None
        else _configured_limit("KRKNAI_MAX_RUN_BYTES", DEFAULT_MAX_RUN_BYTES),
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

    def typed_snapshot(uid: str):
        try:
            manifest = store.manifest(uid)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                return None, None
            raise
        selected_files: dict[str, tuple[bytes, str]] = {}
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "invalid committed manifest"
                )
            path = entry["path"]
            if path in {"progress.json", "results.json"} or re.fullmatch(
                r"(?:yaml|json)/generation_\d+/[^/]+\.(?:yaml|yml|json)", path
            ):
                selected_files[path] = store.read_verified(uid, path, manifest)
        return manifest, parse_run_artifacts(selected_files)

    def not_available_summary() -> dict[str, Any]:
        return {
            "artifactStatus": "not_available",
            "completedGenerations": None,
            "currentGeneration": None,
            "completedScenarios": None,
            "configuredGenerations": None,
            "populationSize": None,
            "bestFitness": None,
            "averageFitness": None,
            "baselineFitness": None,
            "fitnessProgression": [],
        }

    def summary_payload(manifest: dict[str, Any] | None, artifacts: Any):
        if manifest is None:
            return not_available_summary()
        run_status = manifest.get("status")
        if run_status not in {"in_progress", "succeeded", "failed"}:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "invalid committed manifest"
            )
        terminal = run_status in {"succeeded", "failed"}
        final = artifacts.final_results if terminal else None
        progress = artifacts.progress or {}
        if final is not None:
            summary = final.get("summary") or {}
            config = final.get("config") or {}
            completed_scenarios = summary.get("total_scenarios_executed")
            configured_generations = config.get("generations")
            population_size = config.get("population_size")
        else:
            completed_scenarios = progress.get("completedScenarios")
            configured_generations = progress.get("configuredGenerations")
            population_size = progress.get("populationSize")
        values = {
            "completedGenerations": completed_generation_count(artifacts, terminal),
            "currentGeneration": (
                None if terminal else progress.get("currentGeneration")
            ),
            "completedScenarios": completed_scenarios,
            "configuredGenerations": configured_generations,
            "populationSize": population_size,
            **_completed_fitness(artifacts, terminal),
        }
        for field in (
            "completedGenerations",
            "completedScenarios",
            "configuredGenerations",
            "populationSize",
        ):
            value = values[field]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "invalid committed artifact"
                )
        current = values["currentGeneration"]
        if current is not None and (
            isinstance(current, bool) or not isinstance(current, int) or current < 0
        ):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "invalid committed artifact"
            )
        for field in ("bestFitness", "averageFitness", "baselineFitness"):
            value = values[field]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "invalid committed artifact"
                )
        if not isinstance(values["fitnessProgression"], list):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "invalid committed artifact"
            )
        return {
            "artifactStatus": run_status,
            **values,
        }

    @app.post("/v1/configs/validate", dependencies=[Depends(authenticate)])
    async def validate_config(request: Request):
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not isinstance(
            payload.get("configYaml"), str
        ):
            return JSONResponse(
                {"errors": [{"path": "configYaml", "message": "Invalid value"}]},
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        try:
            config_data = yaml.safe_load(payload["configYaml"])
        except yaml.YAMLError:
            config_data = None
        if not isinstance(config_data, dict):
            return JSONResponse(
                {"errors": [{"path": "", "message": "Invalid value"}]},
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        config_data["kubeconfig_file_path"] = "/input/kubeconfig"
        try:
            config = ConfigFile.model_validate(config_data)
        except ValidationError as exc:
            errors = [
                {
                    "path": ".".join(str(part) for part in error.get("loc", ())),
                    "message": "Invalid value",
                }
                for error in exc.errors(include_input=False)
            ]
            return JSONResponse(
                {"errors": errors}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
            )
        if config.genetic.composition_rate > 0:
            return JSONResponse(
                {
                    "errors": [
                        {
                            "path": "genetic.composition_rate",
                            "message": "Invalid value",
                        }
                    ]
                },
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return {"valid": True}

    @app.get(
        "/v1/runs/{uid}/summary",
        dependencies=[Depends(authenticate)],
    )
    def typed_summary(uid: str) -> dict[str, Any]:
        manifest, artifacts = typed_snapshot(uid)
        return summary_payload(manifest, artifacts)

    @app.get(
        "/v1/runs/{uid}/scenarios",
        dependencies=[Depends(authenticate)],
    )
    def scenario_index(uid: str, request: Request) -> dict[str, Any]:
        allowed = {
            "page",
            "limit",
            "generation",
            "scenarioType",
            "search",
            "sort",
            "direction",
        }
        params = request.query_params
        if set(params.keys()) - allowed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid query")
        try:
            page = int(params.get("page", "1"))
            limit = int(params.get("limit", "100"))
            generation_filter = (
                int(params["generation"]) if "generation" in params else None
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid query") from exc
        sort = params.get("sort", "generation")
        direction = params.get("direction", "asc")
        sort_fields = {
            "generation",
            "scenarioId",
            "scenarioType",
            "fitnessScore",
            "outcome",
            "durationSeconds",
        }
        if (
            page < 1
            or limit < 1
            or limit > 500
            or (generation_filter is not None and generation_filter < 0)
            or sort not in sort_fields
            or direction not in {"asc", "desc"}
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid query")
        manifest, artifacts = typed_snapshot(uid)
        if manifest is None:
            rows = []
            terminal = False
        else:
            terminal = manifest["status"] in {"succeeded", "failed"}
            rows = [
                scenario_index_row(value, artifacts, terminal)
                for value in artifacts.scenarios.values()
            ]
        scenario_type_filter = params.get("scenarioType")
        search = params.get("search", "").casefold()
        rows = [
            row
            for row in rows
            if (generation_filter is None or row["generation"] == generation_filter)
            and (
                scenario_type_filter is None
                or (row["scenarioType"] or "").casefold()
                == scenario_type_filter.casefold()
            )
            and (
                not search
                or search in row["scenarioId"].casefold()
                or search in (row["scenarioType"] or "").casefold()
            )
        ]

        def sort_value(row: dict[str, Any]):
            value = row[sort]
            if value is None:
                return (1, 0, "")
            if sort == "generation":
                baseline_rank = 0 if row["scenarioId"] == "baseline" else 1
                return (0, value, baseline_rank)
            if sort == "scenarioId":
                if row["scenarioId"] == "baseline":
                    return (0, 0, 0.0)
                try:
                    return (0, 1, float(value))
                except (TypeError, ValueError):
                    return (0, 2, str(value).casefold())
            if isinstance(value, str):
                value = value.casefold()
            return (0, 0, value)

        rows.sort(key=sort_value, reverse=direction == "desc")
        total = len(rows)
        start = (page - 1) * limit
        return {
            "scenarios": rows[start : start + limit],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "totalPages": (total + limit - 1) // limit,
            },
        }

    @app.get(
        "/v1/runs/{uid}/scenarios/{generation}/{scenario_id}",
        dependencies=[Depends(authenticate)],
    )
    def scenario_detail_route(
        uid: str, generation: str, scenario_id: str
    ) -> dict[str, Any]:
        try:
            generation_id = int(generation)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "invalid generation"
            ) from exc
        if generation_id < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid generation")
        manifest, artifacts = typed_snapshot(uid)
        if manifest is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
        key = f"{generation_id}:{scenario_id}"
        artifact = artifacts.scenarios.get(key)
        if artifact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
        return scenario_detail(
            artifact,
            artifacts,
            manifest["status"] in {"succeeded", "failed"},
        )

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
            warnings: list[str] = []
            try:
                config_yaml = discover_config(
                    temporary_name,
                    namespace=request.namespacePattern,
                    pod_label=request.podLabelPattern,
                    node_label=request.nodeLabelPattern,
                    skip_pod_name=request.skipPodName,
                    rendered_kubeconfig="/input/kubeconfig",
                    warnings=warnings,
                )
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
    def artifact(uid: str, path: str) -> StreamingResponse:
        manifest = store.manifest(uid)
        source, size = store.open_verified(uid, path, manifest)

        def stream():
            try:
                while chunk := source.read(64 * 1024):
                    yield chunk
            finally:
                source.close()

        return StreamingResponse(
            stream(),
            media_type="application/octet-stream",
            headers={"Content-Length": str(size)},
        )

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
    last_response: requests.Response | None = None
    last_error: requests.RequestException | None = None
    for attempt in range(MAX_REQUEST_ATTEMPTS):
        body = kwargs.get("data")
        if body is not None and hasattr(body, "seek"):
            body.seek(0)
        try:
            response = requests.request(method, url, timeout=(5, 30), **kwargs)
            if response.status_code < 500:
                response.raise_for_status()
                return response
            last_response = response
        except requests.HTTPError:
            raise
        except requests.RequestException as error:
            last_error = error
        if attempt < MAX_REQUEST_ATTEMPTS - 1:
            time.sleep(min(2**attempt, MAX_RETRY_DELAY_SECONDS))

    if last_response is not None:
        last_response.raise_for_status()
    assert last_error is not None
    raise last_error


def _upload_files(
    output: Path,
    uid: str,
    service_url: str,
    headers: dict[str, str],
    state: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    marker = output / COMPLETE_MARKER
    for source in sorted(
        path
        for path in output.rglob("*")
        if path.is_file()
        and path != marker
        and not path.name.startswith((".krkn-ai-tmp-", ".upload-", ".manifest-"))
    ):
        relative_path = source.relative_to(output).as_posix()
        with source.open("rb") as snapshot:
            content = snapshot.read()
        checksum = hashlib.sha256(content).hexdigest()
        entry = {"path": relative_path, "sha256": checksum, "size": len(content)}
        if state.get(relative_path) != entry:
            _request_with_retry(
                "PUT",
                f"{service_url}/v1/runs/{quote(uid, safe='')}/files/{quote(relative_path, safe='/')}",
                headers={**headers, "X-Checksum-SHA256": checksum},
                data=io.BytesIO(content),
            )
            state[relative_path] = entry
            _save_state(state)
        files.append(entry)
    return files


def _commit_files(
    service_url: str,
    uid: str,
    headers: dict[str, str],
    files: list[dict[str, Any]],
    run_status: Literal["in_progress", "succeeded", "failed"],
) -> None:
    _request_with_retry(
        "POST",
        f"{service_url}/v1/runs/{quote(uid, safe='')}/commit",
        headers=headers,
        json={"files": files, "status": run_status},
    )


def _final_status(marker: Path) -> Literal["succeeded", "failed"]:
    try:
        return (
            "succeeded" if json.loads(marker.read_text())["exitCode"] == 0 else "failed"
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "failed"


def upload_results() -> None:
    uid = _safe_uid(os.environ["KRKNAI_RUN_UID"])
    output = Path(os.environ.get("KRKNAI_OUTPUT_DIR", "/output")) / uid
    service_url = os.environ["KRKNAI_SERVICE_URL"].rstrip("/")
    token = os.environ["KRKNAI_SERVICE_TOKEN"]
    marker = output / COMPLETE_MARKER
    interval = _configured_limit(
        "KRKNAI_UPLOAD_INTERVAL_SECONDS", DEFAULT_UPLOAD_INTERVAL_SECONDS
    )
    headers = {"Authorization": f"Bearer {token}"}
    state = _load_state()
    while not marker.exists():
        files = _upload_files(output, uid, service_url, headers, state)
        _commit_files(service_url, uid, headers, files, "in_progress")
        for _ in range(interval):
            if marker.exists():
                break
            time.sleep(1)
    files = _upload_files(output, uid, service_url, headers, state)
    _commit_files(service_url, uid, headers, files, _final_status(marker))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["uploader"])
    args = parser.parse_args()
    if args.mode == "uploader":
        upload_results()


if __name__ == "__main__":
    main()
