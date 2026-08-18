import os

import pytest
import streamlit as st

from krkn_ai.dashboard.data_loader import (
    load_fitness_items,
    load_health_check_recos,
    map_slo_columns,
    slo_columns,
)

CONFIG = """
fitness_function:
  include_krkn_failure: true
  # Fitness queries validated against the cluster's Prometheus.
  items:
  # pod-restarts:default
  - query: '(sum(increase(kube_pod_container_status_restarts_total{namespace="default"}[$range$]))) or vector(0)'
    type: range
    weight: 0.5
  # node-pressure
  - query: '(sum(kube_node_status_condition{condition=~"MemoryPressure|DiskPressure|PIDPressure", status="true"})) or vector(0)'
    type: range
    weight: 0.5
  # etcd-no-leader (metric(s) not scraped: etcd_server_has_leader)
  # - query: '(sum(etcd_server_has_leader == bool 0)) or vector(0)'
  #   type: range

health_checks:
  stop_watcher_on_failure: false
  applications:
  - name: "cart"
    url: "http://1.2.3.4:80/health"
  # (no probe, unreachable)
  # - name: "payment"
  #   url: "http://1.2.3.4:81/"
  # (unreachable)
  # - name: "user"
  #   url: "http://1.2.3.4:82/health"

scenario:
  pod-scenarios:
    enable: true
"""


@pytest.fixture(autouse=True)
def clear_cache():
    st.cache_data.clear()


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "krkn-ai.yaml").write_text(CONFIG)
    return str(tmp_path)


def test_load_fitness_items_reads_enabled_and_rejected(run_dir):
    items = load_fitness_items(run_dir)
    assert [item["name"] for item in items] == [
        "pod-restarts:default",
        "node-pressure",
        "etcd-no-leader",
    ]
    assert [item["enabled"] for item in items] == [True, True, False]
    assert items[0]["weight"] == 0.5
    assert items[0]["type"] == "range"
    assert items[2]["reason"] == "metric(s) not scraped: etcd_server_has_leader"
    assert items[2]["query"].startswith("(sum(etcd_server_has_leader")


def test_load_fitness_items_labels_from_catalog(run_dir):
    """Names still resolve when the config carries no comments (merged configs)."""
    stripped = "\n".join(
        line for line in CONFIG.splitlines() if not line.strip().startswith("#")
    )
    with open(os.path.join(run_dir, "krkn-ai.yaml"), "w") as f:
        f.write(stripped)

    items = load_fitness_items(run_dir)
    assert [item["name"] for item in items] == ["pod-restarts:default", "node-pressure"]
    assert items[0]["category"] == "availability"
    assert items[1]["category"] == "node"


def test_load_health_check_recos(run_dir):
    recos = load_health_check_recos(run_dir)
    assert recos == [
        {
            "name": "payment",
            "url": "http://1.2.3.4:81/",
            "reason": "no probe, unreachable",
        },
        {
            "name": "user",
            "url": "http://1.2.3.4:82/health",
            "reason": "unreachable",
        },
    ]


def test_map_slo_columns_requires_matching_counts(run_dir):
    items = load_fitness_items(run_dir)
    assert slo_columns(["slo_10", "fitness_score", "slo_2"]) == ["slo_2", "slo_10"]

    mapping = map_slo_columns(items, ["slo_0", "slo_1", "fitness_score"])
    assert [item["name"] for item in mapping.values()] == [
        "pod-restarts:default",
        "node-pressure",
    ]
    assert map_slo_columns(items, ["slo_0", "slo_1", "slo_2"]) == {}
    assert map_slo_columns(items, []) == {}
