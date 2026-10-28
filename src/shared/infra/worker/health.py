"""Health check of the worker container: exits 0 when every task had a
successful cycle within its `max_age` and the worker wrote the file recently,
1 otherwise (and says why).

Usage:
    python -m src.shared.infra.worker.health [path]
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# The worker rewrites the file every few seconds; older means it is stuck
MAX_FILE_AGE = timedelta(seconds=60)


def problems(path: Path, now: datetime | None = None) -> list[str]:
    """What is wrong with the worker, according to its health file"""
    now = now or datetime.now()
    try:
        health = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [f"health file {path} unreadable: {exc}"]

    found = []
    if now - datetime.fromisoformat(health["updated_at"]) > MAX_FILE_AGE:
        found.append(f"health file not updated since {health['updated_at']}")
    for name, task in health["tasks"].items():
        last = task["last_success_at"] or task["registered_at"]
        if now - datetime.fromisoformat(last) > timedelta(
            seconds=task["max_age_seconds"]
        ):
            found.append(
                f"{name}: no successful cycle since {last}"
                + (f" (last error: {task['last_error']})" if task["last_error"] else "")
            )
    return found


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        path = Path(argv[1])
    else:
        from config import config

        path = Path(config.WORKER_HEALTH_FILE)
    found = problems(path)
    for problem in found:
        print(problem, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
