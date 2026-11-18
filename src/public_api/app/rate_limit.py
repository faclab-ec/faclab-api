"""Rate limits of the public API (S6.3, G-42, D-6).

Each key (an integration client, its tenant) has a GCRA bucket: it sustains
`per_minute` requests and takes up to `burst` at once. The state of a key is
one number, its theoretical arrival time (TAT): the moment its bucket is empty
again. A request moves it `interval` seconds ahead; when that would put it
more than the bucket's capacity (`burst` × `interval`) ahead of now, the
request is refused and the client learns when to retry.
"""

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

# Floating point slack: the burst-th request of a full bucket must fit
_EPSILON = 1e-9


@dataclass(frozen=True)
class RateLimit:
    per_minute: int
    burst: int

    @property
    def interval(self) -> float:
        """Seconds one request takes from the bucket"""
        return 60 / self.per_minute

    @property
    def capacity(self) -> float:
        """Seconds of requests the bucket holds"""
        return self.interval * self.burst

    @property
    def policy(self) -> str:
        """`RateLimit-Policy`: `burst` requests in a window of the seconds the
        bucket takes to fill again"""
        return f"{self.burst};w={max(1, round(self.capacity))}"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: RateLimit
    remaining: int
    # Seconds until the bucket is full again
    reset: int
    # When refused: seconds until a request fits
    retry_after: int = 0


def admit(limit: RateLimit, tat: float | None, now: float) -> tuple[Decision, float]:
    """The decision on a request to a key whose TAT is `tat` (None: never
    used), and the TAT it leaves (the same one when refused)"""
    current = max(tat if tat is not None else now, now)
    moved = current + limit.interval
    if moved - now > limit.capacity + _EPSILON:
        return (
            Decision(
                allowed=False,
                limit=limit,
                remaining=0,
                reset=_seconds(current - now),
                retry_after=max(1, _seconds(moved - limit.capacity - now)),
            ),
            current,
        )
    return (
        Decision(
            allowed=True,
            limit=limit,
            remaining=math.floor(
                round((limit.capacity - (moved - now)) / limit.interval, 6)
            ),
            reset=_seconds(moved - now),
        ),
        moved,
    )


def _seconds(value: float) -> int:
    """Whole seconds, rounded up past the floating point noise"""
    return math.ceil(round(value, 6))


def binding(decisions: Sequence[Decision]) -> Decision:
    """The decision the response reports: the refused one, or the key with the
    fewest requests left"""
    refused = [d for d in decisions if not d.allowed]
    if refused:
        return max(refused, key=lambda d: d.retry_after)
    return min(decisions, key=lambda d: d.remaining)


class RateLimiter(ABC):
    @abstractmethod
    def check(self, keys: Sequence[tuple[str, RateLimit]]) -> Decision:
        """Counts a request against each key in order, stopping at the first
        that refuses it, and returns the decision to report"""
