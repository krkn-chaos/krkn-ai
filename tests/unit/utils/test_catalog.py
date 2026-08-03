"""Unit tests for the fitness catalog and its recommender."""

from types import SimpleNamespace

import pytest

from krkn_ai.models.config import FitnessFunctionItem, FitnessFunctionType
from krkn_ai.templates.generator import create_krkn_ai_template
from krkn_ai.utils.fs import _merge_fitness_items
from krkn_ai.utils.catalog import (
    BASE_CATALOG,
    CatalogEntry,
    FitnessCategory,
    Scope,
    _assign_weights,
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

    def test_keys_are_unique(self):
        keys = [entry.key for entry in BASE_CATALOG]
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("entry", BASE_CATALOG, ids=lambda e: e.key)
    def test_entry_is_well_formed(self, entry: CatalogEntry):
        assert entry.key and entry.query_template
        assert isinstance(entry.type, FitnessFunctionType)
        assert isinstance(entry.scope, Scope)
        if entry.category is not None:
            assert isinstance(entry.category, FitnessCategory)

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
    """Fields are optional per key and weights are not capped."""

    def test_minimal_entry_valid(self):
        entry = CatalogEntry(key="x", query_template="sum(up)")
        assert entry.category is None and entry.name is None and entry.requires == []

    def test_weight_any_value_accepted(self):
        entry = CatalogEntry(key="x", query_template="sum(up)", default_weight=5.0)
        assert entry.default_weight == 5.0


class TestRecommendFitnessQueries:
    """The dynamic layer: existence gate, scoping, shape validation, weights."""

    def test_all_present_single_series_all_enabled(self):
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        # namespace-scoped x 1 ns + cluster-scoped, so the count tracks the catalog
        ns_scoped = sum(1 for e in BASE_CATALOG if e.scope is Scope.namespace)
        cluster_scoped = sum(1 for e in BASE_CATALOG if e.scope is Scope.cluster)
        assert len(results) == ns_scoped + cluster_scoped
        assert all(r["enabled"] for r in results)
        # no history -> equal split, weights sum to ~1
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
            return (
                [{"value": [0, "1"]}, {"value": [0, "2"]}]
                if "apiserver" in q
                else [{"value": [0, "1"]}]
            )

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
        assert (
            'namespace="a"' in restarts[0]["query"]
            or 'namespace="b"' in restarts[0]["query"]
        )
        node = [r for r in results if r["name"] == "node-pressure"]
        assert len(node) == 1  # cluster-scoped, no namespace suffix

    def test_query_keeps_range_placeholder_for_runtime(self):
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        restarts = next(r for r in results if r["name"] == "pod-restarts:demo")
        assert "$range$" in restarts["query"]  # substituted at runtime

    def test_emitted_query_is_wrapped_against_empty_result(self):
        # a label filter matching 0 series must not crash the runtime
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        for r in results:
            assert r["query"].endswith(") or vector(0)"), r["query"]

    def test_prometheus_unreachable_returns_empty(self):
        prom = _FakeProm(_all_required_metrics(), metrics_raises=True)
        assert recommend_fitness_queries(_components(["demo"]), prom) == []

    def test_equal_weights_when_seeds_default(self):
        # catalog seeds all default (1.0) -> equal split
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        weights = [r["weight"] for r in results if r["enabled"]]
        assert max(weights) - min(weights) < 0.001

    def test_weights_normalize_catalog_seeds(self):
        # user-set seed weights are respected (normalized), not overridden
        enabled = [{"weight": 3.0}, {"weight": 1.0}]
        _assign_weights(enabled)
        assert enabled[0]["weight"] == 0.75
        assert enabled[1]["weight"] == 0.25

    def test_learned_weights_seed_priority(self):
        # a learned weight for one query dominates the normalized result
        prom = _FakeProm(_all_required_metrics())
        results = recommend_fitness_queries(_components(["demo"]), prom)
        target = next(r for r in results if r["enabled"])["query"]
        learned = {target: 100.0}  # everything else keeps default seed 1.0
        weighted = recommend_fitness_queries(
            _components(["demo"]), prom, learned_weights=learned
        )
        picked = next(r for r in weighted if r["query"] == target)
        others = [r for r in weighted if r["enabled"] and r["query"] != target]
        assert all(picked["weight"] > o["weight"] for o in others)


class TestMergeFitnessItems:
    """merge unions new fitness items and keeps the user's existing ones."""

    def test_adds_enabled_items_and_keeps_existing(self):
        raw = {
            "fitness_function": {
                "items": [{"query": "existing", "type": "range", "weight": 0.5}]
            }
        }
        fitness_queries = [
            {"query": "new-one", "type": "range", "weight": 0.3, "enabled": True},
            {"query": "disabled", "type": "range", "weight": 0.0, "enabled": False},
            {"query": "existing", "type": "range", "weight": 0.9, "enabled": True},
        ]
        _merge_fitness_items(raw, fitness_queries)
        queries = [i["query"] for i in raw["fitness_function"]["items"]]
        assert queries == ["existing", "new-one"]  # existing kept, disabled skipped

    def test_no_fitness_queries_is_noop(self):
        raw = {"cluster_components": {}}
        _merge_fitness_items(raw, None)
        assert "fitness_function" not in raw


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
