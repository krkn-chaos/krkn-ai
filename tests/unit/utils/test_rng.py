from krkn_ai.utils.rng import RNG


class TestRNG:
    def test_init_without_seed(self):
        """Test initialization without a seed."""
        rng = RNG()
        assert rng.get_seed() is None
        # Should produce a number
        assert 0.0 <= rng.random() < 1.0

    def test_init_with_seed(self):
        """Test initialization with a specific seed."""
        seed = 42
        rng = RNG(seed)
        assert rng.get_seed() == seed

        # Verify reproducibility
        val1 = rng.random()

        rng2 = RNG(seed)
        val2 = rng2.random()
        assert val1 == val2

    def test_set_seed(self):
        """Test setting the seed after initialization."""
        rng = RNG()
        seed = 12345
        rng.set_seed(seed)
        assert rng.get_seed() == seed

        val1 = rng.random()

        # Reset with same seed
        rng.set_seed(seed)
        val2 = rng.random()
        assert val1 == val2

    def test_random(self):
        """Test random() returns a float between 0.0 and 1.0."""
        rng = RNG(42)
        val = rng.random()
        assert isinstance(val, float)
        assert 0.0 <= val < 1.0

    def test_choice(self):
        """Test choice() picks an element from a sequence."""
        rng = RNG(42)
        items = [1, 2, 3, 4, 5]
        choice = rng.choice(items)
        assert choice in items

        # Reproducibility check
        rng.set_seed(42)
        choice2 = rng.choice(items)
        assert choice == choice2

    def test_choices(self):
        """Test choices() picks multiple elements with weights."""
        rng = RNG(42)
        items = ["a", "b", "c"]
        weights = [0.1, 0.8, 0.1]

        # "b" has highest weight, should appear most often in a large sample
        # but for a simple unit test we just check return structure
        choices = rng.choices(items, weights, k=5)
        assert len(choices) == 5
        assert all(c in items for c in choices)

        # Reproducibility check
        rng.set_seed(42)
        choices2 = rng.choices(items, weights, k=5)
        assert choices == choices2

    def test_randint_returns_int_in_inclusive_range(self):
        """Test randint() returns an integer within [low, high] inclusive."""
        rng = RNG(42)
        low, high = 1, 10
        val = rng.randint(low, high)
        assert isinstance(val, int)
        assert low <= val <= high  # both bounds inclusive

    def test_randint_equal_bounds(self):
        """Test randint() with equal low and high returns that value."""
        rng = RNG(42)
        assert rng.randint(5, 5) == 5
        assert rng.randint(0, 0) == 0

    def test_randint_upper_bound_is_reachable(self):
        """Verify the upper bound can actually be produced (catches the numpy off-by-one bug).

        numpy.integers(low, high) is exclusive of high.  Our wrapper must add 1
        so that callers using rng.randint(a, b) get an inclusive [a, b] range.
        Over 10 000 draws, the upper bound *must* appear at least once.
        """
        rng = RNG(seed=0)
        results = {rng.randint(1, 3) for _ in range(10_000)}
        assert 3 in results, (
            "Upper bound 3 was never produced by randint(1, 3) — "
            "likely caused by numpy.integers exclusive-high off-by-one bug."
        )
        assert 1 in results, "Lower bound 1 was never produced by randint(1, 3)."
        assert results == {1, 2, 3}

    def test_randint_covers_full_range(self):
        """Verify every integer in [low, high] is reachable over many draws."""
        rng = RNG(seed=99)
        low, high = 1, 10
        results = {rng.randint(low, high) for _ in range(50_000)}
        assert results == set(range(low, high + 1)), (
            f"Not all values in [{low}, {high}] were produced. Missing: "
            f"{set(range(low, high + 1)) - results}"
        )

    def test_randint_disruption_count_inclusive(self):
        """Regression test: scenario_container uses rng.randint(1, len(containers)).

        With 2 containers, disruption_count must be able to equal 2 (all containers).
        Previously broken because randint(1, 2) with numpy exclusive upper bound
        could only produce 1, silently making the multi-container branch in
        ContainerScenario.mutate() unreachable.
        """
        rng = RNG(seed=7)
        results = {rng.randint(1, 2) for _ in range(10_000)}
        assert 2 in results, (
            "randint(1, 2) never produced 2 — disruption_count could never "
            "equal the number of containers in a 2-container pod."
        )
        assert results == {1, 2}

    def test_sample(self):
        """Test sample() returns unique elements."""
        rng = RNG(42)
        items = [1, 2, 3, 4, 5]
        sampled = rng.sample(items, k=3)
        assert len(sampled) == 3
        assert len(set(sampled)) == 3
        assert all(x in items for x in sampled)

        # Reproducibility check
        rng.set_seed(42)
        sampled2 = rng.sample(items, k=3)
        assert sampled == sampled2

    def test_uniform(self):
        """Test uniform() returns a float within range."""
        rng = RNG(42)
        low, high = 1.5, 5.5
        val = rng.uniform(low, high)
        assert isinstance(val, float)
        assert low <= val <= high
