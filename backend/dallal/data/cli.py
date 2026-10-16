"""`dallal-data` command line: registry inspection and reproducible dataset fetching."""

from __future__ import annotations

import argparse
import logging

from dallal.data.download import fetch_dataset, verify_dataset
from dallal.data.registry import load_registry


def _lade() -> None:
    from dallal.data.adapters import lade

    lade.build(("delivery_jl", "delivery_yt", "delivery_cq", "delivery_sh", "delivery_hz", "pickup_jl", "pickup_yt"))


def _amazon() -> None:
    from dallal.data.adapters import amazon_lmrrc

    amazon_lmrrc.build()


def _olist() -> None:
    from dallal.data.adapters import olist

    olist.build()


def _route_dev() -> None:
    from dallal.data.adapters import route_deviation

    route_deviation.build()


def _spl() -> None:
    from dallal.data.adapters import spl_reference

    spl_reference.build()


def _ocel() -> None:
    from dallal.data.adapters import ocel

    ocel.build()


def _labels() -> None:
    from dallal.data import labels

    labels.build_all()


BUILDERS = {"labels": _labels, "lade": _lade, "amazon_lmrrc": _amazon, "olist": _olist, "route_deviation": _route_dev,
            "spl_open_data": _spl, "ocel_order_management": _ocel}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dallal-data")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show every audited dataset and its decision")
    f = sub.add_parser("fetch", help="download a dataset into backend/.data/raw")
    f.add_argument("dataset", nargs="+", help="dataset id(s), or 'selected' for every SELECT + SECONDARY with files")
    f.add_argument("--all", action="store_true", help="also fetch files flagged group=large")
    f.add_argument("--force", action="store_true")
    b = sub.add_parser("build", help="map raw data into canonical parquet tables (backend/.data/canonical)")
    b.add_argument("source", nargs="+", choices=sorted(BUILDERS))
    v = sub.add_parser("verify", help="check on-disk files against registry/datasets.lock.json")
    v.add_argument("dataset", nargs="+")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    reg = load_registry()

    if args.cmd == "list":
        for d in reg.datasets:
            print(f"{d.decision.upper():9} {d.evidence_level:6} {d.data_kind:14} {d.id:32} {d.name}")
        return 0

    if args.cmd == "build":
        for src in args.source:
            BUILDERS[src]()
        return 0
    ids = args.dataset
    if ids == ["selected"]:
        ids = [d.id for d in reg.datasets if d.decision in ("select", "secondary") and d.files]
    if args.cmd == "fetch":
        for i in ids:
            fetch_dataset(i, include_large=args.all, force=args.force)
        return 0
    ok = True
    for i in ids:
        res = verify_dataset(i)
        ok &= all(res.values())
        print(i, res)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
