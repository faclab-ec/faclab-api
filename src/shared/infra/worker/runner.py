"""Proceso worker: la mensajería (relay del outbox, consumidor) y las tareas
periódicas (purgas), fuera del API (ADR-0007).

`Worker.run()` arranca los servicios en orden, corre las tareas periódicas en el
hilo principal y, con SIGTERM o SIGINT, termina la tarea en curso y detiene los
servicios en orden inverso. `WorkerHealth` lleva el último ciclo exitoso de cada
tarea y lo escribe en un archivo JSON que lee el health check del contenedor
(`python -m src.shared.infra.worker.health`).

Las tareas no toman un lock: las purgas son DELETE idempotentes, así que dos
workers a la vez solo repiten trabajo. El relay del outbox se coordina con su
propio advisory lock.
"""

import json
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


class Service(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    interval: float
    run: Callable[[], Any]


class WorkerHealth:
    """Last successful cycle of each task. A task is stale when it goes longer
    than its `max_age` without one (counting from its registration)."""

    def __init__(self, path: Path | None, clock: Callable[[], datetime] = datetime.now):
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def register(self, name: str, max_age: float) -> None:
        with self._lock:
            self._tasks[name] = {
                "registered_at": self._clock().isoformat(),
                "max_age_seconds": max_age,
                "last_success_at": None,
                "last_error": None,
                "last_error_at": None,
            }

    def success(self, name: str) -> None:
        with self._lock:
            self._tasks[name]["last_success_at"] = self._clock().isoformat()

    def failure(self, name: str, error: str) -> None:
        with self._lock:
            self._tasks[name]["last_error"] = error[:500]
            self._tasks[name]["last_error_at"] = self._clock().isoformat()

    def reporter(self, name: str) -> Callable[[], None]:
        """Callback for a service that reports its own cycles"""
        return lambda: self.success(name)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tasks = {name: dict(state) for name, state in self._tasks.items()}
        return {
            "pid": os.getpid(),
            "updated_at": self._clock().isoformat(),
            "tasks": tasks,
        }

    def write(self) -> None:
        """Atomic: the health check never reads half a file"""
        if self._path is None:
            return
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        temporary.write_text(json.dumps(self.snapshot()))
        temporary.replace(self._path)


class Worker:
    def __init__(
        self,
        services: Sequence[Service],
        tasks: Sequence[PeriodicTask],
        health: WorkerHealth,
        tick: float = 1.0,
        health_interval: float = 5.0,
    ):
        self._services = list(services)
        self._tasks = list(tasks)
        self._health = health
        self._tick = tick
        self._health_interval = health_interval
        self._stop = threading.Event()
        for task in self._tasks:
            # Two missed runs, plus a minute of grace for a slow one
            health.register(task.name, task.interval * 2 + 60)

    def stop(self, *_signal: Any) -> None:
        self._stop.set()

    def run(self, handle_signals: bool = True) -> None:
        if handle_signals:
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        logger.info(
            "worker_started",
            services=[type(service).__name__ for service in self._services],
            tasks=[task.name for task in self._tasks],
        )
        started: list[Service] = []
        try:
            for service in self._services:
                service.start()
                started.append(service)
            self._loop()
        finally:
            for service in reversed(started):
                try:
                    service.stop()
                except Exception:
                    logger.exception(
                        "worker_service_stop_failed", service=type(service).__name__
                    )
            self._health.write()
            logger.info("worker_stopped")

    def _loop(self) -> None:
        # Every task runs right away, then at its interval
        next_run = {task.name: 0.0 for task in self._tasks}
        next_health = 0.0
        while not self._stop.is_set():
            for task in self._tasks:
                if self._stop.is_set():
                    break
                if time.monotonic() >= next_run[task.name]:
                    self._run_task(task)
                    next_run[task.name] = time.monotonic() + task.interval
            if time.monotonic() >= next_health:
                self._write_health()
                next_health = time.monotonic() + self._health_interval
            self._stop.wait(self._tick)

    def _run_task(self, task: PeriodicTask) -> None:
        try:
            task.run()
        except Exception as exc:
            logger.exception("worker_task_failed", task=task.name)
            self._health.failure(task.name, str(exc) or type(exc).__name__)
        else:
            self._health.success(task.name)

    def _write_health(self) -> None:
        try:
            self._health.write()
        except OSError:
            logger.exception("worker_health_write_failed")
