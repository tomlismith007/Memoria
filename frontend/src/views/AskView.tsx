import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookmarkPlus,
  CheckCircle2,
  Loader2,
  Plus,
  Search,
} from "lucide-react";
import { api } from "../api";
import type { AskResponse, Citation } from "../types";
import { MarkdownRenderer } from "../components/ui/MarkdownRenderer";
import { PillBadge } from "../components/ui/PillBadge";
import { PillButton } from "../components/ui/PillButton";
import { RoundedCard } from "../components/ui/RoundedCard";

interface MessageItem {
  id: string;
  question: string;
  result?: AskResponse;
  loading: boolean;
  error?: string;
  archivedPage?: string;
  activeCitation?: Citation | null;
}

const ASK_HISTORY_KEY = "memoria.ask.history";
const ASK_HISTORY_VERSION = 1;

interface PersistedMessage {
  id: string;
  question: string;
  result?: AskResponse;
  error?: string;
  archivedPage?: string;
}

interface PersistedConversation {
  version: number;
  messages: PersistedMessage[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const isCitation = (value: unknown): value is Citation => {
  if (!isRecord(value)) return false;
  return (
    typeof value.ref === "number" &&
    typeof value.doc_id === "string" &&
    typeof value.chunk === "number" &&
    typeof value.start === "number"
  );
};

const isAskResponse = (value: unknown): value is AskResponse => {
  if (!isRecord(value)) return false;
  return (
    typeof value.text === "string" &&
    (value.source === "wiki" || value.source === "rag+wiki") &&
    Array.isArray(value.wiki_pages) &&
    value.wiki_pages.every((page) => typeof page === "string") &&
    Array.isArray(value.citations) &&
    value.citations.every(isCitation)
  );
};

const loadMessages = (): MessageItem[] => {
  try {
    const raw = localStorage.getItem(ASK_HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.version !== ASK_HISTORY_VERSION || !Array.isArray(parsed.messages)) {
      return [];
    }

    const restored: MessageItem[] = [];
    const seen = new Set<string>();
    for (const value of parsed.messages) {
      if (!isRecord(value)) continue;
      const id = value.id;
      const question = value.question;
      if (typeof id !== "string" || !id || typeof question !== "string" || !question || seen.has(id)) {
        continue;
      }
      const result = value.result;
      const error = value.error;
      const archivedPage = value.archivedPage;
      if (result !== undefined && !isAskResponse(result)) continue;
      if (error !== undefined && typeof error !== "string") continue;
      if (archivedPage !== undefined && typeof archivedPage !== "string") continue;
      if (result === undefined && error === undefined) continue;
      seen.add(id);
      restored.push({
        id,
        question,
        result,
        error,
        archivedPage,
        loading: false,
      });
    }
    return restored;
  } catch {
    return [];
  }
};

const persistMessages = (messages: MessageItem[]): void => {
  try {
    const payload: PersistedConversation = {
      version: ASK_HISTORY_VERSION,
      messages: messages
        .filter((message) => !message.loading && (message.result !== undefined || message.error !== undefined))
        .map(({ id, question, result, error, archivedPage }) => ({
          id,
          question,
          result,
          error,
          archivedPage,
        })),
    };
    localStorage.setItem(ASK_HISTORY_KEY, JSON.stringify(payload));
  } catch {
    // Storage is an enhancement; keep the in-memory conversation usable.
  }
};

interface AskViewProps {
  onNavigateWiki: (pageName: string) => void;
}

export const AskView: React.FC<AskViewProps> = ({ onNavigateWiki }) => {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<MessageItem[]>(() => loadMessages());
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [activeModelInfo, setActiveModelInfo] = useState<{
    providerName: string;
    modelName: string;
  }>(() => {
    try {
      const activeId = localStorage.getItem("memoria_active_provider_cache") || "";
      const activeModel = localStorage.getItem("memoria_active_model_cache") || "";
      const cachedStr = localStorage.getItem("memoria_custom_providers_cache");
      if (cachedStr) {
        const cached = JSON.parse(cachedStr);
        const p = Array.isArray(cached) ? cached.find((item: any) => item.id === activeId) : null;
        if (p) {
          return {
            providerName: p.name,
            modelName: activeModel || p.models?.[0]?.id || "未选择模型",
          };
        }
      }
      if (activeModel) {
        return { providerName: activeId || "自定义", modelName: activeModel };
      }
    } catch {}
    return { providerName: "自定义供应商", modelName: "默认模型" };
  });

  const hasStarted = messages.length > 0;

  useEffect(() => {
    const updateModelInfo = () => {
      try {
        const activeId = localStorage.getItem("memoria_active_provider_cache") || "";
        const activeModel = localStorage.getItem("memoria_active_model_cache") || "";
        const cachedStr = localStorage.getItem("memoria_custom_providers_cache");
        if (cachedStr) {
          const cached = JSON.parse(cachedStr);
          const p = Array.isArray(cached) ? cached.find((item: any) => item.id === activeId) : null;
          if (p) {
            setActiveModelInfo({
              providerName: p.name,
              modelName: activeModel || p.models?.[0]?.id || "未选择模型",
            });
            return;
          }
        }
        if (activeModel) {
          setActiveModelInfo({ providerName: activeId || "自定义", modelName: activeModel });
        }
      } catch {}
    };

    updateModelInfo();
    window.addEventListener("storage", updateModelInfo);
    return () => window.removeEventListener("storage", updateModelInfo);
  }, []);

  useEffect(() => {
    persistMessages(messages);
  }, [messages]);

  useEffect(() => {
    if (hasStarted) {
      scrollRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleAsk = async (queryText?: string) => {
    const q = (queryText || input).trim();
    if (!q) return;

    const msgId = Date.now().toString();
    const newMsg: MessageItem = {
      id: msgId,
      question: q,
      loading: true,
    };

    setMessages((prev) => [...prev, newMsg]);
    setInput("");

    try {
      const res = await api.ask(q);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? {
                ...m,
                loading: false,
                result: res,
                activeCitation: res.citations.length > 0 ? res.citations[0] : null,
              }
            : m
        )
      );
    } catch (err: any) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? {
                ...m,
                loading: false,
                error: err.message || "请求失败，请检查模型连接",
              }
            : m
        )
      );
    }
  };

