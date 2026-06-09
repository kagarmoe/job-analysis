#!/usr/bin/env python3
"""Bronze layer derivation from copper snapshots."""

from __future__ import annotations

import argparse

import db


def derive(
    board: str,
    company: str,
    job_id: str | None = None,
    *,
    copper_base_dir: str = "copper",
    bronze_base_dir: str = "bronze",
) -> int:
    """Derive bronze records for one board/company from copper snapshots."""
    copper_conn = db.open_copper(board, base_dir=copper_base_dir)
    bronze_conn = db.open_bronze(board, base_dir=bronze_base_dir)

    if board == "ashby":
        return db.derive_ashby(copper_conn, bronze_conn, company)
    if board == "greenhouse":
        return db.derive_greenhouse(copper_conn, bronze_conn, company)
    if board == "adhoc":
        if not job_id:
            raise ValueError("job_id is required for adhoc bronze derivation")
        return db.derive_adhoc(copper_conn, bronze_conn, company, job_id)

    raise ValueError(f"Unsupported board: {board}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive bronze records from copper")
    parser.add_argument("--board", required=True, choices=["ashby", "greenhouse", "adhoc"])
    parser.add_argument("--company", required=True)
    parser.add_argument("--job-id", default=None)
    args = parser.parse_args()

    count = derive(args.board, args.company, args.job_id)
    print(f"Bronze derivation complete: {count} records for {args.company}/{args.board}")


if __name__ == "__main__":
    main()
