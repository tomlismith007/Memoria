"""Thin CLI: argparse -> the LangGraph orchestrator. No logic here; deps injectable.

Every subcommand runs through the compiled graph, the same one the Web API uses
(feat-045). Calling sync.py directly would make the CLI a second, unverified
orchestration path.
"""

from __future__ import annotations

import argparse
import os
import uuid


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

    agent = sub.add_parser("agent", help="free-text request; the graph router picks the branch")
    agent.add_argument("text")
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


def _graph(args, store, embedder, llm, wiki, overrides: dict | None):
    from langgraph.checkpoint.memory import MemorySaver

    from memoria.graph.graph import build_graph

    overrides = overrides or {}
    return build_graph(store, embedder, llm, wiki).compile(
        checkpointer=overrides.get("checkpointer") or MemorySaver()
    )


def main(argv: list[str] | None = None, deps: dict | None = None) -> int:
    from memoria.wiki import lint as wiki_lint

    args = build_parser().parse_args(argv)
    store, embedder, llm, wiki = _deps(args, deps)
    deps = deps or {}

    # lint has no graph branch; it is a read-only audit over the wiki files.
    if args.cmd == "lint":
        report = wiki_lint(wiki)
        print(f"broken={report.broken} orphans={report.orphans}")
        return 0

    g = _graph(args, store, embedder, llm, wiki, deps)
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}

    if args.cmd == "ingest":
        result = g.invoke(
            {"intent": "ingest", "source_path": args.source, "origin": args.source}, cfg
        )
        print(
            f"doc={result.get('doc_id')} chunks={result.get('chunks', 0)} "
            f"wiki={result.get('ingest_updated', [])}"
        )
    elif args.cmd == "ask":
        result = g.invoke({"text": args.question, "intent": "问答"}, cfg)
        print(f"[{result.get('answer_source', 'rag+wiki')}] {result.get('answer_text', '')}")
        for c in result.get("answer_citations", []):
            print(f"  [{c.ref}] {c.doc_id}#{c.chunk} @ {c.start}")
        for p in result.get("answer_wiki_pages", []):
            print(f"  wiki: [[{p}]]")
    elif args.cmd == "agent":
        # No `intent`: the graph's router node decides, same as POST /api/agent.
        result = g.invoke({"text": args.text}, cfg)
        intent = result.get("intent", "问答")
        print(f"[intent={intent}]")
        if intent == "问答":
            print(f"[{result.get('answer_source', 'rag+wiki')}] {result.get('answer_text', '')}")
            for c in result.get("answer_citations", []):
                print(f"  [{c.ref}] {c.doc_id}#{c.chunk} @ {c.start}")
        elif intent == "ingest":
            print(f"doc={result.get('doc_id')} chunks={result.get('chunks', 0)}")
        else:
            print(f"pending_archive={result.get('pending_archive', [])}")
    return 0
