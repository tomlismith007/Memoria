import React, { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  FileUp,
  FileText,
  Loader2,
  Trash2,
  UploadCloud,
  FileCode,
} from "lucide-react";
import { api } from "../api";
import type { DocumentListResponse, IngestResponse } from "../types";
import { PillBadge } from "../components/ui/PillBadge";
import { PillButton } from "../components/ui/PillButton";
import { RoundedCard } from "../components/ui/RoundedCard";

interface IngestViewProps {
  onNavigateWiki: (pageName: string) => void;
}

export const IngestView: React.FC<IngestViewProps> = ({ onNavigateWiki }) => {
  const [text, setText] = useState("");
  const [origin, setOrigin] = useState("note.md");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [docs, setDocs] = useState<DocumentListResponse | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadDocs = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch {
      // The library listing is an enhancement; ingest still works without it.
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const handleDelete = async (docId: string, name: string) => {
    if (
      !window.confirm(
        `删除文档「${name}」？其全部向量切块与 raw 原文将被清除，已编译的 Wiki 页面保留。`
      )
    ) {
      return;
    }
    setDeletingId(docId);
    try {
      await api.deleteDocument(docId);
      await loadDocs();
    } catch (err: any) {
      alert(`删除失败: ${err.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  const handleIngestText = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await api.ingestText(text, origin || "note.md");
      setResult(res);
      setText("");
      await loadDocs();
    } catch (err: any) {
      alert(`文档双写摄入失败: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setLoading(true);
    setResult(null);
    try {
      const res = await api.ingestFile(file);
      setResult(res);
      await loadDocs();
    } catch (err: any) {
      alert(`文件上传双写失败: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="min-w-0 space-y-6 animate-fade-in max-w-4xl mx-auto">
      {/* Header */}
      <div className="border-b border-zinc-200/80 pb-4">
        <h1 className="text-xl md:text-2xl font-semibold text-zinc-900 tracking-tight flex items-start sm:items-center gap-2 break-words">
          <UploadCloud className="w-5 h-5 text-zinc-700 shrink-0" />
          <span>文档双写摄入中心 (Dual-Write Ingest)</span>
        </h1>
        <p className="text-xs text-zinc-500 mt-1">
          一份原始资料，双流水线并行：解析分块入向量库供检索 + LLM 阅读编译入 Wiki 供沉淀。
        </p>
      </div>

      {/* Drag & Drop File Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`rounded-3xl border-2 border-dashed p-6 sm:p-8 text-center transition-all ${
          dragOver
            ? "border-zinc-900 bg-zinc-100/70"
            : "border-zinc-200 bg-white hover:border-zinc-300 shadow-sm"
        }`}
      >
        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="w-12 h-12 rounded-full bg-zinc-100 flex items-center justify-center text-zinc-600">
            <FileUp className="w-6 h-6" />
          </div>
          <div>
            <span className="text-sm font-medium text-zinc-800">
              拖拽 PDF、Markdown、TXT 文档至此
            </span>
            <span className="text-xs text-zinc-400 block mt-0.5">
              或点击下方按钮选择本地文件
            </span>
          </div>
          <label className="cursor-pointer">
            <input
              type="file"
              accept=".pdf,.md,.txt"
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) {
                  handleFileUpload(e.target.files[0]);
                }
              }}
            />
            <span className="rounded-full bg-zinc-900 text-white px-4 py-2 text-xs font-medium hover:bg-zinc-800 transition-colors inline-block pill-active">
              选择本地文档
            </span>
          </label>
        </div>
      </div>

      {/* Or Paste Direct Text Card */}
      <RoundedCard variant="primary" className="space-y-4">
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider flex items-center gap-1.5">
            <FileCode className="w-4 h-4 text-zinc-500" />
            或直接粘贴正文 Markdown 内容
          </span>
          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
            <label className="text-xs text-zinc-500 font-mono">来源文件名:</label>
            <input
              type="text"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="note.md"
              className="w-full min-w-0 rounded-full bg-zinc-50 border border-zinc-200 px-3 py-1 text-xs text-zinc-800 outline-none sm:w-36 font-mono"
            />
          </div>
        </div>

        <textarea
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="在此处粘贴任何需要摄入知识库的长文本或 Markdown 笔记..."
          className="w-full min-w-0 rounded-2xl bg-zinc-50/70 border border-zinc-200/80 p-4 text-xs md:text-sm text-zinc-900 placeholder:text-zinc-400 outline-none focus:border-zinc-400 font-mono leading-relaxed"
        />

        <div className="flex justify-end">
          <PillButton
            onClick={handleIngestText}
            disabled={loading || !text.trim()}
            icon={loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />}
          >
            {loading ? "双写编译中..." : "开始双写摄入"}
          </PillButton>
        </div>
      </RoundedCard>

      {/* Ingestion Results Display */}
      {result && (
        <RoundedCard variant="primary" className="space-y-4 animate-fade-in border-emerald-200">
          <div className="flex items-center gap-2 text-emerald-800 font-medium text-sm">
            <CheckCircle2 className="w-5 h-5 text-emerald-600" />
            <span>双写流水线摄入完成！</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="bg-zinc-50 rounded-2xl p-4 border border-zinc-100 space-y-1.5">
              <span className="font-semibold text-zinc-700 block">RAG 向量库</span>
              <div className="font-mono text-zinc-500 text-[11px] truncate">
                Doc ID: {result.doc_id}
              </div>
              <div className="text-zinc-600">
                已切分并存入向量切块：<strong>{result.chunks}</strong> 个
              </div>
            </div>

            <div className="bg-emerald-50/60 rounded-2xl p-4 border border-emerald-100 space-y-2">
              <span className="font-semibold text-emerald-900 block">
                LLM Wiki 编译页面 ({result.wiki_pages.length})
              </span>
              {result.wiki_pages.length === 0 ? (
                <span className="text-zinc-400">无新增/修改页面</span>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {result.wiki_pages.map((p) => (
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
              )}
            </div>
          </div>
        </RoundedCard>
      )}

      {/* Document Library: list + deletion (red line: vectors + raw purged together) */}
      {docs && (docs.documents.length > 0 || docs.vector_only.length > 0) && (
        <RoundedCard variant="primary" className="space-y-3">
          <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider flex items-center gap-1.5">
            <FileText className="w-4 h-4 text-zinc-500" />
            已入库文档（{docs.documents.length + docs.vector_only.length}）
          </span>

          <div className="divide-y divide-zinc-100 rounded-2xl border border-zinc-100">
            {docs.documents.map((d) => (
              <div key={d.doc_id} className="flex items-center gap-3 px-3 py-2.5 text-xs min-w-0">
                <FileText className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                <span className="font-mono text-zinc-800 truncate flex-1 min-w-0">{d.name}</span>
                <span className="font-mono text-zinc-400 truncate max-w-[110px] hidden sm:inline">
                  {d.doc_id}
                </span>
                <PillBadge variant={d.chunks > 0 ? "citation" : "neutral"}>
                  {d.chunks > 0 ? `${d.chunks} 切块` : "未入库"}
                </PillBadge>
                <button
                  type="button"
                  onClick={() => handleDelete(d.doc_id, d.name)}
                  disabled={deletingId === d.doc_id}
                  title="删除该文档的全部向量与 raw 原文"
                  className="rounded-full p-1.5 text-zinc-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer disabled:opacity-40 shrink-0"
                >
                  {deletingId === d.doc_id ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            ))}

            {docs.vector_only.map((d) => (
              <div key={d.doc_id} className="flex items-center gap-3 px-3 py-2.5 text-xs min-w-0">
                <FileText className="w-3.5 h-3.5 text-zinc-300 shrink-0" />
                <span className="font-mono text-zinc-400 truncate flex-1 min-w-0">
                  {d.doc_id}（raw 原文已不在）
                </span>
                <PillBadge variant="citation">{d.chunks} 切块</PillBadge>
                <button
                  type="button"
                  onClick={() => handleDelete(d.doc_id, d.doc_id)}
                  disabled={deletingId === d.doc_id}
                  title="清除残留向量"
                  className="rounded-full p-1.5 text-zinc-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer disabled:opacity-40 shrink-0"
                >
                  {deletingId === d.doc_id ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            ))}
          </div>

          <p className="text-[11px] text-zinc-400">
            删除会同时清除该文档的全部向量与 raw 原文（无孤儿向量）；已编译的 Wiki 页面保留。
          </p>
        </RoundedCard>
      )}
    </div>
  );
};