  const handleNewSession = () => {
    if (!window.confirm("清空当前本地问答历史？已沉淀的 Wiki 页面不会被删除。")) return;
    setMessages([]);
    setInput("");
    setArchivingId(null);
  };

  const handleArchive = async (msg: MessageItem) => {
    if (!msg.result) return;
    setArchivingId(msg.id);
    try {
      const res = await api.archiveQA(
        msg.question,
        msg.result.text,
        msg.result.citations
      );
      setMessages((prev) =>
        prev.map((m) => (m.id === msg.id ? { ...m, archivedPage: res.name } : m))
      );
    } catch (err: any) {
      alert(`归档失败: ${err.message}`);
    } finally {
      setArchivingId(null);
    }
  };

  const setActiveCitation = (msgId: string, cit: Citation) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, activeCitation: cit } : m))
    );
  };

  return (
    <div className="flex-1 min-w-0 flex flex-col w-full">
      {/* 1. INITIAL STATE: Centered in the middle */}
      {!hasStarted && (
        <div className="flex-1 flex flex-col items-center justify-center -mt-10 sm:-mt-16 space-y-6 w-full max-w-3xl md:max-w-4xl mx-auto animate-fade-in px-0 sm:px-4">
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-zinc-900 text-center">
            想探索什么知识？
          </h1>

          {/* Active Model Capsule Badge */}
          <div className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            <span>当前模型:</span>
            <span className="font-mono text-zinc-800 bg-white border border-zinc-200/80 px-2.5 py-0.5 rounded-full shadow-xs">
              {activeModelInfo.providerName} / {activeModelInfo.modelName}
            </span>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAsk();
            }}
            className="w-full rounded-full bg-white border border-zinc-200/90 pl-5 pr-1.5 py-1.5 flex items-center h-12 shadow-[0_4px_24px_-4px_rgba(0,0,0,0.06)] focus-within:ring-2 focus-within:ring-zinc-900/10 focus-within:border-zinc-400 transition-all"
          >
            <Search className="w-4 h-4 text-zinc-400 shrink-0 mr-3" />
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="提出问题，如：服务续费时间是什么时候？"
              className="w-full min-w-0 bg-transparent border-none outline-none text-sm text-zinc-900 placeholder:text-zinc-400"
              autoFocus
            />
            <button
              type="submit"
              disabled={!input.trim()}
              title="发送"
              className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 transition-all duration-150 select-none cursor-pointer ${
                input.trim()
                  ? "bg-[#09090b] text-white shadow-sm hover:bg-black active:scale-95 border border-zinc-900/80"
                  : "bg-zinc-100 text-zinc-300 cursor-not-allowed"
              }`}
            >
              <ArrowUp className="w-4 h-4 stroke-[2.4]" />
            </button>
          </form>

          {/* Quick suggestions */}
          <div className="flex items-center justify-center gap-2 flex-wrap">
            {["服务到期时间？", "Memoria 的架构设计是什么？"].map((q) => (
              <button
                key={q}
                onClick={() => handleAsk(q)}
                className="rounded-full px-4 py-1.5 text-xs bg-white border border-zinc-200/80 hover:border-zinc-300 text-zinc-600 hover:text-zinc-900 shadow-sm transition-all pill-active cursor-pointer"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 2. CONVERSATION THREAD: Auto-anchored bottom bar + scrollable Q&A cards */}
      {hasStarted && (
        <div className="flex-1 flex flex-col justify-between max-w-4xl w-full mx-auto animate-fade-in pb-28 space-y-8">
          <div className="space-y-8">
            <div className="flex justify-end">
              <PillButton
                variant="outline"
                size="sm"
                onClick={handleNewSession}
                title="清空当前本地问答历史"
                icon={<Plus className="w-3.5 h-3.5" />}
              >
                新建会话
              </PillButton>
            </div>
            {messages.map((msg) => (
              <div key={msg.id} className="space-y-4">
                {/* User Message Bubble */}
                <div className="flex justify-end">
                  <div className="rounded-2xl bg-zinc-900 text-white px-5 py-2.5 text-xs md:text-sm max-w-xl min-w-0 break-words font-medium shadow-sm">
                    {msg.question}
                  </div>
                </div>

                {/* Loading Skeleton */}
                {msg.loading && (
                  <RoundedCard variant="primary" className="space-y-4 animate-pulse">
                    <div className="flex items-center gap-2.5 text-xs text-zinc-600 font-medium">
                      <Loader2 className="w-4 h-4 animate-spin text-zinc-800" />
                      <span>正在定位 Wiki 索引并进行向量混合检索...</span>
                    </div>
                    <div className="space-y-2 pt-1">
                      <div className="h-3.5 bg-zinc-100 rounded-full w-5/6"></div>
                      <div className="h-3.5 bg-zinc-100 rounded-full w-4/6"></div>
                      <div className="h-3.5 bg-zinc-100 rounded-full w-3/6"></div>
                    </div>
                  </RoundedCard>
                )}

                {/* Error Card */}
                {msg.error && (
                  <RoundedCard variant="rose" className="text-xs text-rose-800 p-4">
                    <strong>请求遇到问题：</strong> {msg.error}
                  </RoundedCard>
                )}

                {/* Answer Card with Rich Markdown */}
                {msg.result && (
                  <RoundedCard variant="primary" className="space-y-5">
                    <div className="flex items-center justify-between border-b border-zinc-100 pb-3 flex-wrap gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <PillBadge
                          variant={msg.result.source === "wiki" ? "wiki" : "citation"}
                        >
                          {msg.result.source === "wiki" ? "Wiki 知识回答" : "RAG 向量混合回答"}
                        </PillBadge>
                        {msg.result.wiki_pages.map((p) => (
                          <button
                            key={p}
                            onClick={() => onNavigateWiki(p)}
                            className="cursor-pointer"
                          >
                            <PillBadge variant="wiki" interactive>
                              [[{p}]]
                            </PillBadge>
                          </button>
                        ))}
                      </div>

                      <div>
                        {msg.archivedPage ? (
                          <PillBadge variant="wiki" className="gap-1.5 py-1 px-3">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            已沉淀入 [[{msg.archivedPage}]]
                          </PillBadge>
                        ) : (
                          <PillButton
                            variant="outline"
                            size="sm"
                            onClick={() => handleArchive(msg)}
                            disabled={archivingId === msg.id}
                            icon={<BookmarkPlus className="w-3.5 h-3.5" />}
                          >
                            {archivingId === msg.id ? "沉淀中..." : "沉淀为 Wiki 页面"}
                          </PillButton>
                        )}
                      </div>
                    </div>

                    {/* Rich Markdown Answer Text */}
                    <div className="min-w-0 break-words text-sm md:text-base leading-relaxed text-zinc-800 font-sans">
                      <MarkdownRenderer
                        content={msg.result.text}
                        citations={msg.result.citations}
                        activeCitation={msg.activeCitation}
                        onSelectCitation={(c) => setActiveCitation(msg.id, c)}
                        onNavigateWiki={onNavigateWiki}
                      />
                    </div>

                    {/* Citations Preview Box */}
                    {msg.result.citations.length > 0 && (
                      <div className="pt-4 border-t border-zinc-100 space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                            来源溯源切片（{msg.result.citations.length} 处引用）
                          </span>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {msg.result.citations.map((c) => {
                            const isSelected = msg.activeCitation?.ref === c.ref;
                            return (
                              <div
                                key={c.ref}
                                onClick={() => setActiveCitation(msg.id, c)}
                                className={`rounded-2xl p-3 border transition-all cursor-pointer text-xs space-y-1 ${
                                  isSelected
                                    ? "bg-blue-50/60 border-blue-300 shadow-sm"
                                    : "bg-zinc-50/70 border-zinc-100 hover:border-zinc-200"
                                }`}
                              >
                                <div className="flex items-center justify-between font-mono text-[11px] text-zinc-500">
                                  <span className="font-semibold text-blue-700">[{c.ref}] Chunk #{c.chunk}</span>
                                  <span className="truncate max-w-[150px]">{c.doc_id}</span>
                                </div>
                                <div className="text-zinc-600 text-[11px]">
                                  字符偏移量: @{c.start}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </RoundedCard>
                )}
              </div>
            ))}
            <div ref={scrollRef} />
          </div>

          {/* Fixed Floating Bottom Capsule Search Bar */}
          <div className="fixed bottom-0 left-0 right-0 z-30 pointer-events-none pb-6 pt-10 bg-gradient-to-t from-canvas via-canvas/90 to-transparent">
            <div className="max-w-4xl w-full mx-auto px-3 sm:px-4 pointer-events-auto space-y-2">
              <div className="flex justify-end pr-3">
                <div className="flex items-center gap-1.5 text-[11px] text-zinc-400 bg-white/90 backdrop-blur-sm border border-zinc-200/80 px-2.5 py-0.5 rounded-full shadow-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                  <span className="font-mono text-zinc-600">
                    {activeModelInfo.providerName} / {activeModelInfo.modelName}
                  </span>
                </div>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleAsk();
                }}
                className="w-full rounded-full bg-white border border-zinc-200/90 pl-5 pr-1.5 py-1.5 flex items-center h-11 shadow-[0_8px_30px_-6px_rgba(0,0,0,0.08)] focus-within:ring-2 focus-within:ring-zinc-900/10 focus-within:border-zinc-400 transition-all"
              >
                <Search className="w-4 h-4 text-zinc-400 shrink-0 mr-3" />
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="继续提问..."
                  className="w-full min-w-0 bg-transparent border-none outline-none text-sm text-zinc-900 placeholder:text-zinc-400"
                  autoFocus
                />
                <button
                  type="submit"
                  disabled={!input.trim()}
                  title="发送"
                  className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all duration-150 select-none cursor-pointer ${
                    input.trim()
                      ? "bg-[#09090b] text-white shadow-sm hover:bg-black active:scale-95 border border-zinc-900/80"
                      : "bg-zinc-100 text-zinc-300 cursor-not-allowed"
                  }`}
                >
                  <ArrowUp className="w-4 h-4 stroke-[2.4]" />
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
