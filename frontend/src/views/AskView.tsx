import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUp,
  BookmarkPlus,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  Search,
  Settings2,
} from "lucide-react";
import { api } from "../api";
import type { AskResponse, Citation, CustomProvider } from "../types";
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
  session_id?: string;
  messages: PersistedMessage[];
}

const newSessionId = (): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

// Tolerant restore: this cache is only ever written by persistMessages below,
// so a light shape check + try/parse is enough — a corrupt file just starts a
// fresh conversation instead of being replayed.
const loadSession = (): { sessionId: string; messages: MessageItem[] } => {
  try {
    const raw = localStorage.getItem(ASK_HISTORY_KEY);
    if (!raw) return { sessionId: newSessionId(), messages: [] };
    const parsed = JSON.parse(raw) as Partial<PersistedConversation> | null;
    if (!parsed || parsed.version !== ASK_HISTORY_VERSION || !Array.isArray(parsed.messages)) {
      return { sessionId: newSessionId(), messages: [] };
    }
    const messages: MessageItem[] = [];
    for (const m of parsed.messages) {
      if (
        !m ||
        typeof m.id !== "string" ||
        !m.id ||
        typeof m.question !== "string" ||
        !m.question ||
        (m.result === undefined && m.error === undefined)
      ) {
        continue;
      }
      messages.push({
        id: m.id,
        question: m.question,
        result: m.result,
        error: typeof m.error === "string" ? m.error : undefined,
        archivedPage: typeof m.archivedPage === "string" ? m.archivedPage : undefined,
        loading: false,
      });
    }
    return {
      sessionId:
        typeof parsed.session_id === "string" && parsed.session_id
          ? parsed.session_id
          : newSessionId(),
      messages,
    };
  } catch {
    return { sessionId: newSessionId(), messages: [] };
  }
};

const persistMessages = (messages: MessageItem[], sessionId: string): void => {
  try {
    const payload: PersistedConversation = {
      version: ASK_HISTORY_VERSION,
      session_id: sessionId,
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
  activeModelInfo: { providerName: string; modelName: string };
  providers: CustomProvider[];
  activeProviderId: string;
  activeChatModel: string;
  onSelectModel: (providerId: string, modelId: string) => void;
  onOpenSettings: () => void;
}

interface ModelPickerBadgeProps {
  providerName: string;
  modelName: string;
  providers: CustomProvider[];
  activeProviderId: string;
  activeChatModel: string;
  onSelectModel: (providerId: string, modelId: string) => void;
  onOpenSettings: () => void;
  align?: "center" | "right";
  placement?: "bottom" | "top";
}

// Capsule trigger + cascading provider → model picker menu (chat models only).
const ModelPickerBadge: React.FC<ModelPickerBadgeProps> = ({
  providerName,
  modelName,
  providers,
  activeProviderId,
  activeChatModel,
  onSelectModel,
  onOpenSettings,
  align = "center",
  placement = "bottom",
}) => {
  const [open, setOpen] = useState(false);
  const [expandedProviderId, setExpandedProviderId] = useState<string | null>(null);
  const enabledProviders = providers.filter((p) => p.enabled);
  const expandedProvider = enabledProviders.find((p) => p.id === expandedProviderId) || null;
  const expandedChatModels = expandedProvider
    ? expandedProvider.models.filter((m) => m.model_type === "chat")
    : [];

  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
          setExpandedProviderId(null);
        }}
        title="点击切换供应商与模型"
        className="font-mono text-zinc-800 bg-white border border-zinc-200/80 px-2.5 py-0.5 rounded-full shadow-xs hover:border-zinc-400 transition-colors cursor-pointer flex items-center gap-1 max-w-[300px]"
      >
        <span className="truncate">
          {providerName} / {modelName}
        </span>
        <ChevronDown
          className={`w-3 h-3 text-zinc-400 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40 cursor-default" onClick={() => setOpen(false)} />
          <div
            className={`absolute w-60 bg-white border border-zinc-200 rounded-xl shadow-lg py-1.5 z-50 animate-fade-in text-left ${
              placement === "top" ? "bottom-full mb-2" : "top-full mt-2"
            } ${align === "right" ? "right-0" : "left-1/2 -translate-x-1/2"}`}
          >
            <div className="px-3 pt-1 pb-1.5">
              <div className="text-[11px] text-zinc-400">{providerName}</div>
              <div className="flex items-center gap-1.5 py-0.5 min-w-0">
                <span className="font-mono text-sm font-medium text-zinc-900 truncate">
                  {modelName}
                </span>
                <Check className="w-3.5 h-3.5 text-zinc-900 shrink-0" />
              </div>
            </div>

            <div className="border-t border-zinc-100 my-1" />

            <div className="max-h-60 overflow-y-auto">
              {enabledProviders.length === 0 && (
                <div className="px-3 py-2 text-xs text-zinc-400">暂无可用供应商，请在设置中添加</div>
              )}
              {enabledProviders.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setExpandedProviderId(expandedProviderId === p.id ? null : p.id)}
                  className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-zinc-50 cursor-pointer ${
                    p.id === activeProviderId ? "text-zinc-900 font-medium" : "text-zinc-700"
                  }`}
                >
                  <span className="truncate">{p.name}</span>
                  <ChevronRight className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                </button>
              ))}
            </div>

            {expandedProvider && (
              <div
                className={`mt-1 sm:mt-0 sm:absolute ${
                  placement === "top" ? "sm:bottom-0" : "sm:top-0"
                } ${
                  align === "right" ? "sm:right-full sm:mr-1" : "sm:left-full sm:ml-1"
                } w-full sm:w-56 bg-white border border-zinc-200 rounded-xl shadow-lg py-1 z-50`}
              >
                {expandedChatModels.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-zinc-400">该供应商暂无对话模型</div>
                ) : (
                  expandedChatModels.map((m) => {
                    const isCurrent =
                      expandedProvider.id === activeProviderId && m.id === activeChatModel;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => {
                          onSelectModel(expandedProvider.id, m.id);
                          setOpen(false);
                          setExpandedProviderId(null);
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-50 cursor-pointer"
                      >
                        <span className="font-mono truncate flex-1 text-left">
                          {m.name || m.id}
                        </span>
                        {m.tags
                          .filter((t) => t !== "Chat")
                          .slice(0, 2)
                          .map((tag) => (
                            <span
                              key={tag}
                              className="text-[10px] px-1.5 py-0.5 rounded-md bg-zinc-100 text-zinc-500 shrink-0"
                            >
                              {tag}
                            </span>
                          ))}
                        {isCurrent && <Check className="w-3.5 h-3.5 text-zinc-900 shrink-0" />}
                      </button>
                    );
                  })
                )}
              </div>
            )}

            <div className="border-t border-zinc-100 my-1" />

            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onOpenSettings();
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-50 cursor-pointer"
            >
              <Settings2 className="w-3.5 h-3.5 text-zinc-400" />
              管理模型
            </button>
          </div>
        </>
      )}
    </div>
  );
};

