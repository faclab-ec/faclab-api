import json
import threading
from datetime import datetime, timedelta

from src.shared.infra.worker import health as health_check
from src.shared.infra.worker.runner import PeriodicTask, Worker, WorkerHealth


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 28, 12, 0)

    def __call__(self) -> datetime:
        return self.now


class RecordingService:
    def __init__(self, name: str, log: list[str]):
        self.name = name
        self.log = log

    def start(self) -> None:
        self.log.append(f"start {self.name}")

    def stop(self) -> None:
        self.log.append(f"stop {self.name}")


def _run_until(worker: Worker, done: threading.Event) -> None:
    """Runs the worker in a thread until `done`, then stops it as SIGTERM would"""
    thread = threading.Thread(target=worker.run, kwargs={"handle_signals": False})
    thread.start()
    assert done.wait(timeout=5)
    worker.stop()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_services_start_in_order_and_stop_in_reverse(tmp_path):
    log: list[str] = []
    done = threading.Event()
    worker = Worker(
        [RecordingService("relay", log), RecordingService("consumer", log)],
        [PeriodicTask("tick", 60, done.set)],
        WorkerHealth(tmp_path / "health.json"),
        tick=0.01,
    )

    _run_until(worker, done)

    assert log == ["start relay", "start consumer", "stop consumer", "stop relay"]


def test_a_periodic_task_runs_at_its_interval(tmp_path):
    runs: list[int] = []
    done = threading.Event()

    def task() -> None:
        runs.append(1)
        if len(runs) == 3:
            done.set()

    worker = Worker(
        [],
        [PeriodicTask("tick", 0.01, task)],
        WorkerHealth(tmp_path / "h.json"),
        tick=0.01,
    )

    _run_until(worker, done)

    assert len(runs) >= 3


def test_a_failing_task_is_recorded_and_the_worker_goes_on(tmp_path):
    path = tmp_path / "health.json"
    done = threading.Event()

    def broken() -> None:
        raise ConnectionError("database is down")

    worker = Worker(
        [],
        [PeriodicTask("broken", 60, broken), PeriodicTask("fine", 60, done.set)],
        WorkerHealth(path),
        tick=0.01,
    )

    _run_until(worker, done)

    tasks = json.loads(path.read_text())["tasks"]
    assert tasks["broken"]["last_success_at"] is None
    assert tasks["broken"]["last_error"] == "database is down"
    assert tasks["fine"]["last_success_at"] is not None


def test_a_service_reports_its_cycles(tmp_path):
    clock = Clock()
    health = WorkerHealth(tmp_path / "health.json", clock=clock)
    health.register("outbox_relay", 60)

    health.reporter("outbox_relay")()
    health.write()

    task = json.loads((tmp_path / "health.json").read_text())["tasks"]["outbox_relay"]
    assert task["last_success_at"] == clock.now.isoformat()
    assert task["max_age_seconds"] == 60


def test_the_health_check_passes_while_every_task_is_fresh(tmp_path):
    clock = Clock()
    path = tmp_path / "health.json"
    health = WorkerHealth(path, clock=clock)
    health.register("outbox_relay", 60)
    health.success("outbox_relay")
    health.write()

    assert health_check.problems(path, now=clock.now + timedelta(seconds=30)) == []


def test_the_health_command_exits_with_the_result(tmp_path):
    path = tmp_path / "health.json"
    health = WorkerHealth(path)
    health.register("outbox_relay", 60)
    health.success("outbox_relay")
    health.write()

    assert health_check.main(["health", str(path)]) == 0
    assert health_check.main(["health", str(tmp_path / "missing.json")]) == 1


def test_the_health_check_fails_on_a_stale_task(tmp_path):
    clock = Clock()
    path = tmp_path / "health.json"
    health = WorkerHealth(path, clock=clock)
    health.register("outbox_relay", 60)
    health.register("kafka_consumer", 300)
    health.success("outbox_relay")
    health.failure("outbox_relay", "broker unavailable")
    clock.now += timedelta(seconds=55)
    health.success("kafka_consumer")
    health.write()

    found = health_check.problems(path, now=clock.now + timedelta(seconds=10))

    assert found == [
        "outbox_relay: no successful cycle since 2026-10-28T12:00:00 "
        "(last error: broker unavailable)"
    ]


def test_a_task_without_cycles_is_stale_after_its_max_age(tmp_path):
    clock = Clock()
    path = tmp_path / "health.json"
    health = WorkerHealth(path, clock=clock)
    health.register("kafka_consumer", 300)

    clock.now += timedelta(seconds=200)
    health.write()
    assert health_check.problems(path, now=clock.now) == []

    clock.now += timedelta(seconds=101)
    health.write()
    assert len(health_check.problems(path, now=clock.now)) == 1


def test_the_health_check_fails_without_a_file(tmp_path):
    [problem] = health_check.problems(tmp_path / "missing.json")

    assert "unreadable" in problem


def test_the_health_check_fails_when_the_worker_stops_writing(tmp_path):
    clock = Clock()
    path = tmp_path / "health.json"
    WorkerHealth(path, clock=clock).write()

    [problem] = health_check.problems(path, now=clock.now + timedelta(minutes=5))

    assert problem.startswith("health file not updated since")
