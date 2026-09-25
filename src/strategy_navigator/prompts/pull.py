#!/usr/bin/env python
"""Export the operative prompt templates out of the n8n MongoDB into the repo.

Most stage prompts are not in the n8n workflow export — n8n reads them at runtime
from MongoDB, collection ``prompt_list``, keyed by ``promptId`` (see
``strategy_navigator.prompts.registry``). This module pulls each ``promptId`` the
pipeline needs and writes it to ``prompts/_mongo/<id>.md`` with a small
front-matter header. The loader converts ``${var}`` -> ``{{ var }}`` on read, so
the file stays a faithful copy of what ops edits in Mongo.

Usage:
    # straight from Mongo (default: $SN_N8N_MONGO_URL or mongodb://localhost:27017)
    strategy-navigator prompts pull --mongo-url mongodb://... --db n8n

    # or via the challenges-backend prompt API (no Mongo access needed)
    strategy-navigator prompts pull --from-backend --backend-url https://api... --token $JWT

    strategy-navigator prompts pull --check      # exit 1 if anything is missing/stale
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from strategy_navigator.prompts import registry

_OUT = Path(__file__).resolve().parent / "_mongo"


def _header(prompt_id: str, name: str, source: str) -> str:
    return (
        "---\n"
        f"promptId: {prompt_id}\n"
        f"promptName: {name}\n"
        f"pulledFrom: {source}\n"
        f"pulledAt: {datetime.now(UTC).isoformat(timespec='seconds')}\n"
        "note: verbatim copy of MongoDB prompt_list; ${var} placeholders are\n"
        "  rendered as Jinja {{ var }} by strategy_navigator.prompts\n"
        "---\n\n"
    )


def _write(prompt_id: str, name: str, body: str, source: str) -> Path:
    _OUT.mkdir(parents=True, exist_ok=True)
    path = _OUT / f"{prompt_id}.md"
    path.write_text(_header(prompt_id, name, source) + body.rstrip() + "\n", encoding="utf-8")
    return path


def _from_mongo(url: str, db_name: str, coll: str) -> dict[str, dict]:
    from pymongo import MongoClient  # lazy: only needed for this path

    client: MongoClient = MongoClient(url, serverSelectionTimeoutMS=5000)
    docs = client[db_name][coll].find({})
    return {d["promptId"]: d for d in docs if "promptId" in d}


def _from_backend(base_url: str, token: str | None) -> dict[str, dict]:
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = httpx.get(f"{base_url.rstrip('/')}/n8n/prompts", headers=headers, timeout=30)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    return {d["promptId"]: d for d in items if "promptId" in d}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mongo-url", default=os.getenv("SN_N8N_MONGO_URL", "mongodb://localhost:27017")
    )
    ap.add_argument("--db", default=os.getenv("SN_N8N_MONGO_DB", "n8n"))
    ap.add_argument("--collection", default="prompt_list")
    ap.add_argument("--from-backend", action="store_true")
    ap.add_argument("--backend-url", default=os.getenv("SN_BACKEND_URL", ""))
    ap.add_argument("--token", default=os.getenv("SN_BACKEND_TOKEN"))
    ap.add_argument("--check", action="store_true", help="report only, non-zero exit if incomplete")
    args = ap.parse_args(argv)

    wanted = registry.mongo_prompt_ids()
    print(f"pipeline needs {len(wanted)} Mongo prompt templates")

    if args.check:
        missing = [p for p in wanted if not (_OUT / f"{p}.md").exists()]
        for p in missing:
            print(f"  MISSING  {p}.md")
        if missing:
            print(f"\n{len(missing)} not exported. Run `strategy-navigator prompts pull`.")
            return 1
        print("all present")
        return 0

    if args.from_backend:
        if not args.backend_url:
            ap.error("--from-backend requires --backend-url / $SN_BACKEND_URL")
        source = f"backend {args.backend_url}"
        catalog = _from_backend(args.backend_url, args.token)
    else:
        source = f"mongo {args.mongo_url}/{args.db}.{args.collection}"
        catalog = _from_mongo(args.mongo_url, args.db, args.collection)

    print(f"fetched {len(catalog)} prompt_list entries from {source}\n")

    exit_code = 0
    for prompt_id in wanted:
        doc = catalog.get(prompt_id)
        if doc is None or not str(doc.get("prompt", "")).strip():
            print(f"  MISSING  {prompt_id}   (not in prompt_list)")
            exit_code = 1
            continue
        path = _write(prompt_id, doc.get("promptName", prompt_id), doc["prompt"], source)
        print(f"  wrote    prompts/_mongo/{path.name}")

    extra = sorted(set(catalog) - set(wanted))
    if extra:
        print(f"\n{len(extra)} prompt_list entries not referenced by any stage: {extra}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
