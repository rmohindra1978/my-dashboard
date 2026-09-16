"""Pipeline orchestrator.

python -m pipelines.build --sample            load synthetic fixtures (fast, offline)
python -m pipelines.build --all               run every registered public source
python -m pipelines.build --source acs5 ...   run selected sources
python -m pipelines.build --list              show registered sources
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from backend.app.data.warehouse import rebuild_market_features, warehouse
from backend.app.registry import load_metric_registry
from pipelines.sources import SAMPLE_SOURCES, SOURCES


def build(sources: list[str], sample: bool, warehouse_path: Path | None = None) -> dict[str, int]:
    registry = load_metric_registry()
    results: dict[str, int] = {}
    with warehouse(warehouse_path, read_only=False) as con:
        if sample:
            results["sample"] = SAMPLE_SOURCES["sample"]().run(con, rebuild_features=False)
        for sid in sources:
            if sid not in SOURCES:
                raise SystemExit(f"unknown source '{sid}'. Registered: {sorted(SOURCES)}")
            results[sid] = SOURCES[sid](registry=registry).run(con, rebuild_features=False)
        n = rebuild_market_features(con)
        logging.getLogger("pipelines").info("market_features rebuilt: %d rows", n)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all", action="store_true", help="run every registered source")
    p.add_argument("--sample", action="store_true", help="load synthetic fixtures")
    p.add_argument("--source", action="append", default=[], help="run a specific source id (repeatable)")
    p.add_argument("--list", action="store_true")
    p.add_argument("--warehouse", type=Path, default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.list:
        for sid in SOURCES:
            print(sid)
        return 0
    sources = list(SOURCES) if args.all else args.source
    if not sources and not args.sample:
        p.print_help()
        return 2
    if args.all and not SOURCES:
        print("no public sources registered yet - run with --sample for synthetic data", file=sys.stderr)
    results = build(sources, args.sample, args.warehouse)
    for sid, n in results.items():
        print(f"{sid}: {n} metric rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
