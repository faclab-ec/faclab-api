"""Peaks and averages of what sample.sh recorded during a run (S9.2)."""

import csv
import sys
from collections import defaultdict
from pathlib import Path


def rows(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    with path.open() as handle:
        return [row for row in csv.reader(handle) if row]


def mebibytes(usage: str) -> float:
    value = usage.split("/")[0].strip()
    for suffix, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("B", 0)):
        if value.endswith(suffix):
            return float(value.removesuffix(suffix)) * factor
    return 0.0


def containers(folder: Path) -> None:
    cpu: dict[str, list[float]] = defaultdict(list)
    memory: dict[str, float] = defaultdict(float)
    for _, name, percent, usage in rows(folder / "stats.csv"):
        cpu[name].append(float(percent.rstrip("%")))
        memory[name] = max(memory[name], mebibytes(usage))
    print("contenedor: CPU media / máxima (% de un núcleo), memoria máxima")
    for name, values in sorted(cpu.items(), key=lambda item: -sum(item[1])):
        print(
            f"  {name:32} {sum(values) / len(values):6.1f} / {max(values):6.1f}  {memory[name]:6.0f} MiB"
        )


def connections(folder: Path) -> None:
    total: dict[str, int] = defaultdict(int)
    by_role: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for at, database, role, state, count in rows(folder / "connections.csv"):
        total[at] += int(count)
        by_role[(database, role)][at] += int(count)
        if state == "idle in transaction":
            by_role[(database, f"{role} idle in tx")][at] += int(count)
    print(f"conexiones de PostgreSQL, máximo: {max(total.values(), default=0)}")
    for (database, role), samples in sorted(by_role.items()):
        print(f"  {database}/{role}: {max(samples.values())}")


def waits(folder: Path) -> None:
    found: dict[tuple[str, str, str], list[float]] = defaultdict(
        lambda: [0.0, 0.0, 0.0]
    )
    for row in rows(folder / "waits.csv"):
        _, database, kind, event, count, longest, query = row[:7]
        entry = found[(database, f"{kind}:{event}", query[:80])]
        entry[0] += 1
        entry[1] = max(entry[1], float(count))
        entry[2] = max(entry[2], float(longest or 0))
    print("esperas vistas (muestras, sesiones máx., segundos máx.)")
    for (database, event, query), (samples, sessions, longest) in sorted(
        found.items(), key=lambda item: -item[1][0] * item[1][1]
    )[:8]:
        print(
            f"  {samples:4.0f} {sessions:3.0f} {longest:7.3f}  {database} {event}  {query}"
        )


def queues(folder: Path) -> None:
    outbox = rows(folder / "outbox.csv")
    print(
        "outbox sin publicar, máximo:",
        max((int(r[2]) for r in outbox), default=0),
        "mensajes; el más antiguo",
        max((float(r[3]) for r in outbox), default=0.0),
        "s",
    )
    pending: dict[str, int] = defaultdict(int)
    for at, _, count in rows(folder / "invoices.csv"):
        pending[at] += int(count)
    print("comprobantes sin resultado, máximo:", max(pending.values(), default=0))
    lag: dict[str, int] = defaultdict(int)
    for _, group, topic, value in rows(folder / "lag.csv"):
        lag[f"{group}/{topic}"] = max(lag[f"{group}/{topic}"], int(value))
    print(
        "lag de Kafka, máximo:", ", ".join(f"{k}={v}" for k, v in sorted(lag.items()))
    )
    load = rows(folder / "load.csv")
    memory = rows(folder / "host-mem.csv")
    if load and memory:
        print(
            f"host: carga 1 min máx. {max(float(r[1]) for r in load):.2f}, "
            f"memoria disponible mín. {min(int(r[1]) for r in memory) / 1024:.0f} MiB"
        )


if __name__ == "__main__":
    run = Path(sys.argv[1])
    containers(run)
    connections(run)
    waits(run)
    queues(run)
