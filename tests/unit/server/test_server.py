import base64
import hashlib
from pathlib import Path
from unittest.mock import patch
from requests import ConnectionError

from fastapi.testclient import TestClient

from krkn_ai.models.custom_errors import PrometheusConnectionError
from krkn_ai.server import create_app, upload_results

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


def test_discovery_returns_warning_when_prometheus_is_unavailable(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    with patch(
        "krkn_ai.server.discover_config", side_effect=PrometheusConnectionError("down")
    ):
        response = client.post(
            "/v1/discoveries",
            headers=TOKEN_HEADERS,
            json={"kubeconfig": base64.b64encode(b"apiVersion: v1\n").decode()},
        )
    assert response.status_code == 200
    assert response.json()["warnings"]


def test_artifacts_are_hidden_until_manifest_commit(tmp_path: Path):
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
    assert (
        client.get(
            "/v1/runs/run-1/files/nested/result.txt", headers=TOKEN_HEADERS
        ).status_code
        == 404
    )
    manifest = {
        "files": [{"path": "nested/result.txt", "sha256": digest, "size": len(payload)}]
    }
    assert (
        client.post(
            "/v1/runs/run-1/commit", headers=TOKEN_HEADERS, json=manifest
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/runs/run-1/results", headers=TOKEN_HEADERS).json() == manifest
    )
    assert (
        client.get(
            "/v1/runs/run-1/files/nested/result.txt", headers=TOKEN_HEADERS
        ).content
        == payload
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
        "files": [{"path": "result.txt", "sha256": digest, "size": len(payload)}]
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


def test_uploader_retries_and_commits_after_failure_marker(tmp_path: Path, monkeypatch):
    output = tmp_path / "output"
    state = tmp_path / "state"
    output.mkdir()
    (output / ".krkn-ai-complete").write_text('{"exitCode":42}\n')
    (output / "result.txt").write_text("result")
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
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
    assert [method for method, _, _ in calls] == ["PUT", "PUT", "POST"]
    assert calls[-1][2]["json"]["files"][0]["path"] == "result.txt"
