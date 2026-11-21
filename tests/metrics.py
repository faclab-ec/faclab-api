"""The metrics a test records, read in memory (S7.1).

OTel accepts one global meter provider, so the whole run shares it
(`metric_reader` in `tests/conftest.py`). Counters and histograms are
exported as deltas: each collection holds only what happened since the
previous one, so a test sees its own measurements. The instruments of the code
are proxies of the API and bind to this provider when it is set.
"""

from dataclasses import dataclass, field
from typing import Any

from opentelemetry import metrics
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    HistogramDataPoint,
    InMemoryMetricReader,
)

Point = tuple[float, dict[str, Any]]

_reader: InMemoryMetricReader | None = None


def install_reader() -> InMemoryMetricReader:
    global _reader
    if _reader is None:
        _reader = InMemoryMetricReader(
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
            }
        )
        metrics.set_meter_provider(MeterProvider(metric_readers=[_reader]))
    return _reader


@dataclass
class Collected:
    """One collection: per metric its unit and its points. A histogram's point
    is how many measurements it took"""

    units: dict[str, str] = field(default_factory=dict)
    data: dict[str, list[Point]] = field(default_factory=dict)

    def points(self, name: str) -> list[Point]:
        return self.data.get(name, [])

    def attributes(self, name: str) -> list[dict[str, Any]]:
        return [attributes for _value, attributes in self.points(name)]

    def total(self, name: str, **attributes: Any) -> float:
        """Sum of the points whose attributes include these (dots as `__`)"""
        wanted = {key.replace("__", "."): value for key, value in attributes.items()}
        return sum(
            value
            for value, attrs in self.points(name)
            if all(attrs.get(key) == value for key, value in wanted.items())
        )


class RecordedMetrics:
    def __init__(self, reader: InMemoryMetricReader):
        self._reader = reader

    def collect(self) -> Collected:
        collected = Collected()
        data = self._reader.get_metrics_data()
        if data is None:
            return collected
        for resource_metrics in data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    collected.units[metric.name] = metric.unit or ""
                    points = collected.data.setdefault(metric.name, [])
                    for point in metric.data.data_points:
                        value = (
                            point.count
                            if isinstance(point, HistogramDataPoint)
                            else point.value
                        )
                        points.append((value, dict(point.attributes or {})))
        return collected
