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
    assert "Krkn-AI Run Report" in html
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find("title").text.startswith("Krkn-AI Report:")
    # Ensure all default tabs are present
    assert soup.find(id="tab-dashboard")
    assert soup.find(id="tab-fitness")
    assert soup.find(id="tab-health")
    assert soup.find(id="tab-detailed")
    assert soup.find(id="tab-anomalies")
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
            "krkn_failure_score": [1],
        }
    )

    html = generate_html_report(
        df_all=df_results,
        run_uuid="test-uuid",
        output_dir="/tmp/out",
        delta_baseline=0.5,
        delta_prev=0.2,
        global_services=["svc1"],
        filtered_scenario_ids=["1"],
    )
    assert "scen1" in html
    assert "test-uuid" in html


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


def test_generate_html_report_includes_configuration():
    html = generate_html_report(
        pd.DataFrame(),
        config_data={
            "fitness_function": {"query": "up"},
            "scenario": {"pod-scenarios": {"enable": True}},
        },
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find(id="tab-config")
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
            "__PROMETHEUS_TOKEN": "do-not-leak",
            "health_checks": {"headers": {"__AUTHORIZATION": "Bearer secret"}},
        },
        health_check_recos=[
            {
                "name": "discovered",
                "__URL": "https://user:pass@example.test/ready",
                "reason": "unreachable",
            }
        ],
    )
    assert "do-not-leak" not in html
    assert "Bearer secret" not in html
    assert "https://user:pass@example.test/ready" not in html
    assert "***" in html


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
