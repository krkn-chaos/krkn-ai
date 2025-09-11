import numpy as np
from typing import List, Any

class RNG:
    def __init__(self):
        self.rng = np.random.default_rng()

    def random(self):
        return self.rng.random()

    def choice(self, items: List[Any]):
        return self.rng.choice(items)

    def choices(self, items: List[Any], weights: List[float], k: int = 1):
        return list(self.rng.choice(items, p=weights, size=k))

    def randint(self, low: int, high: int):
        if low == high:
            return low
        return self.rng.integers(low, high)

rng = RNG()
