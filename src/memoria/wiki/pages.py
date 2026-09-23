"""LLM Wiki storage layer: raw/ (read-only) + wiki/ pages + schema.md + index.md + log.md."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")

DEFAULT_SCHEMA_MD = """# Wiki 写作规范（给 LLM）

## 页面结构

- `# 标题` 开头；正文分节；末尾 `## 来源` 列出事实出处（raw 文件名或问答日期）。
- 每个事实句必须可溯源，无来源不写。

## 双向链接

- 用 `[[页名]]` 引用其他页面；新建链接时，被引页面也应加回链。
- 页名即文件名（`[[服务到期]]` 对应 `wiki/服务到期.md`）。

## 索引与日志

- `index.md` 由程序生成，不要手改；`log.md` 每次变更追加一行（日期 + 改了什么）。
- `raw/` 只读：原始资料永不修改，缺资料就写"缺"，不编。

## 更新原则

- ingest 一次约更新 10 个相关页面；小改优先补链接，大改才重写整页。
"""

INDEX_MD = "# Index\n\n{entries}\n"
LOG_MD = "# Log\n"


def extract_links(text: str) -> list[str]:
    """Ordered-unique [[links]] in a page."""
    seen: list[str] = []
    for m in LINK_RE.findall(text):
        name = m.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


class Wiki:
    """File-backed wiki. All writes are confined to wiki/ — raw/ is never written."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.pages_dir = self.root / "wiki"
        self.schema_file = self.root / "schema.md"
        self.index_file = self.pages_dir / "index.md"
        self.log_file = self.pages_dir / "log.md"

    def ensure_layout(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        if not self.schema_file.exists():
            self.schema_file.write_text(DEFAULT_SCHEMA_MD, encoding="utf-8")
        if not self.index_file.exists():
            self.index_file.write_text(INDEX_MD.format(entries=""), encoding="utf-8")
        if not self.log_file.exists():
            self.log_file.write_text(LOG_MD, encoding="utf-8")

    def _page_file(self, name: str) -> Path:
        # Red line, enforced: no traversal, no absolute paths — writes stay in wiki/.
        if not name or "/" in name or "\\" in name or ".." in name:
            raise ValueError(f"invalid page name: {name!r}")
        return self.pages_dir / f"{name}.md"

    def write_page(self, name: str, text: str) -> None:
        self._page_file(name).write_text(text, encoding="utf-8")

    def read_page(self, name: str) -> str | None:
        try:
            return self._page_file(name).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None

    def list_pages(self) -> list[str]:
        return sorted(
            p.stem
            for p in self.pages_dir.glob("*.md")
            if p.stem not in ("index", "log")
        )

    def build_index(self) -> str:
        """Regenerate index.md from current pages and their [[links]]."""
        lines = []
        for name in self.list_pages():
            links = extract_links(self.read_page(name) or "")
            suffix = " -> " + ", ".join(f"[[{l}]]" for l in sorted(links)) if links else ""
            lines.append(f"- [[{name}]]{suffix}")
        content = INDEX_MD.format(entries="\n".join(lines) + ("\n" if lines else ""))
        self.index_file.write_text(content, encoding="utf-8")
        return content

    def append_log(self, entry: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(f"- {ts}: {entry}\n")