interface AskInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  size: "lg" | "sm";
}

// Capsule ask input shared by the initial hero screen and the floating bottom
// bar; the two differ only in size, shadow and placeholder text.
const AskInput: React.FC<AskInputProps> = ({ value, onChange, onSubmit, placeholder, size }) => {
  const large = size === "lg";
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className={`w-full rounded-full bg-white border border-zinc-200/90 pl-5 pr-1.5 py-1.5 flex items-center ${
        large
          ? "h-12 shadow-[0_4px_24px_-4px_rgba(0,0,0,0.06)]"
          : "h-11 shadow-[0_8px_30px_-6px_rgba(0,0,0,0.08)]"
      } focus-within:ring-2 focus-within:ring-zinc-900/10 focus-within:border-zinc-400 transition-all`}
    >
      <Search className="w-4 h-4 text-zinc-400 shrink-0 mr-3" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full min-w-0 bg-transparent border-none outline-none text-sm text-zinc-900 placeholder:text-zinc-400"
        autoFocus
      />
      <button
        type="submit"
        disabled={!value.trim()}
        title="发送"
        className={`${
          large ? "w-9 h-9" : "w-8 h-8"
        } rounded-full flex items-center justify-center shrink-0 transition-all duration-150 select-none cursor-pointer ${
          value.trim()
            ? "bg-[#09090b] text-white shadow-sm hover:bg-black active:scale-95 border border-zinc-900/80"
            : "bg-zinc-100 text-zinc-300 cursor-not-allowed"
        }`}
      >
        <ArrowUp className="w-4 h-4 stroke-[2.4]" />
      </button>
    </form>
  );
};

export const AskView: React.FC<AskViewProps> = ({
  onNavigateWiki,
  activeModelInfo,
  providers,
  activeProviderId,
  activeChatModel,
  onSelectModel,
  onOpenSettings,
}) => {
  const [input, setInput] = useState("");
  const [session] = useState(() => loadSession());
  const [messages, setMessages] = useState<MessageItem[]>(session.messages);
  const [sessionId, setSessionId] = useState<string>(session.sessionId);
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const hasStarted = messages.length > 0;

  useEffect(() => {
    persistMessages(messages, sessionId);
  }, [messages, sessionId]);

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
      const res = await api.ask(q, sessionId); // conversation_id = graph thread: model sees prior turns
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
    setSessionId(newSessionId()); // fresh conversation => fresh graph memory
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
            <ModelPickerBadge
              providerName={activeModelInfo.providerName}
              modelName={activeModelInfo.modelName}
              providers={providers}
              activeProviderId={activeProviderId}
              activeChatModel={activeChatModel}
              onSelectModel={onSelectModel}
              onOpenSettings={onOpenSettings}
            />
          </div>

          <AskInput
            value={input}
            onChange={setInput}
            onSubmit={() => handleAsk()}
            placeholder="提出问题，如：服务续费时间是什么时候？"
            size="lg"
          />

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
                        {msg.result.citations_verified === false && (
                          <PillBadge
                            variant="warning"
                            title="部分内容没有可溯源的出处，请谨慎采信"
                          >
                            <AlertTriangle className="w-3 h-3" />
                            部分内容未溯源
                          </PillBadge>
                        )}
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
                <div className="flex items-center gap-1.5 text-[11px] text-zinc-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                  <ModelPickerBadge
                    providerName={activeModelInfo.providerName}
                    modelName={activeModelInfo.modelName}
                    providers={providers}
                    activeProviderId={activeProviderId}
                    activeChatModel={activeChatModel}
                    onSelectModel={onSelectModel}
                    onOpenSettings={onOpenSettings}
                    align="right"
                    placement="top"
                  />
                </div>
              </div>
              <AskInput
                value={input}
                onChange={setInput}
                onSubmit={() => handleAsk()}
                placeholder="继续提问..."
                size="sm"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
