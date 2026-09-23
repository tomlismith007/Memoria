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
