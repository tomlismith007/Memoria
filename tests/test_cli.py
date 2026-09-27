"""feat-009: CLI wiring. Offline — injected fakes, capsys on output."""

from memoria.cli import build_parser, main
from memoria.rag import ChromaStore, FakeEmbedder
from memoria.wiki import Wiki


class ScriptedChat:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


def _deps(tmp_path, *replies):
    return {
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": ScriptedChat(*replies),
        "wiki": Wiki(tmp_path / "kb"),
    }


def test_parser_commands():
    assert build_parser().parse_args(["ask", "q"]).question == "q"
    assert build_parser().parse_args(["ingest", "f.md"]).source == "f.md"
    assert build_parser().parse_args(["lint"]).cmd == "lint"
    assert build_parser().parse_args(["agent", "你好"]).text == "你好"


def test_cli_ingest(tmp_path, capsys):
    src = tmp_path / "n.md"
    src.write_text("服务 A 到期。" * 10, encoding="utf-8")
    rc = main(["ingest", str(src)], deps=_deps(tmp_path, "## [[服务到期]]\n# 服务到期\n\n到期。\n"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "doc=" in out and "服务到期" in out


def test_cli_ask_wiki_path(tmp_path, capsys):
    deps = _deps(tmp_path, "[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    deps["wiki"].ensure_layout()
    deps["wiki"].write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    deps["wiki"].build_index()
    rc = main(["ask", "何时到期"], deps=deps)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[wiki]" in out and "2027" in out


def test_cli_lint(tmp_path, capsys):
    deps = _deps(tmp_path)
    deps["wiki"].ensure_layout()
    deps["wiki"].write_page("A", "# A\n\n见 [[Ghost]]。\n")
    rc = main(["lint"], deps=deps)
    assert rc == 0
    assert "Ghost" in capsys.readouterr().out


def test_cli_runs_through_the_graph(tmp_path, capsys):
    """feat-045: no subcommand may call sync.py directly — the graph is the orchestrator."""
    import memoria.sync as sync_mod

    def explode(*a, **kw):  # pragma: no cover - only runs on regression
        raise AssertionError("CLI bypassed the graph and called sync.py directly")

    # Separate deps per subcommand: ScriptedChat replays in call order, so one
    # shared instance would desync across the two invocations.
    ask_deps = _deps(tmp_path, "[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    agent_deps = _deps(tmp_path, "问答", "[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    for deps in (ask_deps, agent_deps):
        deps["wiki"].ensure_layout()
        deps["wiki"].write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
        deps["wiki"].build_index()

    real_answer, real_dual = sync_mod.hybrid_answer, sync_mod.dual_ingest
    sync_mod.hybrid_answer = explode
    sync_mod.dual_ingest = explode
    try:
        assert main(["ask", "何时到期"], deps=ask_deps) == 0
        assert main(["agent", "何时到期"], deps=agent_deps) == 0
    finally:
        sync_mod.hybrid_answer, sync_mod.dual_ingest = real_answer, real_dual

    out = capsys.readouterr().out
    assert "[wiki]" in out and "2027" in out
    assert "intent=问答" in out  # the agent subcommand reported the routed branch


def test_cli_agent_runs_the_router_llm(tmp_path, capsys):
    """feat-045: `agent` omits `intent`, so the router's LLM branch must actually run."""
    deps = _deps(tmp_path, "问答", "[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    deps["wiki"].ensure_layout()
    deps["wiki"].write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    deps["wiki"].build_index()
    rc = main(["agent", "何时到期"], deps=deps)
    assert rc == 0
    assert any("意图路由" in system for system, _ in deps["llm"].calls)
    assert "intent=问答" in capsys.readouterr().out


def test_cli_ask_presets_intent_and_skips_router(tmp_path, capsys):
    """The structured `ask` subcommand must not pay for a router round-trip."""
    deps = _deps(tmp_path, "[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    deps["wiki"].ensure_layout()
    deps["wiki"].write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    deps["wiki"].build_index()
    main(["ask", "何时到期"], deps=deps)
    assert not any("意图路由" in system for system, _ in deps["llm"].calls)
    capsys.readouterr()
