import React, { useState } from "react";
import {
  CheckCircle2,
  FileUp,
  Loader2,
  UploadCloud,
  FileCode,
} from "lucide-react";
import { api } from "../api";
import type { IngestResponse } from "../types";
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

  const handleIngestText = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await api.ingestText(text, origin || "note.md");
      setResult(res);
      setText("");
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
    <div className="space-y-6 animate-fade-in max-w-4xl mx-auto">
      {/* Header */}
      <div className="border-b border-zinc-200/80 pb-4">
        <h1 className="text-xl md:text-2xl font-semibold text-zinc-900 tracking-tight flex items-center gap-2">
          <UploadCloud className="w-5 h-5 text-zinc-700" />
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
        className={`rounded-3xl border-2 border-dashed p-8 text-center transition-all ${
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
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider flex items-center gap-1.5">
            <FileCode className="w-4 h-4 text-zinc-500" />
            或直接粘贴正文 Markdown 内容
          </span>
          <div className="flex items-center gap-2">
            <label className="text-xs text-zinc-500 font-mono">来源文件名:</label>
            <input
              type="text"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="note.md"
              className="rounded-full bg-zinc-50 border border-zinc-200 px-3 py-1 text-xs text-zinc-800 outline-none w-36 font-mono"
            />
          </div>
        </div>

        <textarea
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="在此处粘贴任何需要摄入知识库的长文本或 Markdown 笔记..."
          className="w-full rounded-2xl bg-zinc-50/70 border border-zinc-200/80 p-4 text-xs md:text-sm text-zinc-900 placeholder:text-zinc-400 outline-none focus:border-zinc-400 font-mono leading-relaxed"
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
    </div>
  );
};
