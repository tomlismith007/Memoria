import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  FileText,
  Link2,
  RefreshCw,
  Search,
} from "lucide-react";
import { api } from "../api";
import type { WikiListResponse, WikiPageDetail } from "../types";
import { PillBadge } from "../components/ui/PillBadge";
import { PillButton } from "../components/ui/PillButton";
import { RoundedCard } from "../components/ui/RoundedCard";
import { MarkdownRenderer } from "../components/ui/MarkdownRenderer";

interface WikiViewProps {
  initialPage?: string | null;
}

export const WikiView: React.FC<WikiViewProps> = ({ initialPage }) => {
  const [listData, setListData] = useState<WikiListResponse | null>(null);
  const [selectedPage, setSelectedPage] = useState<string | null>(initialPage || null);
  const [pageDetail, setPageDetail] = useState<WikiPageDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [pageLoading, setPageLoading] = useState(false);
  const [search, setSearch] = useState("");

  const loadList = async () => {
    setLoading(true);
    try {
      const data = await api.getWikiPages();
      setListData(data);
      if (!selectedPage && data.pages.length > 0) {
        setSelectedPage(data.pages[0].name);
      }
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadPage = async (name: string) => {
    setPageLoading(true);
    try {
      const detail = await api.getWikiPage(name);
      setPageDetail(detail);
    } catch (err: any) {
      alert(`加载页面 ${name} 失败: ${err.message}`);
    } finally {
      setPageLoading(false);
    }
  };

  useEffect(() => {
    loadList();
  }, []);

  useEffect(() => {
    if (initialPage) {
      setSelectedPage(initialPage);
    }
  }, [initialPage]);

  useEffect(() => {
    if (selectedPage) {
      loadPage(selectedPage);
    }
  }, [selectedPage]);

  const filteredPages =
    listData?.pages.filter((p) =>
      p.name.toLowerCase().includes(search.toLowerCase())
    ) || [];

  // Parse Markdown with [[links]] into clickable pill elements
  const renderWikiContent = (content: string) => {
    const parts = content.split(/(\[\[[^\[\]]+\]\])/g);
    return parts.map((part, idx) => {
      const match = part.match(/\[\[([^\[\]]+)\]\]/);
      if (match) {
        const linkName = match[1];
        return (
          <button
            key={idx}
            onClick={() => setSelectedPage(linkName)}
            className="cursor-pointer mx-0.5 inline-block"
          >
            <PillBadge variant="wiki" interactive>
              [[{linkName}]]
            </PillBadge>
          </button>
        );
      }
      return <span key={idx}>{part}</span>;
    });
  };

  return (
    <div className="min-w-0 space-y-6 animate-fade-in max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col items-start gap-3 border-b border-zinc-200/80 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl md:text-2xl font-semibold text-zinc-900 tracking-tight flex items-start sm:items-center gap-2 break-words">
            <BookOpen className="w-5 h-5 text-zinc-700 shrink-0" />
            <span>LLM Wiki 知识复利库</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            由大模型自动编译与维护的原子 Markdown 页面，以双向链接与全局索引构建知识复利。
          </p>
        </div>
        <PillButton
          variant="outline"
          size="sm"
          onClick={loadList}
          disabled={loading}
          icon={<RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />}
        >
          刷新索引
        </PillButton>
      </div>

      {/* Lint Diagnostics Banner if any broken/orphans */}
      {listData && (listData.lint.broken.length > 0 || listData.lint.orphans.length > 0) && (
        <div className="bg-amber-50/70 border border-amber-200/70 rounded-2xl p-4 flex flex-col items-start gap-2 text-xs text-amber-900 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
            <span>
              <strong>Wiki Lint 诊断</strong>：发现 {listData.lint.broken.length} 个断链，{listData.lint.orphans.length} 个孤立页面。
            </span>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {listData.lint.broken.map(([src, dst], i) => (
              <PillBadge key={i} variant="candidate" className="max-w-full break-all">
                {src} ➔ ?[[{dst}]]
              </PillBadge>
            ))}
          </div>
        </div>
      )}

      {/* Main Split Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
        {/* Left Column: Index Directory */}
        <div className="md:col-span-4 space-y-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索页面..."
              className="w-full rounded-full bg-white border border-zinc-200/80 pl-9 pr-3 py-1.5 text-xs text-zinc-900 placeholder:text-zinc-400 outline-none focus:border-zinc-400"
            />
          </div>

          <div className="bg-white rounded-3xl border border-zinc-200/80 p-3 max-h-[600px] overflow-y-auto space-y-1.5 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-400 px-3 py-1 uppercase tracking-wider">
              全部页面 ({filteredPages.length})
            </div>
            {filteredPages.length === 0 ? (
              <div className="text-center py-8 text-xs text-zinc-400">
                暂无页面
              </div>
            ) : (
              filteredPages.map((page) => {
                const isSelected = selectedPage === page.name;
                return (
                  <button
                    key={page.name}
                    onClick={() => setSelectedPage(page.name)}
                    className={`w-full text-left rounded-2xl px-3.5 py-2.5 text-xs flex items-center justify-between transition-all pill-active cursor-pointer ${
                      isSelected
                        ? "bg-zinc-900 text-white font-medium shadow-sm"
                        : "text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    <span className="truncate pr-2">{page.name}</span>
                    <span
                      className={`text-[10px] rounded-full px-2 py-0.5 shrink-0 ${
                        isSelected
                          ? "bg-zinc-800 text-zinc-300"
                          : "bg-zinc-100 text-zinc-500"
                      }`}
                    >
                      {page.links.length} 链接
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Page Content & Backlinks */}
        <div className="md:col-span-8">
          <RoundedCard variant="primary" className="min-h-[500px] space-y-5">
            {pageLoading ? (
              <div className="flex items-center justify-center py-24 text-zinc-400 text-xs">
                加载页面中...
              </div>
            ) : pageDetail ? (
              <div className="space-y-6">
                <div className="border-b border-zinc-100 pb-4 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="min-w-0 break-words text-xl font-bold text-zinc-900">
                    {pageDetail.name}
                  </h2>
                  <span className="shrink-0 text-xs font-mono text-zinc-400">
                    {pageDetail.content.length} 字符
                  </span>
                </div>

                {/* Markdown text */}
                <div className="min-w-0 break-words text-sm leading-relaxed text-zinc-800 font-sans">
                  <MarkdownRenderer
                    content={pageDetail.content}
                    onNavigateWiki={setSelectedPage}
                  />
                </div>

                {/* Backlinks & Forward Links Drawer */}
                <div className="border-t border-zinc-100 pt-5 space-y-4">
                  <div>
                    <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider block mb-2">
                      反向引用（引用了本页的页面）
                    </span>
                    {pageDetail.backlinks.length === 0 ? (
                      <span className="text-xs text-zinc-400">暂无反向引用</span>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {pageDetail.backlinks.map((bl) => (
                          <button
                            key={bl}
                            onClick={() => setSelectedPage(bl)}
                            className="cursor-pointer"
                          >
                            <PillBadge variant="wiki" interactive>
                              <Link2 className="w-3 h-3" />
                              [[{bl}]]
                            </PillBadge>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider block mb-2">
                      正向引用（本页引用的页面）
                    </span>
                    {pageDetail.links.length === 0 ? (
                      <span className="text-xs text-zinc-400">暂无出链</span>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {pageDetail.links.map((fl) => (
                          <button
                            key={fl}
                            onClick={() => setSelectedPage(fl)}
                            className="cursor-pointer"
                          >
                            <PillBadge variant="neutral" interactive>
                              <ArrowRight className="w-3 h-3" />
                              [[{fl}]]
                            </PillBadge>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-28 text-zinc-400 text-xs">
                请在左侧选择一个 Wiki 页面浏览
              </div>
            )}
          </RoundedCard>
        </div>
      </div>
    </div>
  );
};
