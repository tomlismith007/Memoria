import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Cpu,
  Loader2,
  RefreshCw,
  Settings,
  X,
} from "lucide-react";
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

interface TestResult {
  llm_ok: boolean;
  llm_latency_ms: number;
  llm_message: string;
  embed_ok: boolean;
  embed_latency_ms: number;
  embed_message: string;
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

  // Model listing state
  const [fetchingLLMModels, setFetchingLLMModels] = useState(false);
  const [fetchingEmbedModels, setFetchingEmbedModels] = useState(false);
  const [llmModelList, setLlmModelList] = useState<string[]>([]);
  const [embedModelList, setEmbedModelList] = useState<string[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Connection testing state
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      setSuccess(false);
      setFetchError(null);
      setTestResult(null);
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

  const handleFetchLLMModels = async () => {
    setFetchingLLMModels(true);
    setFetchError(null);
    try {
      const res = await fetch("/api/config/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: config.llm_base_url,
          api_key: config.llm_api_key,
        }),
      });
      const data = await res.json();
      if (res.ok && data.models) {
        setLlmModelList(data.models);
        if (data.models.length === 0) {
          setFetchError("接口返回的模型列表为空");
        }
      } else {
        setFetchError(data.message || "获取模型列表失败");
      }
    } catch (err: any) {
      setFetchError(`获取失败: ${err.message}`);
    } finally {
      setFetchingLLMModels(false);
    }
  };

  const handleFetchEmbedModels = async () => {
    setFetchingEmbedModels(true);
    setFetchError(null);
    const baseUrl = config.embed_base_url || config.llm_base_url;
    const apiKey = config.embed_api_key || config.llm_api_key;
    try {
      const res = await fetch("/api/config/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseUrl,
          api_key: apiKey,
        }),
      });
      const data = await res.json();
      if (res.ok && data.models) {
        setEmbedModelList(data.models);
        if (data.models.length === 0) {
          setFetchError("接口返回的模型列表为空");
        }
      } else {
        setFetchError(data.message || "获取模型列表失败");
      }
    } catch (err: any) {
      setFetchError(`获取失败: ${err.message}`);
    } finally {
      setFetchingEmbedModels(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch("/api/config/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm_base_url: config.llm_base_url,
          llm_api_key: config.llm_api_key,
          llm_model: config.llm_model,
          embed_base_url: config.embed_base_url,
          embed_api_key: config.embed_api_key,
          embed_model: config.embed_model,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setTestResult(data);
      } else {
        setTestResult({
          llm_ok: false,
          llm_latency_ms: 0,
          llm_message: data.message || "测试请求失败",
          embed_ok: false,
          embed_latency_ms: 0,
          embed_message: "未执行",
        });
      }
    } catch (err: any) {
      setTestResult({
        llm_ok: false,
        llm_latency_ms: 0,
        llm_message: `网络错误: ${err.message}`,
        embed_ok: false,
        embed_latency_ms: 0,
        embed_message: "未执行",
      });
    } finally {
      setTesting(false);
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-900/40 backdrop-blur-sm animate-fade-in overflow-y-auto">
      <div className="bg-white rounded-3xl border border-zinc-200 shadow-2xl max-w-lg w-full p-6 md:p-8 space-y-5 my-8">
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
            className="rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors cursor-pointer"
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

          <div className="space-y-3.5 text-xs">
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
                <div className="flex items-center justify-between mb-1">
                  <label className="font-medium text-zinc-700">LLM Model</label>
                  <button
                    type="button"
                    onClick={handleFetchLLMModels}
                    disabled={fetchingLLMModels || !config.llm_base_url}
                    className="text-[11px] text-zinc-600 hover:text-zinc-900 flex items-center gap-1 hover:underline cursor-pointer disabled:opacity-40"
                    title="从远端接口获取可用模型列表"
                  >
                    {fetchingLLMModels ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3 h-3" />
                    )}
                    <span>获取模型</span>
                  </button>
                </div>
                <input
                  type="text"
                  value={config.llm_model}
                  onChange={(e) => setConfig({ ...config, llm_model: e.target.value })}
                  className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                  placeholder="gpt-4o-mini"
                />
              </div>
            </div>

            {/* Quick LLM Model Selection Pills */}
            {llmModelList.length > 0 && (
              <div className="space-y-1 p-2.5 bg-zinc-50/80 rounded-xl border border-zinc-200/60 animate-fade-in">
                <div className="flex items-center justify-between text-[11px] text-zinc-500">
                  <span>选择可用 LLM 模型 ({llmModelList.length} 个):</span>
                  <button
                    onClick={() => setLlmModelList([])}
                    className="text-[10px] text-zinc-400 hover:text-zinc-600"
                  >
                    收起
                  </button>
                </div>
                <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto pt-1">
                  {llmModelList.map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setConfig({ ...config, llm_model: m })}
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono transition-all cursor-pointer ${
                        config.llm_model === m
                          ? "bg-[#09090b] text-white"
                          : "bg-white border border-zinc-200 text-zinc-600 hover:border-zinc-400"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className="font-medium text-zinc-700 block mb-1">
                Embedding Base URL
              </label>
              <input
                type="text"
                value={config.embed_base_url}
                onChange={(e) => setConfig({ ...config, embed_base_url: e.target.value })}
                className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                placeholder="留空则默认复用 LLM Base URL"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
                <div className="flex items-center justify-between mb-1">
                  <label className="font-medium text-zinc-700">Embedding Model</label>
                  <button
                    type="button"
                    onClick={handleFetchEmbedModels}
                    disabled={fetchingEmbedModels || (!config.embed_base_url && !config.llm_base_url)}
                    className="text-[11px] text-zinc-600 hover:text-zinc-900 flex items-center gap-1 hover:underline cursor-pointer disabled:opacity-40"
                    title="从远端接口获取可用向量模型列表"
                  >
                    {fetchingEmbedModels ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3 h-3" />
                    )}
                    <span>获取模型</span>
                  </button>
                </div>
                <input
                  type="text"
                  value={config.embed_model}
                  onChange={(e) => setConfig({ ...config, embed_model: e.target.value })}
                  className="w-full rounded-xl border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-400 font-mono text-xs"
                  placeholder="text-embedding-3-small"
                />
              </div>
            </div>

            {/* Quick Embedding Model Selection Pills */}
            {embedModelList.length > 0 && (
              <div className="space-y-1 p-2.5 bg-zinc-50/80 rounded-xl border border-zinc-200/60 animate-fade-in">
                <div className="flex items-center justify-between text-[11px] text-zinc-500">
                  <span>选择向量 Embedding 模型 ({embedModelList.length} 个):</span>
                  <button
                    onClick={() => setEmbedModelList([])}
                    className="text-[10px] text-zinc-400 hover:text-zinc-600"
                  >
                    收起
                  </button>
                </div>
                <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto pt-1">
                  {embedModelList.map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setConfig({ ...config, embed_model: m })}
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono transition-all cursor-pointer ${
                        config.embed_model === m
                          ? "bg-[#09090b] text-white"
                          : "bg-white border border-zinc-200 text-zinc-600 hover:border-zinc-400"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {fetchError && (
              <div className="p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-center gap-1.5">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>{fetchError}</span>
              </div>
            )}
          </div>
        </div>

        {/* Connectivity Test Diagnostics Card */}
        {testResult && (
          <div className="space-y-2 p-3 bg-zinc-50/80 rounded-2xl border border-zinc-200/80 text-xs animate-fade-in">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-zinc-700">连通性诊断结果:</span>
              <button
                onClick={() => setTestResult(null)}
                className="text-[11px] text-zinc-400 hover:text-zinc-600 cursor-pointer"
              >
                清除
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {/* LLM Status */}
              <div
                className={`p-2.5 rounded-xl border flex items-start gap-2 ${
                  testResult.llm_ok
                    ? "bg-emerald-50/60 border-emerald-200 text-emerald-900"
                    : "bg-rose-50/60 border-rose-200 text-rose-900"
                }`}
              >
                {testResult.llm_ok ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <div className="font-medium text-[11px] flex items-center gap-1.5">
                    <span>LLM 对话模型</span>
                    {testResult.llm_ok && (
                      <span className="px-1.5 py-0.2 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-mono">
                        {testResult.llm_latency_ms}ms
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] text-zinc-600 truncate mt-0.5" title={testResult.llm_message}>
                    {testResult.llm_message}
                  </div>
                </div>
              </div>

              {/* Embedding Status */}
              <div
                className={`p-2.5 rounded-xl border flex items-start gap-2 ${
                  testResult.embed_ok
                    ? "bg-emerald-50/60 border-emerald-200 text-emerald-900"
                    : "bg-rose-50/60 border-rose-200 text-rose-900"
                }`}
              >
                {testResult.embed_ok ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <div className="font-medium text-[11px] flex items-center gap-1.5">
                    <span>Embedding 向量</span>
                    {testResult.embed_ok && testResult.embed_latency_ms > 0 && (
                      <span className="px-1.5 py-0.2 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-mono">
                        {testResult.embed_latency_ms}ms
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] text-zinc-600 truncate mt-0.5" title={testResult.embed_message}>
                    {testResult.embed_message}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {success && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 text-xs text-emerald-800 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>配置已成功更新并保存至本地！</span>
          </div>
        )}

        <div className="flex items-center justify-between pt-2 border-t border-zinc-100">
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={testing || !config.llm_base_url}
            className="rounded-full px-3.5 py-1.5 text-xs font-medium border border-zinc-200/90 text-zinc-700 hover:bg-zinc-100 hover:text-zinc-900 transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            title="测试当前配置的接口连通性与响应延迟"
          >
            {testing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-500" />
            ) : (
              <Activity className="w-3.5 h-3.5 text-zinc-500" />
            )}
            <span>{testing ? "测试中..." : "测试连接"}</span>
          </button>

          <div className="flex items-center gap-2">
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
    </div>
  );
};
