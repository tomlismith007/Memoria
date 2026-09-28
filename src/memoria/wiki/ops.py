"""Wiki operations: ingest / query / lint. LLM I/O in minimal parseable formats."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from memoria.llm import ChatLLM
from memoria.rag.retrieve import keyword_score
from memoria.wiki.pages import Wiki, extract_links

SECTION_RE = re.compile(r"^## \[\[([^\[\]]+)\]\]\s*$", re.M)
_WIKI_REF_RE = re.compile(r"\[\[[^\]]+\]\]")


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Split LLM output into (page name, body) on `## [[Name]]` headers."""
    parts = SECTION_RE.split(text)
    sections = []
    for i in range(1, len(parts), 2):
        name, body = parts[i].strip(), parts[i + 1].strip() if i + 1 < len(parts) else ""
        if name and body:
            sections.append((name, body))
    return sections


def _parse_names(text: str, valid: set[str]) -> list[str]:
    """Tolerant page-name list: `- [[X]]`, `[[X]]`, or bare `X` lines."""
    names = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        m = re.fullmatch(r"\[\[([^\[\]]+)\]\]", line)
        cand = (m.group(1) if m else line).strip()
        if cand in valid and cand not in names:
            names.append(cand)
    return names


def _select_relevant(pages: dict[str, str | None], material: str, k: int) -> list[str]:
    """Top-k pages by keyword overlap with the new material. Reuses the RAG scorer."""
    scored = [
        (keyword_score(material, f"{name} {body or ''}"), name)
        for name, body in pages.items()
        if body
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))  # ties break on name, not dict order
    return [name for _, name in scored[:k]]


def ingest(
    material: str, origin: str, wiki: Wiki, llm: ChatLLM, max_pages: int = 10
) -> list[str]:
    """LLM reads new material, rewrites related pages. Returns updated page names.

    The prompt is laid out cache-first: the page-name index is a stable prefix that
    only changes when pages are added or removed, and it sits ahead of the variable
    material/body blocks. The previous layout inlined every page body after the
    material, so each ingest rewrote the whole prompt and prefix caching never hit.
    """
    pages = {n: wiki.read_page(n) for n in wiki.list_pages()}
    selected = _select_relevant(pages, material, k=max_pages)
    index_block = "\n".join(f"- [[{n}]]" for n in sorted(pages)) or "（空）"
    bodies = "\n\n".join(f"## [[{n}]]\n{pages[n]}" for n in selected) or "（无相关页面）"
    user = (
        f"现有页面目录：\n{index_block}\n\n"
        f"新资料（来源：{origin}）：\n{material}\n\n"
        f"相关页面正文：\n{bodies}\n\n"
        "请更新相关页面（新建+修改，总数不超过 "
        f"{max_pages}），每个页面用 `## [[页名]]` 开头输出完整新内容。"
    )
    sections = _parse_sections(llm.chat("你是 Wiki 维护者。只输出页面内容，无多余解释。", user))
    updated = []
    for name, body in sections[:max_pages]:
        wiki.write_page(name, body + "\n")
        updated.append(name)
    wiki.build_index()
    wiki.append_log(
        f"ingest {origin}：更新 {len(updated)} 页 {updated}"
        f"（展开 {len(selected)}/{len(pages)} 页正文）"
    )
    if len(sections) > max_pages:
        wiki.append_log(f"ingest {origin}：{len(sections) - max_pages} 页超出上限未写")
    return updated


@dataclass
class WikiAnswer:
    text: str
    pages: list[str] = field(default_factory=list)
    citations_verified: bool = True


def query(question: str, wiki: Wiki, llm: ChatLLM) -> WikiAnswer:
    """Index first (locate), then deep-read selected pages, then answer."""
    index = wiki.read_page("index") or ""
    names = wiki.list_pages()
    selected = _parse_names(
        llm.chat(
            "你是 Wiki 检索器。根据目录选出能回答问题的页面，每行一个（`[[页名]]` 或页名），不要解释。",
            f"目录：\n{index}\n\n问题：{question}",
        ),
        set(names),
    )
    context = "\n\n".join(
        f"## [[{n}]]\n{wiki.read_page(n)}" for n in selected if wiki.read_page(n)
    )
    text = llm.chat(
        "你是 Wiki 问答助手。只根据提供的页面回答，注明 [[页名]] 来源；答不上就直说。",
        f"页面：\n{context or '（无相关页面）'}\n\n问题：{question}",
    )
    # Conservative: a wiki answer without any [[页名]] source is unverified, even refusals.
    return WikiAnswer(
        text=text, pages=selected, citations_verified=bool(_WIKI_REF_RE.search(text))
    )


@dataclass
class LintReport:
    broken: list[tuple[str, str]] = field(default_factory=list)  # (page, missing link)
    orphans: list[str] = field(default_factory=list)  # no incoming links
    contradictions: list[str] = field(default_factory=list)


def lint(wiki: Wiki, llm: ChatLLM | None = None, max_pairs: int = 5) -> LintReport:
    """Static broken-link + orphan check; LLM contradiction check on linked pairs only."""
    report = LintReport()
    pages = wiki.list_pages()
    known = set(pages)
    incoming: dict[str, int] = {p: 0 for p in pages}
    pairs: list[tuple[str, str]] = []
    for name in pages:
        for link in extract_links(wiki.read_page(name) or ""):
            if link not in known:
                report.broken.append((name, link))
            else:
                incoming[link] += 1
                if (link, name) not in pairs and (name, link) not in pairs:
                    pairs.append((name, link))
    report.orphans = sorted(p for p in pages if incoming[p] == 0)
    if llm is not None:
        for a, b in pairs[:max_pairs]:
            verdict = llm.chat(
                "你是 Wiki 审核员。判断两页是否有实质矛盾，只回 `YES: 原因` 或 `NO`。",
                f"页 A [[{a}]]：\n{wiki.read_page(a)}\n\n页 B [[{b}]]：\n{wiki.read_page(b)}",
            )
            if verdict.strip().upper().startswith("YES"):
                report.contradictions.append(f"[[{a}]] vs [[{b}]]: {verdict.strip()}")
    return report
