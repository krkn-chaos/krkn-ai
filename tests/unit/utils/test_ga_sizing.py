"""
Genetic algorithm sizing tests
"""

from unittest.mock import patch

from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Container,
    Namespace,
    Node,
    Pod,
    PVC,
    Service,
    ServicePort,
)
from krkn_ai.utils import ga_sizing
from krkn_ai.utils.ga_sizing import recommend_genetic_params
from krkn_ai.utils.rng import rng


def build_cluster(namespaces=1, pods=2, nodes=1, pvcs=1, services=0):
    ns_list = []
    for i in range(namespaces):
        ns_list.append(
            Namespace(
                name=f"ns-{i}",
                pods=[
                    Pod(
                        name=f"pod-{i}-{j}",
                        labels={"app": f"app-{i}-{j}"},
                        containers=[Container(name="main")],
                    )
                    for j in range(pods)
                ],
                pvcs=[PVC(name=f"pvc-{i}-{k}") for k in range(pvcs)],
                services=[
                    Service(name=f"svc-{i}-{k}", ports=[ServicePort(port=80 + k)])
                    for k in range(services)
                ],
            )
        )
    node_list = [
        Node(name=f"node-{i}", labels={"kubernetes.io/hostname": f"node-{i}"})
        for i in range(nodes)
    ]
    return ClusterComponents(namespaces=ns_list, nodes=node_list)


class TestTier:
    """Tier boundaries on distinct target count"""

    def test_tier_boundaries(self):
        assert ga_sizing._tier(1) == "small"
        assert ga_sizing._tier(ga_sizing.SMALL_MAX_TARGETS) == "small"
        assert ga_sizing._tier(ga_sizing.SMALL_MAX_TARGETS + 1) == "medium"
        assert ga_sizing._tier(ga_sizing.MEDIUM_MAX_TARGETS) == "medium"
        assert ga_sizing._tier(ga_sizing.MEDIUM_MAX_TARGETS + 1) == "large"


class TestCountTargetSpace:
    """Exact (non-sampled) target counting"""

    def test_every_scenario_spec_has_a_registered_counter(self):
        from krkn_ai.models.scenario.factory import scenario_specs

        names = {name for name, _ in scenario_specs}
        assert names == set(ga_sizing.TARGET_SPACE_COUNTERS.keys())

    def test_node_only_cluster_scales_with_node_count(self):
        """Regression: node-targeting scenarios (network-chaos, node-*-hog)
        must contribute to the total even when the cluster has no services
        or PVCs, and the total must grow as nodes are added."""
        small = build_cluster(namespaces=1, pods=1, nodes=5, pvcs=0)
        large = build_cluster(namespaces=1, pods=1, nodes=50, pvcs=0)

        small_targets, _ = ga_sizing.count_target_space(small, "kubeconfig.yaml")
        large_targets, _ = ga_sizing.count_target_space(large, "kubeconfig.yaml")

        assert large_targets > small_targets

    def test_service_only_cluster_scales_with_service_count(self):
        """Regression: syn-flood targets services, not nodes/pods. A cluster
        whose only variety is in service count must not be sized as flat."""
        few_services = build_cluster(namespaces=1, pods=1, nodes=1, pvcs=0, services=2)
        many_services = build_cluster(
            namespaces=1, pods=1, nodes=1, pvcs=0, services=40
        )

        few_targets, _ = ga_sizing.count_target_space(few_services, "kubeconfig.yaml")
        many_targets, _ = ga_sizing.count_target_space(many_services, "kubeconfig.yaml")

        assert many_targets > few_targets

    def test_deterministic_and_rng_free(self):
        """Counting is pure introspection over cluster_components: it must
        never consume entropy from the shared global RNG, and repeated
        calls on the same cluster must return identical results."""
        cluster = build_cluster(namespaces=3, pods=4, nodes=3, services=2)

        rng.set_seed(42)
        draws_before = [rng.random() for _ in range(3)]

        rng.set_seed(42)
        results = [
            ga_sizing.count_target_space(cluster, "kubeconfig.yaml") for _ in range(5)
        ]
        draws_after = [rng.random() for _ in range(3)]

        assert all(r == results[0] for r in results)
        assert draws_before == draws_after


class TestRecommendGeneticParams:
    """Profile produced for a discovered cluster"""

    def test_returns_profile_for_real_cluster(self):
        cluster = build_cluster(namespaces=2, pods=3, nodes=2)
        profile = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert profile is not None
        assert profile["generations"] > 0
        assert profile["population_size"] >= 2
        assert profile["exploration_saturation"] == ga_sizing.EXPLORATION_SATURATION
        assert profile["generation_saturation"] == ga_sizing.GENERATION_SATURATION

    def test_same_cluster_sizes_the_same_way(self):
        cluster = build_cluster(namespaces=2, pods=3, nodes=2)
        first = recommend_genetic_params(cluster, "kubeconfig.yaml")
        second = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert first == second

    def test_tournament_size_never_exceeds_population(self):
        cluster = build_cluster(namespaces=3, pods=4, nodes=3)
        profile = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert profile["tournament_size"] <= profile["population_size"]
        assert profile["tournament_size"] >= 2

    def test_small_cluster_skips_composition_and_injection(self):
        cluster = build_cluster(namespaces=1, pods=1, nodes=1, pvcs=0)
        with patch.object(ga_sizing, "count_target_space", return_value=(10, 5)):
            profile = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert profile["composition_rate"] == 0.0
        assert profile["population_injection_rate"] == 0.0

    def test_large_cluster_enables_composition_and_injection(self):
        cluster = build_cluster(namespaces=5, pods=5, nodes=3)
        with patch.object(ga_sizing, "count_target_space", return_value=(600, 12)):
            profile = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert profile["composition_rate"] > 0
        assert profile["population_injection_rate"] > 0

    def test_returns_none_when_no_targets_found(self):
        cluster = build_cluster()
        with patch.object(ga_sizing, "count_target_space", return_value=(0, 0)):
            assert recommend_genetic_params(cluster, "kubeconfig.yaml") is None

    def test_returns_none_when_probe_fails(self):
        cluster = build_cluster()
        with patch.object(
            ga_sizing, "count_target_space", side_effect=RuntimeError("boom")
        ):
            assert recommend_genetic_params(cluster, "kubeconfig.yaml") is None

    def test_empty_cluster_returns_none(self):
        assert recommend_genetic_params(ClusterComponents(), "kubeconfig.yaml") is None

    def test_each_tier_produces_a_distinct_profile(self):
        cluster = build_cluster()
        profiles = []
        for targets in (10, 300, 600):
            with patch.object(
                ga_sizing, "count_target_space", return_value=(targets, 12)
            ):
                profiles.append(recommend_genetic_params(cluster, "kubeconfig.yaml"))

        populations = [p["population_size"] for p in profiles]
        assert populations == sorted(populations)
        assert len(set(populations)) == 3
