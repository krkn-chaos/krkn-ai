"""Unit tests for the fitness catalog and its recommender."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from krkn_ai.models.config import FitnessFunctionItem, FitnessFunctionType
from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.utils.catalog import (
    BASE_CATALOG,
    CatalogEntry,
    FitnessCategory,
    Scope,
    get_base_catalog,
    recommend_fitness_queries,
)


def _all_required_metrics():
    metrics = set()
    for entry in BASE_CATALOG:
        metrics.update(entry.requires)
    return metrics


def _components(namespace_names):
    """Minimal stand-in for ClusterComponents.get_active_components()."""
    active = SimpleNamespace(
        namespaces=[SimpleNamespace(name=n) for n in namespace_names]
    )
    return SimpleNamespace(get_active_components=lambda: active)


class _FakeProm:
    """Fake KrknPrometheus: canned metric list + query-result rule."""

    def __init__(self, metrics, query_rule=None, metrics_raises=False):
        self._metrics = list(metrics)
        self._rule = query_rule or (lambda q: [{"value": [0, "1"]}])  # 1 series
        self._metrics_raises = metrics_raises
        self.prom_cli = SimpleNamespace(all_metrics=self._all_metrics)

    def _all_metrics(self):
        if self._metrics_raises:
            raise RuntimeError("prometheus down")
        return self._metrics

    def process_query(self, query):
        return self._rule(query)


class TestBaseCatalog:
    """Structural checks over the shipped base catalog."""

    def test_catalog_non_empty(self):
        assert len(get_base_catalog()) > 0

    def test_get_base_catalog_returns_base_catalog(self):
        assert get_base_catalog() is BASE_CATALOG

    def test_keys_are_unique(self):
        keys = [entry.key for entry in BASE_CATALOG]
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("entry", BASE_CATALOG, ids=lambda e: e.key)
    def test_entry_is_well_formed(self, entry: CatalogEntry):
        assert 0.0 <= entry.default_weight <= 1.0
        assert isinstance(entry.type, FitnessFunctionType)
        assert isinstance(entry.category, FitnessCategory)
        assert isinstance(entry.scope, Scope)
        assert entry.requires, "requires must list at least one metric name"
        assert entry.key and entry.name and entry.query_template

    @pytest.mark.parametrize("entry", BASE_CATALOG, ids=lambda e: e.key)
    def test_scope_matches_placeholder(self, entry: CatalogEntry):
        # namespace-scoped queries carry $ns; cluster-scoped ones do not.
        if entry.scope is Scope.namespace:
            assert "$ns" in entry.query_template
        else:
            assert "$ns" not in entry.query_template


class TestCatalogEntryBehavior:
    """Placeholder resolution and config-type emission."""

    def _namespace_entry(self) -> CatalogEntry:
        return next(e for e in BASE_CATALOG if e.scope is Scope.namespace)

    def test_resolved_query_substitutes_namespace(self):
        entry = self._namespace_entry()
        resolved = entry.resolved_query("robot-shop")
        assert "$ns" not in resolved
        assert 'namespace="robot-shop"' in resolved

    def test_resolved_query_leaves_range_placeholder(self):
        # $range$ must survive for the runtime FitnessCalculator to substitute.
        entry = next(e for e in BASE_CATALOG if "$range$" in e.query_template)
        assert "$range$" in entry.resolved_query("robot-shop")

    def test_resolved_query_without_namespace_is_unchanged(self):
        entry = self._namespace_entry()
        assert entry.resolved_query() == entry.query_template

    @pytest.mark.parametrize("entry", BASE_CATALOG, ids=lambda e: e.key)
    def test_to_fitness_item_emits_valid_config_type(self, entry: CatalogEntry):
        item = entry.to_fitness_item("robot-shop")
        assert isinstance(item, FitnessFunctionItem)
        assert item.type == entry.type
        assert item.weight == entry.default_weight
        assert item.query == entry.resolved_query("robot-shop")


class TestCatalogEntryValidation:
    """The [0,1] weight constraint mirrors FitnessFunctionItem."""

    def _kwargs(self, **overrides):
        base = dict(
            key="test",
            category=FitnessCategory.availability,
            name="Test",
            query_template='sum(up{namespace="$ns"})',
            requires=["up"],
        )
        base.update(overrides)
        return base

    @pytest.mark.parametrize("weight", [-0.1, 1.1])
    def test_weight_out_of_range_rejected(self, weight):
        with pytest.raises(ValidationError):
            CatalogEntry(**self._kwargs(default_weight=weight))

    def test_weight_in_range_accepted(self):
        entry = CatalogEntry(**self._kwargs(default_weight=0.5))
        assert entry.default_weight == 0.5


class TestRecommendFitnessQueries:
    """The dynamic layer: existence gate, scoping, shape validation."""

    def test_all_present_single_series_all_enabled(self):
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        # 4 namespace-scoped x 1 ns + 2 cluster-scoped = 6 items, all enabled
        assert len(results) == 6
        assert all(r["enabled"] for r in results)
        # equal-split weights sum to ~1
        assert abs(sum(r["weight"] for r in results) - 1.0) < 0.01

    def test_missing_metric_is_gated_out(self):

        metrics = _all_required_metrics() - {
            "container_cpu_cfs_throttled_periods_total",
            "container_cpu_cfs_periods_total",
        }
        results = recommend_fitness_queries(_components(["demo"]), _FakeProm(metrics))
        cpu = [r for r in results if r["name"].startswith("cpu-throttle")]
        assert cpu and all(not r["enabled"] for r in cpu)
        assert "not scraped" in cpu[0]["reason"]
        # everything else stays enabled
        others = [r for r in results if not r["name"].startswith("cpu-throttle")]
        assert all(r["enabled"] for r in others)

    def test_zero_series_but_present_is_kept(self):

        def rule(q):
            return [] if "OOMKilled" in q else [{"value": [0, "1"]}]

        results = recommend_fitness_queries(
            _components(["demo"]), _FakeProm(_all_required_metrics(), rule)
        )
        oom = next(r for r in results if r["name"].startswith("oom-kills"))
        assert oom["enabled"] is True

    def test_multi_series_is_rejected(self):

        def rule(q):
            return [{"value": [0, "1"]}, {"value": [0, "2"]}] if "apiserver" in q else [
                {"value": [0, "1"]}
            ]

        results = recommend_fitness_queries(
            _components(["demo"]), _FakeProm(_all_required_metrics(), rule)
        )
        api = next(r for r in results if r["name"] == "apiserver-errors")
        assert api["enabled"] is False
        assert "needs aggregation" in api["reason"]

    def test_namespace_scoping_expands_per_namespace(self):
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["a", "b"]), prom)
        restarts = [r for r in results if r["name"].startswith("pod-restarts")]
        assert {r["name"] for r in restarts} == {"pod-restarts:a", "pod-restarts:b"}
        assert 'namespace="a"' in restarts[0]["query"] or 'namespace="b"' in restarts[0]["query"]
        node = [r for r in results if r["name"] == "node-pressure"]
        assert len(node) == 1  # cluster-scoped, no namespace suffix

    def test_query_keeps_range_placeholder_for_runtime(self):
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        restarts = next(r for r in results if r["name"] == "pod-restarts:demo")
        assert "$range$" in restarts["query"]  # FitnessCalculator substitutes at runtime

    def test_emitted_query_is_wrapped_against_empty_result(self):
        # a label filter matching 0 series must not crash the runtime
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        for r in results:
            assert r["query"].endswith(") or vector(0)"), r["query"]

    def test_prometheus_unreachable_returns_empty(self):
        prom = _FakeProm(_all_required_metrics(), metrics_raises=True)
        assert recommend_fitness_queries(_components(["demo"]), prom) == []


class TestTemplateWiring:
    """discover template renders dynamic items, else the static default."""

    def _data(self):
        return {"namespaces": []}

    def test_enabled_items_rendered(self):
        fitness_queries = [
            {
                "name": "pod-restarts:demo",
                "query": 'sum(increase(kube_pod_container_status_restarts_total{namespace="demo"}[$range$]))',
                "type": "range",
                "weight": 0.5,
                "enabled": True,
                "reason": "",
            },
            {
                "name": "cpu-throttle:demo",
                "query": "max(...)",
                "type": "range",
                "weight": 1.0,
                "enabled": False,
                "reason": "metric(s) not scraped: container_cpu_cfs_periods_total",
            },
        ]
        out = create_krkn_ai_template(
            "/tmp/kubeconfig", self._data(), fitness_queries=fitness_queries
        )
        assert "items:" in out
        assert "pod-restarts:demo" in out
        assert "kube_pod_container_status_restarts_total" in out
        # disabled entry appears commented with its reason
        assert "# cpu-throttle:demo (metric(s) not scraped" in out

    def test_static_default_when_no_fitness_queries(self):
        out = create_krkn_ai_template("/tmp/kubeconfig", self._data())
        assert "sum(kube_pod_container_status_restarts_total)" in out
        assert "items:" not in out
