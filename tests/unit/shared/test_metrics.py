"""The metric infrastructure of S7.1: counting after the commit, observable
values sampled by a task, the connection pools and the HTTP server metric."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.shared.infra.adapters.telemetry import instrument_fastapi
from src.shared.infra.database import create_session_maker
from src.shared.infra.metrics import add_on_commit
from src.shared.infra.telemetry_instruments import (
    ObservedValues,
    observe_pools,
    sales_confirmed,
)

SOURCE = "faclab.sale.source"


def _session():
    session = create_session_maker("sqlite://")()
    session.execute(text("SELECT 1"))
    return session


def test_a_committed_transaction_counts(recorded_metrics):
    session = _session()
    add_on_commit(session, sales_confirmed, {SOURCE: "pos"})

    assert recorded_metrics.collect().total("faclab.sales.confirmed") == 0
    session.commit()

    assert recorded_metrics.collect().points("faclab.sales.confirmed") == [
        (1, {SOURCE: "pos"})
    ]


def test_a_rolled_back_transaction_counts_nothing(recorded_metrics):
    session = _session()
    add_on_commit(session, sales_confirmed, {SOURCE: "pos"})
    session.rollback()
    # Nor a later commit of the same session
    session.execute(text("SELECT 1"))
    session.commit()

    assert recorded_metrics.collect().total("faclab.sales.confirmed") == 0


def test_a_session_closed_without_commit_counts_nothing(recorded_metrics):
    session = _session()
    add_on_commit(session, sales_confirmed, {SOURCE: "pos"})
    session.close()

    assert recorded_metrics.collect().total("faclab.sales.confirmed") == 0


def test_without_a_session_it_counts_now(recorded_metrics):
    add_on_commit(None, sales_confirmed, {SOURCE: "api"})

    assert recorded_metrics.collect().points("faclab.sales.confirmed") == [
        (1, {SOURCE: "api"})
    ]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_observed_values_are_the_last_sample():
    clock = Clock()
    values = ObservedValues(clock)
    values.replace([(3, {"topic": "a"})], max_age=60)
    values.replace([(1, {"topic": "a"}), (0, {"topic": "b"})], max_age=60)

    observed = [(o.value, o.attributes) for o in values.observe()]

    assert observed == [(1, {"topic": "a"}), (0, {"topic": "b"})]


def test_a_stale_sample_is_not_observed():
    clock = Clock()
    values = ObservedValues(clock)
    values.replace([(3, {"topic": "a"})], max_age=60)

    clock.now += 61

    assert values.observe() == []


def test_nothing_is_observed_before_the_first_sample():
    assert ObservedValues().observe() == []


def _pool_counts(name: str) -> dict[str, float]:
    return {
        str(o.attributes["db.client.connection.state"]): o.value
        for o in observe_pools()
        if o.attributes and o.attributes["db.client.connection.pool.name"] == name
    }


def test_the_pool_reports_used_and_idle_connections(tmp_path, recorded_metrics):
    # A file database: SQLAlchemy pools it with a QueuePool
    factory = create_session_maker(f"sqlite:///{tmp_path}/db.sqlite", pool_name="t1")
    engine = factory.kw["bind"]

    connection = engine.connect()
    assert _pool_counts("t1") == {"used": 1, "idle": 0}
    connection.close()
    assert _pool_counts("t1") == {"used": 0, "idle": 1}

    collected = recorded_metrics.collect()
    assert collected.units["db.client.connection.count"] == "{connection}"
    assert {
        "db.client.connection.pool.name": "t1",
        "db.client.connection.state": "idle",
    } in collected.attributes("db.client.connection.count")


def test_pools_that_dont_count_connections_are_left_out():
    create_session_maker("sqlite://", pool_name="memory")

    assert _pool_counts("memory") == {}


def test_http_requests_use_the_stable_conventions(recorded_metrics):
    app = FastAPI()

    @app.get("/items/{item_id}")
    def get_item(item_id: int) -> dict:
        return {"id": item_id}

    instrument_fastapi(app)
    assert TestClient(app).get("/items/42").status_code == 200

    collected = recorded_metrics.collect()
    assert collected.units["http.server.request.duration"] == "s"
    (attributes,) = collected.attributes("http.server.request.duration")
    assert attributes["http.route"] == "/items/{item_id}"
    assert attributes["http.request.method"] == "GET"
    assert attributes["http.response.status_code"] == 200
