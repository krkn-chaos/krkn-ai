import base64
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from requests import ConnectionError, HTTPError, Response

from krkn_ai.server import _request_with_retry, create_app, upload_results

TOKEN_HEADERS = {"Authorization": "Bearer service-token"}


def test_discovery_renders_runner_kubeconfig(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    with patch(
        "krkn_ai.server.discover_config",
        return_value="kubeconfig_file_path: /input/kubeconfig\n",
    ) as discover:
        response = client.post(
            "/v1/discoveries",
            headers=TOKEN_HEADERS,
            json={"kubeconfig": base64.b64encode(b"apiVersion: v1\n").decode()},
        )
    assert response.status_code == 200
    assert response.json() == {
        "configYaml": "kubeconfig_file_path: /input/kubeconfig\n",
        "warnings": [],
    }
    assert discover.call_args.kwargs["rendered_kubeconfig"] == "/input/kubeconfig"


def test_discovery_preserves_results_when_prometheus_is_unavailable(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))

    def discover_config(*args, warnings, **kwargs):
        warnings.append("Prometheus unavailable")
        return "cluster_components:\n  namespaces: []\n"

    with patch("krkn_ai.server.discover_config", side_effect=discover_config):
        response = client.post(
            "/v1/discoveries",
            headers=TOKEN_HEADERS,
            json={"kubeconfig": base64.b64encode(b"apiVersion: v1\n").decode()},
        )

    assert response.status_code == 200
    assert response.json() == {
        "configYaml": "cluster_components:\n  namespaces: []\n",
        "warnings": ["Prometheus unavailable"],
    }


