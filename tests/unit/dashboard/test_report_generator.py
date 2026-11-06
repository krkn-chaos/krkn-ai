import pandas as pd
from bs4 import BeautifulSoup

from krkn_ai.dashboard.report_generator import (
    generate_html_report,
    _df_table,
    _cards,
    _sec,
    _subsec,
    _na,
)


def test_generate_html_report_empty():
    df_results = pd.DataFrame()
    html = generate_html_report(df_results)
    assert isinstance(html, str)
    assert "Krkn-AI Dashboard Report" in html
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find("title").text.startswith("Krkn-AI Report:")
    # Ensure all default tabs are present
    assert soup.find(id="tab-dashboard")
    assert soup.find(id="tab-fitness")
    assert soup.find(id="tab-health")
    assert soup.find(id="tab-detailed")
    assert soup.find(id="tab-anomalies")
    assert soup.find(id="tab-logs")
    assert soup.find(id="tab-config")
    assert soup.find(id="tab-failed")
    # Lineage is omitted when no lineage data provided
    assert soup.find(id="tab-lineage") is None


def test_generate_html_report_with_data():
    df_results = pd.DataFrame(
        {
            "scenario_id": ["1", "baseline"],
            "generation_id": [0, -1],
            "fitness_score": [1.0, 0.5],
            "duration_seconds": [10, 5],
            "health_check_failure_score": [0, 0],
            "health_check_response_time_score": [1, 1],
            "krkn_failure_score": [1, 1],
            "scenario": ["scen1", "baseline"],
        }
    )
    df_health = pd.DataFrame(
        {
            "scenario_id": ["1"],
            "component_name": ["svc1"],
            "average_response_time": [0.1],
            "max_response_time": [0.2],
            "failure_count": [0],
            "success_count": [10],
        }
    )
    df_details = pd.DataFrame(
        {
            "scenario_id": ["1"],
            "service": ["svc1"],
            "seconds_into_scenario": [1.0],
            "response_time": [0.1],
            "success": [True],
            "timestamp": ["2026-05-19T10:00:00Z"],
            "status_code": [200],
            "error": ["None"],
        }
    )
    df_failed = pd.DataFrame(
        {
            "scenario_id": ["2"],
            "scenario": ["scen2"],
            "krkn_failure_score": [-1],
        }
    )

    html = generate_html_report(
        df_results=df_results.head(1),
        df_health=df_health,
        df_results_all=df_results,
        df_details=df_details,
        df_failed=df_failed,
        global_services=["svc1"],
        filtered_scenario_ids=["1"],
    )
    assert "scen1" in html
    assert "scen2" in html
    assert "svc1" in html


def test_df_table():
    df = pd.DataFrame({"A": [1, 2], "B": ["x", "y"]})
    html = _df_table(df)
    assert "<table" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_df_table_empty():
    html = _df_table(None)
    assert "No data available." in html
    html = _df_table(pd.DataFrame())
    assert "No data available." in html


def test_cards():
    html = _cards([("Metric", 10)])
    assert '<div class="metric-card">' in html
    assert '<span class="metric-val">10</span>' in html
    assert '<span class="metric-lbl">Metric</span>' in html


def test_sec():
    html = _sec("Title", "<p>Content</p>", "tab1")
    assert '<section class="report-section" id="tab1">' in html
    assert "<h2>Title</h2>" in html
    assert "<p>Content</p>" in html


def test_subsec():
    html = _subsec("Title", "<p>Content</p>")
    assert '<div class="subsec">' in html
    assert "<h3>Title</h3>" in html
    assert "<p>Content</p>" in html


def test_na():
    html = _na("Custom Msg")
    assert "<p class='muted'>Custom Msg</p>" in html


def test_generate_html_report_with_logs_config_and_lineage():
    df_results = pd.DataFrame(
        {
            "scenario_id": ["1"],
            "generation_id": [0],
            "fitness_score": [1.0],
            "duration_seconds": [10],
            "health_check_failure_score": [0],
            "health_check_response_time_score": [1],
            "krkn_failure_score": [1],
            "scenario": ["scen1"],
        }
    )
    df_logs = [
        {
            "scenario_id": "1",
            "job_status": True,
            "run_uuid": "test-uuid-123",
            "timestamp": "2026-05-19T10:00:00Z",
            "scenario_type": "pod_scenario",
            "cluster_version": "1.30",
            "total_node_count": 3,
            "exit_status": 0,
            "duration": "10s",
            "raw_text": "Sample chaos engine output log line 1\nline 2",
        }
    ]
    config_data = {
        "fitness_function": {
            "query": "node_cpu_utilization",
            "include_krkn_failure": True,
        },
        "health_checks": {
            "applications": [
                {
                    "name": "cart-service",
                    "url": "http://cart:8080/health",
                    "status_code": 200,
                    "timeout": 4,
                    "interval": 2,
                }
            ]
        },
        "scenario": {"pod_scenario": {"enable": True}},
        "cluster_components": {
            "namespaces": [{"name": "default"}],
            "nodes": [{"name": "node-1"}],
        },
    }
    df_lineage = pd.DataFrame(
        {
            "scenario_id": ["1", "2"],
            "generation": [0, 1],
            "origin": ["initial", "crossover"],
            "fitness_score": [0.8, 1.2],
            "parent_ids": [[], ["1"]],
        }
    )

    html = generate_html_report(
        df_results=df_results,
        df_logs=df_logs,
        config_data=config_data,
        df_lineage=df_lineage,
        scen_id_to_name={"1": "Pod Chaos 1"},
    )

    soup = BeautifulSoup(html, "html.parser")
    # Verify tabs present
    assert soup.find(id="tab-logs") is not None
    assert soup.find(id="tab-config") is not None
    assert soup.find(id="tab-lineage") is not None

    # Verify logs content
    assert "Scenario 1 – Pod Chaos 1" in html
    assert "test-uuid-123" in html
    assert "Sample chaos engine output log line 1" in html

    # Verify config content
    assert "node_cpu_utilization" in html
    assert "cart-service" in html
    assert "http://cart:8080/health" in html

    # Verify lineage content
    assert "Origin Distribution" in html
    assert "GA Strategy per Generation" in html
    assert "Crossover" in html
