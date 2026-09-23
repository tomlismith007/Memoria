"""State graph: route -> (qa | mail triage -> confirm -> archive | ingest)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from memoria.graph import nodes
from memoria.graph.state import MemoriaState
from memoria.llm import ChatLLM
from memoria.rag import ChromaStore, Embedder
from memoria.wiki import Wiki


def build_graph(
    store: ChromaStore,
    embedder: Embedder,
    llm: ChatLLM,
    wiki: Wiki,
    mail_service=None,
):
    g = StateGraph(MemoriaState)
    g.add_node("router", nodes.make_router(llm))
    g.add_node("qa", nodes.make_qa(store, embedder, llm))
    g.add_node("mail_triage", nodes.make_mail_triage(llm, service=mail_service))
    g.add_node("confirm_archive", nodes.confirm_archive)
    g.add_node("mail_archive", nodes.make_mail_archive(mail_service))
    g.add_node("ingest", nodes.make_ingest(wiki, llm))

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        lambda s: s["intent"],
        {"问答": "qa", "邮件": "mail_triage", "ingest": "ingest"},
    )
    g.add_edge("qa", END)
    g.add_edge("mail_triage", "confirm_archive")
    g.add_edge("confirm_archive", "mail_archive")
    g.add_edge("mail_archive", END)
    g.add_edge("ingest", END)
    return g
