import numpy as np
from typing import List, Any, Optional
from typing import TypeVar, Sequence

T = TypeVar("T")


class RNG:
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        self.rng = np.random.default_rng(seed=seed)

    def get_seed(self) -> Optional[int]:
        """Return the seed used to initialize the RNG, or None if no seed was set."""
        return self.seed

    def set_seed(self, seed: Optional[int] = None):
        """Reset the RNG with a new seed."""
        self.seed = seed
        self.rng = np.random.default_rng(seed=seed)

    def random(self):
        return self.rng.random()

    def choice(self, items: Sequence[T]) -> T:
        """Return a random element from the given non-empty sequence. The return type is inferred from the list type."""
        return self.rng.choice(items)

    def choices(self, items: List[Any], weights: List[float], k: int = 1):
        return list(self.rng.choice(items, p=weights, size=k))

    def randint(self, low: int, high: int) -> int:
        """Return a random integer N such that low <= N <= high (both inclusive).

        Note: numpy's ``integers(low, high)`` uses an exclusive upper bound.
        We add 1 to ``high`` so that the public contract of this method is
        inclusive on both ends, matching the behaviour of Python's
        ``random.randint``.
        """
        if low == high:
            return low
        return int(self.rng.integers(low, high + 1))

    def sample(self, items: Sequence[T], k: int) -> List[T]:
        """Return k unique elements from items, without replacement."""
        indices = self.rng.choice(len(items), size=k, replace=False)
        return [items[i] for i in indices]

    def uniform(self, low: float, high: float):
        return self.rng.uniform(low, high)


rng = RNG()