def test_artifacts_become_visible_with_in_progress_manifest(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    payload = b"run result"
    digest = hashlib.sha256(payload).hexdigest()
    upload = client.put(
        "/v1/runs/run-1/files/nested/result.txt",
        headers={**TOKEN_HEADERS, "X-Checksum-Sha256": digest},
        content=payload,
    )
    assert upload.status_code == 201
    assert (
        client.get("/v1/runs/run-1/results", headers=TOKEN_HEADERS).status_code == 404
    )
    in_progress = {
        "status": "in_progress",
        "files": [
            {"path": "nested/result.txt", "sha256": digest, "size": len(payload)}
        ],
    }
    assert (
        client.post(
            "/v1/runs/run-1/commit", headers=TOKEN_HEADERS, json=in_progress
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/runs/run-1/results", headers=TOKEN_HEADERS).json()
        == in_progress
    )
    assert (
        client.get(
            "/v1/runs/run-1/files/nested/result.txt", headers=TOKEN_HEADERS
        ).content
        == payload
    )
    updated_payload = b"updated result"
    updated_digest = hashlib.sha256(updated_payload).hexdigest()
    assert (
        client.put(
            "/v1/runs/run-1/files/nested/result.txt",
            headers={**TOKEN_HEADERS, "X-Checksum-Sha256": updated_digest},
            content=updated_payload,
        ).status_code
        == 201
    )
    updated_in_progress = {
        "status": "in_progress",
        "files": [
            {
                "path": "nested/result.txt",
                "sha256": updated_digest,
                "size": len(updated_payload),
            }
        ],
    }
    assert (
        client.post(
            "/v1/runs/run-1/commit",
            headers=TOKEN_HEADERS,
            json=updated_in_progress,
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/runs/run-1/results", headers=TOKEN_HEADERS).json()
        == updated_in_progress
    )
    completed = {**updated_in_progress, "status": "succeeded"}
    assert (
        client.post(
            "/v1/runs/run-1/commit", headers=TOKEN_HEADERS, json=completed
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/runs/run-1/results", headers=TOKEN_HEADERS).json() == completed
    )


def test_checksum_and_path_traversal_are_rejected(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    assert (
        client.put(
            "/v1/runs/run-1/files/result.txt",
            headers={**TOKEN_HEADERS, "X-Checksum-Sha256": "0" * 64},
            content=b"different",
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/v1/runs/run-1/files/%2E%2E/secret.txt",
            headers={
                **TOKEN_HEADERS,
                "X-Checksum-Sha256": hashlib.sha256(b"x").hexdigest(),
            },
            content=b"x",
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/v1/runs/%2E%2E/files/secret.txt",
            headers={
                **TOKEN_HEADERS,
                "X-Checksum-Sha256": hashlib.sha256(b"x").hexdigest(),
            },
            content=b"x",
        ).status_code
        == 422
    )


def test_manifest_commit_is_idempotent(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    payload = b"value"
    digest = hashlib.sha256(payload).hexdigest()
    assert (
        client.put(
            "/v1/runs/run-1/files/result.txt",
            headers={**TOKEN_HEADERS, "X-Checksum-Sha256": digest},
            content=payload,
        ).status_code
        == 201
    )
    manifest = {
        "status": "succeeded",
        "files": [{"path": "result.txt", "sha256": digest, "size": len(payload)}],
    }
    assert (
        client.post(
            "/v1/runs/run-1/commit", headers=TOKEN_HEADERS, json=manifest
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/runs/run-1/commit", headers=TOKEN_HEADERS, json=manifest
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/runs/run-1/commit",
            headers=TOKEN_HEADERS,
            json={**manifest, "status": "in_progress"},
        ).status_code
        == 409
    )


def test_artifact_upload_enforces_file_and_run_limits(tmp_path: Path):
    client = TestClient(
        create_app(
            tmp_path,
            "service-token",
            max_artifact_bytes=4,
            max_run_bytes=3,
        )
    )
    first = b"two"
    assert (
        client.put(
            "/v1/runs/run-1/files/first.txt",
            headers={
                **TOKEN_HEADERS,
                "X-Checksum-Sha256": hashlib.sha256(first).hexdigest(),
            },
            content=first,
        ).status_code
        == 201
    )

    second = b"two"
    response = client.put(
        "/v1/runs/run-1/files/second.txt",
        headers={
            **TOKEN_HEADERS,
            "X-Checksum-Sha256": hashlib.sha256(second).hexdigest(),
        },
        content=second,
    )

    assert response.status_code == 413


def test_uploader_retries_and_commits_after_failure_marker(tmp_path: Path, monkeypatch):
    output = tmp_path / "output"
    state = tmp_path / "state"
    run_output = output / "run-1"
    run_output.mkdir(parents=True)
    (run_output / ".krkn-ai-complete").write_text('{"exitCode":42}\n')
    (run_output / "result.txt").write_text("result")
    calls = []

    def request(method, url, **kwargs):
        body = kwargs.get("data")
        calls.append((method, url, kwargs, body.read() if body else None))
        if len(calls) == 1:
            raise ConnectionError("temporarily unavailable")

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

        return Response()

    monkeypatch.setenv("KRKNAI_OUTPUT_DIR", str(output))
    monkeypatch.setenv("KRKNAI_UPLOAD_STATE_DIR", str(state))
    monkeypatch.setenv("KRKNAI_RUN_UID", "run-1")
    monkeypatch.setenv("KRKNAI_SERVICE_URL", "http://service")
    monkeypatch.setenv("KRKNAI_SERVICE_TOKEN", "token")
    monkeypatch.setattr("krkn_ai.server.requests.request", request)
    monkeypatch.setattr("krkn_ai.server.time.sleep", lambda _: None)
    upload_results()
    assert [method for method, _, _, _ in calls] == ["PUT", "PUT", "POST"]
    assert [call[3] for call in calls[:2]] == [b"result", b"result"]
    assert calls[-1][2]["json"]["files"][0]["path"] == "result.txt"
    assert calls[-1][2]["json"]["status"] == "failed"


def test_uploader_checkpoints_then_finalizes_on_completion(tmp_path: Path, monkeypatch):
    output = tmp_path / "output"
    state = tmp_path / "state"
    run_output = output / "run-1"
    run_output.mkdir(parents=True)
    marker = run_output / ".krkn-ai-complete"
    (run_output / "result.txt").write_text("result")
    calls = []

    def request(method, url, **kwargs):
        body = kwargs.get("data")
        calls.append((method, url, kwargs, body.read() if body else None))

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

        return Response()

    def complete_run(_: int) -> None:
        marker.write_text('{"exitCode":0}\n')

    monkeypatch.setenv("KRKNAI_OUTPUT_DIR", str(output))
    monkeypatch.setenv("KRKNAI_UPLOAD_STATE_DIR", str(state))
    monkeypatch.setenv("KRKNAI_RUN_UID", "run-1")
    monkeypatch.setenv("KRKNAI_SERVICE_URL", "http://service")
    monkeypatch.setenv("KRKNAI_SERVICE_TOKEN", "token")
    monkeypatch.setattr("krkn_ai.server.requests.request", request)
    monkeypatch.setattr("krkn_ai.server.time.sleep", complete_run)

    upload_results()

    assert [method for method, _, _, _ in calls] == ["PUT", "POST", "POST"]
    assert [call[2]["json"]["status"] for call in calls[1:]] == [
        "in_progress",
        "succeeded",
    ]


def test_request_retry_does_not_retry_client_errors(monkeypatch):
    calls = []
    response = Response()
    response.status_code = 401
    response.url = "http://service"

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return response

    monkeypatch.setattr("krkn_ai.server.requests.request", request)

    with pytest.raises(HTTPError):
        _request_with_retry("PUT", "http://service")

    assert len(calls) == 1
