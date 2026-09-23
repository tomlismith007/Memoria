import React, { useEffect, useState } from "react";
import { CheckCircle2, Cpu, Settings, X } from "lucide-react";
import { PillButton } from "./PillButton";

interface SettingsData {
  llm_base_url: string;
  llm_api_key: string;
  llm_model: string;
  embed_base_url: string;
  embed_api_key: string;
  embed_model: string;
  demo_mode: boolean;
}

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [config, setConfig] = useState<SettingsData>({
    llm_base_url: "https://api.openai.com/v1",
    llm_api_key: "",
    llm_model: "gpt-4o-mini",
    embed_base_url: "https://api.openai.com/v1",
    embed_api_key: "",
    embed_model: "text-embedding-3-small",
    demo_mode: false,
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      setSuccess(false);
      fetch("/api/config")
        .then((r) => r.json())
        .then((data) => {
          setConfig({ ...data, demo_mode: false });
        })
        .catch((e) => console.error(e))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  const handleSave = async () => {
    setSaving(true);
    setSuccess(false);
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...config, demo_mode: false }),
      });
      if (res.ok) {
        setSuccess(true);
        setTimeout(() => setSuccess(false), 3000);
      } else {
        alert("保存配置失败");
      }
    } catch (e: any) {
      alert(`保存失败: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const applyPreset = (preset: "openai" | "deepseek" | "ollama") => {
    if (preset === "openai") {
      setConfig((p) => ({
        ...p,
        llm_base_url: "https://api.openai.com/v1",
        llm_model: "gpt-4o-mini",
        embed_base_url: "https://api.openai.com/v1",
        embed_model: "text-embedding-3-small",
      }));
    } else if (preset === "deepseek") {
      setConfig((p) => ({
        ...p,
        llm_base_url: "https://api.deepseek.com/v1",
        llm_model: "deepseek-chat",
      }));
    } else if (preset === "ollama") {
      setConfig((p) => ({
        ...p,
        llm_base_url: "http://localhost:11434/v1",
        llm_model: "qwen2.5:7b",
        embed_base_url: "http://localhost:11434/v1",
        embed_model: "nomic-embed-text",
        llm_api_key: "ollama",
        embed_api_key: "ollama",
      }));
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-900/40 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-3xl border border-zinc-200 shadow-2xl max-w-lg w-full p-6 md:p-8 space-y-6">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-zinc-100 flex items-center justify-center text-zinc-700">
              <Settings className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-zinc-900">模型与环境配置</h2>
              <p className="text-xs text-zinc-400">配置底层 LLM 与向量 Embedding 连接</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Model Key Settings */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400">快速预设:</span>
            {(["openai", "deepseek", "ollama"] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => applyPreset(p)}
                className="rounded-full px-2.5 py-0.5 text-xs bg-zinc-100 hover:bg-zinc-200/70 text-zinc-700 transition-colors capitalize cursor-pointer"
              >
                {p}
              </button>
            ))}
          </div>

          <div className="space-y-3 text-xs">
            <div>
              <label className="font-medium text-zinc-700 block mb-1">
                LLM Base URL (OpenAI 兼容接口)
              </label>
              <input
                type="text"
                value={config.llm_base_url}
                onChange={(e) => setConfig({ ...config, llm_base_url: e.target.value })}
                className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                placeholder="https://api.openai.com/v1"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="font-medium text-zinc-700 block mb-1">LLM API Key</label>
                <input
                  type="password"
                  value={config.llm_api_key}
                  onChange={(e) => setConfig({ ...config, llm_api_key: e.target.value })}
                  className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                  placeholder="sk-..."
                />
              </div>
              <div>
                <label className="font-medium text-zinc-700 block mb-1">LLM Model</label>
                <input
                  type="text"
                  value={config.llm_model}
                  onChange={(e) => setConfig({ ...config, llm_model: e.target.value })}
                  className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                  placeholder="gpt-4o-mini"
                />
              </div>
            </div>

            <div>
              <label className="font-medium text-zinc-700 block mb-1">
                Embedding Base URL
              </label>
              <input
                type="text"
                value={config.embed_base_url}
                onChange={(e) => setConfig({ ...config, embed_base_url: e.target.value })}
                className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                placeholder="https://api.openai.com/v1"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="font-medium text-zinc-700 block mb-1">Embedding API Key</label>
                <input
                  type="password"
                  value={config.embed_api_key}
                  onChange={(e) => setConfig({ ...config, embed_api_key: e.target.value })}
                  className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                  placeholder="留空则复用 LLM Key"
                />
              </div>
              <div>
                <label className="font-medium text-zinc-700 block mb-1">Embedding Model</label>
                <input
                  type="text"
                  value={config.embed_model}
                  onChange={(e) => setConfig({ ...config, embed_model: e.target.value })}
                  className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                  placeholder="text-embedding-3-small"
                />
              </div>
            </div>
          </div>
        </div>

        {success && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 text-xs text-emerald-800 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>配置已成功更新并保存至本地！</span>
          </div>
        )}

        <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-zinc-100">
          <PillButton variant="secondary" size="sm" onClick={onClose}>
            关闭
          </PillButton>
          <PillButton
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "保存中..." : "保存配置"}
          </PillButton>
        </div>
      </div>
    </div>
  );
};
