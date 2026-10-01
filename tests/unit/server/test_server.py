import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import patch


import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from requests import ConnectionError, HTTPError, Response

from krkn_ai.run_results import parse_run_artifacts
from krkn_ai.server import (
    _request_with_retry,
    _upload_files,
    create_app,
    upload_results,
)

TOKEN_HEADERS = {"Authorization": "Bearer service-token"}


@pytest.mark.parametrize(
    "origin",
    ["initial", "crossover", "composition", "parameter_mutation", "type_mutation"],
)
def test_legacy_scenario_origin_tag_is_normalized_safely(origin: str):
    path = "yaml/generation_0/scenario_7.yaml"
    content = f"""\
generation_id: 0
scenario_id: 7
scenario:
  name: pod_scenarios
  origin: !!python/object/apply:krkn_ai.models.scenario.base.ScenarioOrigin
    - {origin}
fitness_result:
  fitness_score: 10
""".encode()
    checksum = hashlib.sha256(content).hexdigest()
    with pytest.raises(HTTPException) as error:
        parse_run_artifacts({path: (content, checksum)})
    assert error.value.status_code == 503

    progress = json.dumps(
        {
            "resultChecksums": {"0:7": checksum},
            "fitnessFinalByScenario": {"0:7": False},
        }
    ).encode()
    parsed = parse_run_artifacts(
        {
            path: (content, checksum),
            "progress.json": (progress, hashlib.sha256(progress).hexdigest()),
        }
    )
    assert parsed.scenarios["0:7"].value["scenario"]["origin"] == origin

    arbitrary_tag = content.replace(
        b"python/object/apply:krkn_ai.models.scenario.base.ScenarioOrigin",
        b"python/object/apply:os.system",
    )
    with pytest.raises(HTTPException) as error:
        parse_run_artifacts(
            {path: (arbitrary_tag, hashlib.sha256(arbitrary_tag).hexdigest())}
        )
    assert error.value.status_code == 502

    invalid_value = content.replace(origin.encode(), b"not-an-origin")
    with pytest.raises(HTTPException) as error:
        parse_run_artifacts(
            {path: (invalid_value, hashlib.sha256(invalid_value).hexdigest())}
        )
    assert error.value.status_code == 502


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
    (run_output / ".krkn-ai-tmp-progress.json").write_text("partial")
    (run_output / ".upload-staging").write_text("partial")
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
    assert all(call[1].endswith("/result.txt") for call in calls if call[0] == "PUT")
    assert all(
        call[2]["headers"]["X-Checksum-SHA256"] == hashlib.sha256(call[3]).hexdigest()
        for call in calls[:2]
    )
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


def test_uploader_hashes_the_exact_opened_snapshot(tmp_path: Path, monkeypatch):
    output = tmp_path / "run-1"
    output.mkdir()
    source = output / "result.txt"
    snapshot = b"old committed bytes"
    source.write_bytes(snapshot)
    monkeypatch.setenv("KRKNAI_UPLOAD_STATE_DIR", str(tmp_path / "state"))
    uploads = []

    def upload(method, url, **kwargs):
        body = kwargs["data"].read()
        uploads.append((method, url, body, kwargs["headers"]["X-Checksum-SHA256"]))
        source.write_bytes(b"new bytes")

    monkeypatch.setattr("krkn_ai.server._request_with_retry", upload)
    entries = _upload_files(output, "run-1", "http://service", {}, {})

    expected_digest = hashlib.sha256(snapshot).hexdigest()
    assert uploads == [
        (
            "PUT",
            "http://service/v1/runs/run-1/files/result.txt",
            snapshot,
            expected_digest,
        )
    ]
    assert entries[0]["sha256"] == expected_digest
    assert source.read_bytes() == b"new bytes"


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


