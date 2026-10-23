"""Seeded random streams, one per entity, and inverse-CDF distributions.

Each stream is identified by a key such as (seed, "truck", "unload", day, index) or
(seed, "service", truck id, step). A stream's numbers depend only on its key, never on how many numbers other
entities drew before it. That gives common random numbers across scenarios: adding a hopper changes neither the
arrivals nor any truck's own service times, so differences between scenarios come from the change itself.

Reproducibility: the key is hashed with BLAKE2b to seed `random.Random`, whose `random()` sequence for an integer
seed Python guarantees not to change. Distribution formulas are written out here rather than taken from the
`random` module, whose other methods may change between Python versions.
"""
import hashlib
import math
import random


class Stream:
    def __init__(self, seed: int, *key: object):
        digest = hashlib.blake2b(repr((seed,) + key).encode("utf-8"), digest_size=8).digest()
        self._rng = random.Random(int.from_bytes(digest, "big"))

    def uniform(self) -> float:
        """A number in [0, 1)."""
        return self._rng.random()


def derived_seed(base_seed: int, *key: object) -> int:
    """A 32-bit seed derived from a base seed and a key (e.g. one per replication)."""
    digest = hashlib.blake2b(repr((base_seed,) + key).encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big")


def triangular(u: float, low: float, mode: float, high: float) -> float:
    """Inverse CDF of the triangular distribution (same formula as the prototype)."""
    if not high > low:
        return low
    split = (mode - low) / (high - low)
    if u < split:
        return low + math.sqrt(u * (high - low) * (mode - low))
    return high - math.sqrt((1 - u) * (high - low) * (high - mode))


def exponential(u: float, rate: float) -> float:
    """Inverse CDF of the exponential distribution; `rate` events per time unit."""
    return -math.log(1 - u) / rate


def pick_weighted(u: float, weights: dict[str, float]) -> str:
    """The key whose cumulative share contains u (weights are normalised; insertion order is kept)."""
    items = [(k, w) for k, w in weights.items() if w > 0]
    total = sum(w for _, w in items)
    acc = 0.0
    for key, w in items:
        acc += w / total
        if u < acc:
            return key
    return items[-1][0]
