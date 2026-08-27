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
    # Ensure all tabs are present
    assert soup.find(id="tab-dashboard")
    assert soup.find(id="tab-health")
    assert soup.find(id="tab-detailed")
    assert soup.find(id="tab-anomalies")
    assert soup.find(id="tab-logs")
    assert soup.find(id="tab-config")
    assert soup.find(id="tab-failed")


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


def test_generate_html_report_includes_logs_and_configuration():
    html = generate_html_report(
        pd.DataFrame(),
        df_logs=[
            {
                "scenario_id": 3,
                "job_status": True,
                "scenario_type": "pod-kill",
                "duration": "4s",
                "exit_status": 0,
                "raw_text": "raw scenario log",
            }
        ],
        config_data={
            "fitness_function": {"query": "up"},
            "scenario": {"pod-scenarios": {"enable": True}},
        },
        scen_id_to_name={"3": "pod-scenarios"},
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find(id="tab-logs")
    assert soup.find(id="tab-config")
    assert "raw scenario log" in html
    assert "pod-scenarios" in html
    assert "up" in html


def test_generate_html_report_includes_optional_lineage_section():
    lineage = pd.DataFrame(
        {
            "scenario_id": ["1", "2"],
            "scenario_uuid": ["root", "child"],
            "parent_ids": [[], ["root"]],
            "generation": [0, 1],
            "origin": ["initial", "parameter_mutation"],
            "fitness_score": [1.0, 2.5],
        }
    )
    html = generate_html_report(pd.DataFrame(), df_lineage=lineage)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find(id="tab-lineage")
    assert "parameter_mutation" in html
    assert "child" in html


def test_generate_html_report_redacts_configuration_secrets():
    html = generate_html_report(
        pd.DataFrame(),
        config_data={
            "prometheus_token": "do-not-leak",
            "health_checks": {"headers": {"Authorization": "Bearer secret"}},
        },
    )
    assert "do-not-leak" not in html
    assert "Bearer secret" not in html
    assert "***" in html


def test_generate_html_report_redacts_raw_logs_and_recommendation_urls():
    html = generate_html_report(
        pd.DataFrame(),
        df_logs=[
            {
                "scenario_id": 1,
                "job_status": False,
                "raw_text": "Authorization: Bearer log-secret\nurl=https://user:pass@example.test/health?token=url-secret",
            }
        ],
        config_data={
            "health_checks": {
                "applications": [
                    {
                        "name": "service",
                        "url": "https://user:pass@example.test/health?token=config-secret",
                        "headers": {"Authorization": "Bearer header-secret"},
                    }
                ]
            }
        },
        health_check_recos=[
            {
                "name": "discovered",
                "url": "https://user:pass@example.test/ready?token=reco-secret",
                "reason": "unreachable",
            }
        ],
    )
    for secret in (
        "log-secret",
        "url-secret",
        "config-secret",
        "header-secret",
        "reco-secret",
    ):
        assert secret not in html
    assert "Authorization: ***" in html
    assert "https://***@example.test/" in html
    assert "token=***" in html


def test_generate_html_report_handles_lineage_without_origin_data():
    lineage = pd.DataFrame(
        {
            "scenario_id": ["1"],
            "scenario_uuid": ["child"],
            "parent_ids": [[]],
            "generation": [0],
            "origin": [None],
            "fitness_score": [2.5],
        }
    )
    html = generate_html_report(pd.DataFrame(), df_lineage=lineage)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find(id="tab-lineage")
    assert "Lineage origin data not recorded for this run." in html
    assert "Origin Distribution" not in html