def test_final_best_scenarios_restore_parameters_by_generation_and_id(
    tmp_path: Path,
):
    client = TestClient(create_app(tmp_path, "service-token"))
    artifacts = {}
    result_checksums = {}
    for generation in (0, 1):
        path = f"yaml/generation_{generation}/custom-result.yaml"
        content = yaml.safe_dump(
            {
                "generation_id": generation,
                "scenario_id": 7,
                "scenario": {
                    "name": "pod_scenarios",
                    "origin": "initial",
                    "parent_ids": [],
                },
                "fitness_result": {
                    "fitness_score": generation + 10,
                    "scores": [
                        {
                            "id": 1,
                            "fitness_score": generation + 2,
                            "weighted_score": generation + 1,
                            "normalized_score": 0.25,
                        }
                    ],
                },
            }
        ).encode()
        checksum = hashlib.sha256(content).hexdigest()
        artifacts[path] = content
        result_checksums[f"{generation}:7"] = checksum

    progress = json.dumps(
        {
            "resultChecksums": result_checksums,
            "fitnessFinalByScenario": {
                "0:7": True,
                "1:7": True,
            },
        }
    ).encode()
    final_results = json.dumps(
        {
            "best_scenarios": [
                {
                    "generation": 0,
                    "scenario_id": 7,
                    "parameters": {"namespace": "older-generation"},
                },
                {
                    "generation": 1,
                    "scenario_id": 7,
                    "parameters": {"namespace": "newer-generation"},
                },
            ]
        }
    ).encode()
    artifacts["progress.json"] = progress
    artifacts["results.json"] = final_results

    manifest_files = []
    for path, content in artifacts.items():
        checksum = hashlib.sha256(content).hexdigest()
        upload = client.put(
            f"/v1/runs/run-1/files/{path}",
            headers={**TOKEN_HEADERS, "X-Checksum-Sha256": checksum},
            content=content,
        )
        assert upload.status_code == 201
        manifest_files.append({"path": path, "sha256": checksum, "size": len(content)})
    commit = client.post(
        "/v1/runs/run-1/commit",
        headers=TOKEN_HEADERS,
        json={"status": "succeeded", "files": manifest_files},
    )
    assert commit.status_code == 200

    older = client.get("/v1/runs/run-1/scenarios/0/7", headers=TOKEN_HEADERS)
    newer = client.get("/v1/runs/run-1/scenarios/1/7", headers=TOKEN_HEADERS)
    assert older.status_code == 200
    assert newer.status_code == 200
    assert older.json()["parameters"] == [
        {"name": "namespace", "value": "older-generation"}
    ]
    assert newer.json()["parameters"] == [
        {"name": "namespace", "value": "newer-generation"}
    ]
    assert older.json()["fitnessResult"]["scores"] == [
        {
            "id": 1,
            "rawScore": 2,
            "normalizedScore": None,
            "query": None,
            "queryType": None,
        }
    ]


