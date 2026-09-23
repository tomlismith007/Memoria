"""Thin CLI: argparse -> existing modules. No logic here; deps injectable for tests."""

from __future__ import annotations

import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memoria", description="Memoria personal knowledge system")
    p.add_argument("--chroma", default=os.environ.get("MEMORIA_CHROMA", "./data/chroma"))
    p.add_argument("--wiki", default=os.environ.get("MEMORIA_WIKI", "./data/wiki"))
    sub = p.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="dual-write a document into vectors + wiki")
    ing.add_argument("source", help="file path or URL")

    ask = sub.add_parser("ask", help="wiki-first hybrid answer with citations")
    ask.add_argument("question")

    sub.add_parser("lint", help="wiki broken-links / orphans check")
    return p


def _deps(args, overrides: dict | None):
    from memoria.llm import OpenAICompatibleChat
    from memoria.rag import ChromaStore, OpenAICompatibleEmbedder
    from memoria.wiki import Wiki

    overrides = overrides or {}
    store = overrides.get("store") or ChromaStore(path=args.chroma)
    wiki = overrides.get("wiki") or Wiki(args.wiki)
    wiki.ensure_layout()
    return (
        store,
        overrides.get("embedder") or OpenAICompatibleEmbedder(),
        overrides.get("llm") or OpenAICompatibleChat(),
        wiki,
    )


def main(argv: list[str] | None = None, deps: dict | None = None) -> int:
    from memoria.sync import dual_ingest, hybrid_answer
    from memoria.wiki import lint as wiki_lint

    args = build_parser().parse_args(argv)
    store, embedder, llm, wiki = _deps(args, deps)

    if args.cmd == "ingest":
        res = dual_ingest(args.source, store, embedder, wiki, llm)
        print(f"doc={res.doc_id} chunks={res.chunks} wiki={res.wiki_pages}")
    elif args.cmd == "ask":
        ans = hybrid_answer(args.question, wiki, llm, store, embedder)
        print(f"[{ans.source}] {ans.text}")
        for c in ans.citations:
            print(f"  [{c.ref}] {c.doc_id}#{c.chunk} @ {c.start}")
        for p in ans.wiki_pages:
            print(f"  wiki: [[{p}]]")
    elif args.cmd == "lint":
        report = wiki_lint(wiki)
        print(f"broken={report.broken} orphans={report.orphans}")
    return 0
