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
)
from krkn_ai.utils import ga_sizing
from krkn_ai.utils.ga_sizing import recommend_genetic_params
from krkn_ai.utils.rng import rng


def build_cluster(namespaces=1, pods=2, nodes=1, pvcs=1):
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


class TestRecommendGeneticParams:
    """Profile produced for a discovered cluster"""

    def test_returns_profile_for_real_cluster(self):
        cluster = build_cluster(namespaces=2, pods=3, nodes=2)
        profile = recommend_genetic_params(cluster, "kubeconfig.yaml", samples=40)

        assert profile is not None
        assert profile["generations"] > 0
        assert profile["population_size"] >= 2
        assert profile["exploration_saturation"] == ga_sizing.EXPLORATION_SATURATION
        assert profile["generation_saturation"] == ga_sizing.GENERATION_SATURATION

    def test_same_cluster_sizes_the_same_way(self):
        cluster = build_cluster(namespaces=2, pods=3, nodes=2)
        first = recommend_genetic_params(cluster, "kubeconfig.yaml", samples=60)
        second = recommend_genetic_params(cluster, "kubeconfig.yaml", samples=60)

        assert first == second

    def test_probe_restores_caller_seed(self):
        cluster = build_cluster()
        rng.set_seed(1234)
        recommend_genetic_params(cluster, "kubeconfig.yaml", samples=20)

        assert rng.get_seed() == 1234

    def test_tournament_size_never_exceeds_population(self):
        cluster = build_cluster(namespaces=3, pods=4, nodes=3)
        profile = recommend_genetic_params(cluster, "kubeconfig.yaml", samples=40)

        assert profile["tournament_size"] <= profile["population_size"]
        assert profile["tournament_size"] >= 2

    def test_small_cluster_skips_composition_and_injection(self):
        cluster = build_cluster(namespaces=1, pods=1, nodes=1, pvcs=0)
        with patch.object(ga_sizing, "count_distinct_targets", return_value=(10, 5)):
            profile = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert profile["composition_rate"] == 0.0
        assert profile["population_injection_rate"] == 0.0

    def test_large_cluster_enables_composition_and_injection(self):
        cluster = build_cluster(namespaces=5, pods=5, nodes=3)
        with patch.object(ga_sizing, "count_distinct_targets", return_value=(400, 12)):
            profile = recommend_genetic_params(cluster, "kubeconfig.yaml")

        assert profile["composition_rate"] > 0
        assert profile["population_injection_rate"] > 0

    def test_returns_none_when_no_targets_found(self):
        cluster = build_cluster()
        with patch.object(ga_sizing, "count_distinct_targets", return_value=(0, 0)):
            assert recommend_genetic_params(cluster, "kubeconfig.yaml") is None

    def test_returns_none_when_probe_fails(self):
        cluster = build_cluster()
        with patch.object(
            ga_sizing, "count_distinct_targets", side_effect=RuntimeError("boom")
        ):
            assert recommend_genetic_params(cluster, "kubeconfig.yaml") is None

    def test_empty_cluster_returns_none(self):
        assert recommend_genetic_params(ClusterComponents(), "kubeconfig.yaml") is None

    def test_each_tier_produces_a_distinct_profile(self):
        cluster = build_cluster()
        profiles = []
        for targets in (10, 150, 400):
            with patch.object(
                ga_sizing, "count_distinct_targets", return_value=(targets, 12)
            ):
                profiles.append(recommend_genetic_params(cluster, "kubeconfig.yaml"))

        populations = [p["population_size"] for p in profiles]
        assert populations == sorted(populations)
        assert len(set(populations)) == 3