def test_typed_partial_results_validation_and_manifest_consistency(
    tmp_path: Path, minimal_config
):
    client = TestClient(create_app(tmp_path, "service-token"))
    auth = TOKEN_HEADERS
    assert client.get("/v1/runs/run-1/summary", headers=auth).json() == {
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
    assert client.get("/v1/runs/run-1/summary").status_code == 401

    valid_config = yaml.safe_dump(minimal_config.model_dump(mode="json"))
    assert client.post(
        "/v1/configs/validate",
        headers=auth,
        json={"configYaml": valid_config},
    ).json() == {"valid": True}
    invalid_config = minimal_config.model_dump(mode="json")
    invalid_config["kubeconfig_file_path"] = "credential-must-not-leak"
    invalid_config["genetic"]["composition_rate"] = 0.5
    response = client.post(
        "/v1/configs/validate",
        headers=auth,
        json={"configYaml": yaml.safe_dump(invalid_config)},
    )
    assert response.status_code == 422
    assert response.json() == {
        "errors": [{"path": "genetic.composition_rate", "message": "Invalid value"}]
    }
    assert "credential-must-not-leak" not in response.text

    def result_doc(scenario_id, fitness, start, end):
        return {
            "generation_id": 0,
            "scenario_id": scenario_id,
            "scenario": {
                "name": "pod_scenarios",
                "parameters": [{"name": "namespace", "value": "shop"}],
                "origin": "initial",
                "parent_ids": [],
            },
            "cmd": "krkn --scenario pod",
            "log": "logs/scenario.log",
            "returncode": 0,
            "start_time": start,
            "end_time": end,
            "duration_seconds": 10.0,
            "fitness_result": {
                "fitness_score": fitness,
                "scores": [
                    {
                        "id": 1,
                        "fitness_score": fitness / 2,
                        "weighted_score": fitness / 4,
                        "normalized_score": fitness / 100,
                        "query": "up",
                        "query_type": "range",
                    }
                ],
                "health_check_failure_score": 0.25,
                "health_check_response_time_score": 0.5,
                "krkn_failure_score": 0.75,
            },
            "health_check_results": {
                "https://shop.example/health": [
                    {
                        "name": "shop",
                        "timestamp": "2025-01-01T00:00:02+00:00",
                        "response_time": 0.12,
                        "status_code": 200,
                        "success": True,
                        "error": None,
                    },
                    {
                        "name": "shop",
                        "timestamp": "2025-01-01T00:00:05+00:00",
                        "response_time": 0.2,
                        "status_code": 503,
                        "success": False,
                        "error": "unhealthy",
                    },
                ],
            },
        }

    files = {
        "yaml/generation_0/custom-result-name.yaml": yaml.safe_dump(
            result_doc(
                9,
                30.0,
                "2025-01-01T00:00:00+00:00",
                "2025-01-01T00:00:10+00:00",
            )
        ).encode(),
        "yaml/generation_0/custom-baseline-name.yaml": yaml.safe_dump(
            result_doc(
                "baseline",
                15.0,
                "2025-01-01T00:00:00+00:00",
                "2025-01-01T00:01:00+00:00",
            )
        ).encode(),
    }

    def progress(baseline, scenario, *, finalized, completed=0, best=30.0):
        return {
            "completedGenerations": completed,
            "currentGeneration": None if completed else 0,
            "completedScenarios": 1,
            "configuredGenerations": 2,
            "populationSize": 2,
            "bestFitness": best,
            "averageFitness": best,
            "baselineFitness": baseline,
            "fitnessProgression": (
                [{"generation": 0, "best": best, "average": best}] if completed else []
            ),
            "fitnessFinalByScenario": {
                "0:baseline": finalized,
                "0:9": finalized,
            },
            "resultChecksums": {
                "0:baseline": hashlib.sha256(
                    files["yaml/generation_0/custom-baseline-name.yaml"]
                ).hexdigest(),
                "0:9": hashlib.sha256(
                    files["yaml/generation_0/custom-result-name.yaml"]
                ).hexdigest(),
            },
        }

    files["progress.json"] = json.dumps(progress(15.0, 30.0, finalized=False)).encode()

    def commit(current_files, run_status="in_progress"):
        manifest_files = []
        for path, content in current_files.items():
            checksum = hashlib.sha256(content).hexdigest()
            upload = client.put(
                f"/v1/runs/run-1/files/{path}",
                headers={**auth, "X-Checksum-Sha256": checksum},
                content=content,
            )
            assert upload.status_code == 201
            manifest_files.append(
                {"path": path, "sha256": checksum, "size": len(content)}
            )
        response = client.post(
            "/v1/runs/run-1/commit",
            headers=auth,
            json={"status": run_status, "files": manifest_files},
        )
        assert response.status_code == 200

    commit(files)
    summary = client.get("/v1/runs/run-1/summary", headers=auth)
    assert summary.status_code == 200
    assert summary.json() == {
        "artifactStatus": "in_progress",
        "completedGenerations": 0,
        "currentGeneration": 0,
        "completedScenarios": 1,
        "configuredGenerations": 2,
        "populationSize": 2,
        "bestFitness": None,
        "averageFitness": None,
        "baselineFitness": None,
        "fitnessProgression": [],
    }
    index = client.get("/v1/runs/run-1/scenarios", headers=auth)
    assert index.status_code == 200
    scenarios_by_id = {row["scenarioId"]: row for row in index.json()["scenarios"]}
    assert scenarios_by_id == {
        "baseline": {
            "generation": 0,
            "scenarioId": "baseline",
            "scenarioType": "pod_scenarios",
            "outcome": "succeeded",
            "durationSeconds": 10.0,
            "fitnessScore": None,
            "fitnessState": "provisional",
        },
        "9": {
            "generation": 0,
            "scenarioId": "9",
            "scenarioType": "pod_scenarios",
            "outcome": "succeeded",
            "durationSeconds": 10.0,
            "fitnessScore": None,
            "fitnessState": "provisional",
        },
    }
    for direction, expected_ids in (
        ("asc", ["baseline", "9"]),
        ("desc", ["9", "baseline"]),
    ):
        sorted_index = client.get(
            f"/v1/runs/run-1/scenarios?sort=scenarioId&direction={direction}",
            headers=auth,
        )
        assert sorted_index.status_code == 200
        assert [
            row["scenarioId"] for row in sorted_index.json()["scenarios"]
        ] == expected_ids
    generation_index = client.get(
        "/v1/runs/run-1/scenarios?sort=generation&direction=asc", headers=auth
    )
    assert generation_index.status_code == 200
    assert [row["scenarioId"] for row in generation_index.json()["scenarios"]] == [
        "baseline",
        "9",
    ]
    baseline_detail = client.get("/v1/runs/run-1/scenarios/0/baseline", headers=auth)
    assert baseline_detail.json()["fitnessResult"]["fitnessScore"] is None
    assert baseline_detail.json()["fitnessState"] == "provisional"
    detail = client.get("/v1/runs/run-1/scenarios/0/9", headers=auth).json()
    assert detail["fitnessResult"]["fitnessScore"] is None
    assert detail["fitnessState"] == "provisional"
    assert detail["fitnessResult"]["scores"] == [
        {
            "id": 1,
            "rawScore": 15.0,
            "normalizedScore": None,
            "query": "up",
            "queryType": "range",
        }
    ]
    assert [sample["responseTimeSeconds"] for sample in detail["healthChecks"]] == [
        0.12,
        0.2,
    ]
    assert [sample["elapsedSeconds"] for sample in detail["healthChecks"]] == [
        2.0,
        5.0,
    ]

    files["yaml/generation_0/custom-result-name.yaml"] = yaml.safe_dump(
        result_doc(
            9,
            75.0,
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:10+00:00",
        )
    ).encode()
    # A native rewrite before the next manifest commit is never exposed.
    changed_checksum = hashlib.sha256(
        files["yaml/generation_0/custom-result-name.yaml"]
    ).hexdigest()
    assert (
        client.put(
            "/v1/runs/run-1/files/yaml/generation_0/custom-result-name.yaml",
            headers={**auth, "X-Checksum-Sha256": changed_checksum},
            content=files["yaml/generation_0/custom-result-name.yaml"],
        ).status_code
        == 201
    )
    assert client.get("/v1/runs/run-1/summary", headers=auth).status_code == 503
    assert (
        client.get(
            "/v1/runs/run-1/files/yaml/generation_0/custom-result-name.yaml",
            headers=auth,
        ).status_code
        == 503
    )

    files["progress.json"] = json.dumps(
        progress(21.0, 75.0, finalized=True, completed=1, best=75.0)
    ).encode()
    files["yaml/generation_0/custom-baseline-name.yaml"] = yaml.safe_dump(
        result_doc(
            "baseline",
            21.0,
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:01:00+00:00",
        )
    ).encode()
    # Refresh the baseline checksum after its normalized artifact is replaced.
    files["progress.json"] = json.dumps(
        progress(21.0, 75.0, finalized=True, completed=1, best=75.0)
    ).encode()
    commit(files)
    baseline_index = client.get(
        "/v1/runs/run-1/scenarios?search=baseline", headers=auth
    )
    assert baseline_index.status_code == 200
    assert len(baseline_index.json()["scenarios"]) == 1
    baseline_row = baseline_index.json()["scenarios"][0]
    assert baseline_row["fitnessScore"] == 21.0
    assert baseline_row["fitnessState"] == "final"
    baseline_detail = client.get(
        "/v1/runs/run-1/scenarios/0/baseline", headers=auth
    ).json()
    assert baseline_detail["fitnessResult"]["fitnessScore"] == 21.0
    assert baseline_detail["fitnessResult"]["scores"] == [
        {
            "id": 1,
            "rawScore": 10.5,
            "normalizedScore": 0.21,
            "query": "up",
            "queryType": "range",
        }
    ]
    assert baseline_detail["fitnessState"] == "final"
    detail = client.get("/v1/runs/run-1/scenarios/0/9", headers=auth).json()
    assert detail["fitnessResult"]["fitnessScore"] == 75.0
    assert detail["fitnessResult"]["scores"] == [
        {
            "id": 1,
            "rawScore": 37.5,
            "normalizedScore": 0.75,
            "query": "up",
            "queryType": "range",
        }
    ]
    assert detail["fitnessState"] == "final"
    assert client.get("/v1/runs/run-1/summary", headers=auth).json()[
        "fitnessProgression"
    ] == [{"generation": 0, "best": 75.0, "average": 75.0}]

    files["results.json"] = json.dumps(
        {
            "config": {"generations": 2, "population_size": 2},
            "summary": {
                "generations_completed": 1,
                "total_scenarios_executed": 1,
                "best_fitness_score": 75.0,
                "average_fitness_score": 75.0,
            },
            "baseline": {"fitness_score": 21.0},
            "fitness_progression": [{"generation": 0, "best": 75.0, "average": 75.0}],
        }
    ).encode()
    commit(files, "succeeded")
    assert client.get("/v1/runs/run-1/summary", headers=auth).json() == {
        "artifactStatus": "succeeded",
        "completedGenerations": 1,
        "currentGeneration": None,
        "completedScenarios": 1,
        "configuredGenerations": 2,
        "populationSize": 2,
        "bestFitness": 75.0,
        "averageFitness": 75.0,
        "baselineFitness": 21.0,
        "fitnessProgression": [{"generation": 0, "best": 75.0, "average": 75.0}],
    }
    assert (
        client.get("/v1/runs/run-1/scenarios?limit=501", headers=auth).status_code
        == 400
    )


def test_failed_later_generation_preserves_only_completed_fitness(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    auth = TOKEN_HEADERS

    def scenario_doc(generation, scenario_id, total, *, finalized_query):
        return yaml.safe_dump(
            {
                "generation_id": generation,
                "scenario_id": scenario_id,
                "scenario": {"name": "pod_scenarios", "parameters": []},
                "returncode": 0 if generation == 0 else 1,
                "duration_seconds": 1.0,
                "fitness_result": {
                    "fitness_score": total,
                    "scores": [
                        {
                            "id": 1,
                            "fitness_score": total / 2,
                            "normalized_score": 0.5,
                            "query": finalized_query,
                            "query_type": "point",
                        }
                    ],
                },
            }
        ).encode()

    artifacts = {
        "yaml/generation_0/scenario-7.yaml": scenario_doc(
            0, 7, 80, finalized_query="up"
        ),
        "yaml/generation_0/scenario-8.yaml": scenario_doc(
            0, 8, 10, finalized_query="up"
        ),
        "yaml/generation_1/scenario-9.yaml": scenario_doc(
            1, 9, 999, finalized_query="later"
        ),
    }
    files = {}
    checksums = {}
    for path, content in artifacts.items():
        files[path] = content
        generation = int(path.split("/")[1].removeprefix("generation_"))
        scenario_id = path.rsplit("-", 1)[1].split(".", 1)[0]
        checksums[f"{generation}:{scenario_id}"] = hashlib.sha256(content).hexdigest()
    files["progress.json"] = json.dumps(
        {
            "completedGenerations": 1,
            "currentGeneration": 1,
            "completedScenarios": 3,
            "configuredGenerations": 3,
            "populationSize": 2,
            "bestFitness": 999,
            "averageFitness": 999,
            "baselineFitness": 999,
            "fitnessProgression": [
                {"generation": 0, "best": 999, "average": 999},
                {"generation": 1, "best": 1000, "average": 1000},
            ],
            "fitnessFinalByScenario": {
                "0:7": True,
                "0:8": True,
                "1:9": False,
            },
            "resultChecksums": checksums,
        }
    ).encode()
    files["results.json"] = json.dumps(
        {
            "config": {"generations": 3, "population_size": 2},
            "summary": {
                "generations_completed": 1,
                "total_scenarios_executed": 3,
                "best_fitness_score": 999,
                "average_fitness_score": 999,
            },
            "baseline": {"fitness_score": 999},
            "fitness_progression": [
                {"generation": 0, "best": 999, "average": 999},
                {"generation": 1, "best": 1000, "average": 1000},
            ],
        }
    ).encode()

    manifest_files = []
    for path, content in files.items():
        checksum = hashlib.sha256(content).hexdigest()
        assert (
            client.put(
                f"/v1/runs/run-failed/files/{path}",
                headers={**auth, "X-Checksum-Sha256": checksum},
                content=content,
            ).status_code
            == 201
        )
        manifest_files.append({"path": path, "sha256": checksum, "size": len(content)})
    assert (
        client.post(
            "/v1/runs/run-failed/commit",
            headers=auth,
            json={"status": "in_progress", "files": manifest_files},
        ).status_code
        == 200
    )
    in_progress = client.get("/v1/runs/run-failed/summary", headers=auth).json()
    assert in_progress == {
        "artifactStatus": "in_progress",
        "completedGenerations": 1,
        "currentGeneration": 1,
        "completedScenarios": 3,
        "configuredGenerations": 3,
        "populationSize": 2,
        "bestFitness": 80,
        "averageFitness": 45,
        "baselineFitness": None,
        "fitnessProgression": [{"generation": 0, "best": 80, "average": 45}],
    }
    partial_rows = {
        row["scenarioId"]: row
        for row in client.get("/v1/runs/run-failed/scenarios", headers=auth).json()[
            "scenarios"
        ]
    }
    assert partial_rows["7"]["fitnessScore"] == 80
    assert partial_rows["9"]["fitnessScore"] is None
    assert partial_rows["9"]["fitnessState"] == "provisional"
    assert (
        client.post(
            "/v1/runs/run-failed/commit",
            headers=auth,
            json={"status": "failed", "files": manifest_files},
        ).status_code
        == 200
    )

    summary = client.get("/v1/runs/run-failed/summary", headers=auth).json()
    assert summary == {
        "artifactStatus": "failed",
        "completedGenerations": 1,
        "currentGeneration": None,
        "completedScenarios": 3,
        "configuredGenerations": 3,
        "populationSize": 2,
        "bestFitness": 80,
        "averageFitness": 45,
        "baselineFitness": None,
        "fitnessProgression": [{"generation": 0, "best": 80, "average": 45}],
    }
    rows = {
        row["scenarioId"]: row
        for row in client.get("/v1/runs/run-failed/scenarios", headers=auth).json()[
            "scenarios"
        ]
    }
    assert rows["7"]["fitnessScore"] == 80
    assert rows["9"]["fitnessScore"] is None
    assert rows["9"]["fitnessState"] == "unfinalized"
    detail = client.get("/v1/runs/run-failed/scenarios/1/9", headers=auth).json()
    assert detail["fitnessResult"]["fitnessScore"] is None
    assert detail["fitnessResult"]["scores"] == [
        {
            "id": 1,
            "rawScore": 499.5,
            "normalizedScore": None,
            "query": "later",
            "queryType": "point",
        }
    ]
    assert detail["fitnessState"] == "unfinalized"


def test_corrupt_committed_yaml_is_reported_as_bad_gateway(tmp_path: Path):
    client = TestClient(create_app(tmp_path, "service-token"))
    payload = b"generation_id: ["
    checksum = hashlib.sha256(payload).hexdigest()
    assert (
        client.put(
            "/v1/runs/run-1/files/yaml/generation_0/custom.yaml",
            headers={**TOKEN_HEADERS, "X-Checksum-Sha256": checksum},
            content=payload,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/runs/run-1/commit",
            headers=TOKEN_HEADERS,
            json={
                "status": "in_progress",
                "files": [
                    {
                        "path": "yaml/generation_0/custom.yaml",
                        "sha256": checksum,
                        "size": len(payload),
                    }
                ],
            },
        ).status_code
        == 200
    )
    response = client.get("/v1/runs/run-1/summary", headers=TOKEN_HEADERS)
    assert response.status_code == 502
    assert response.json()["detail"] == "invalid committed artifact"
