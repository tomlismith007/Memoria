import React from "react";
import { ArrowLeft, ArrowRight, Plus } from "lucide-react";
import type { CustomModel, ModelApiFormat } from "../../types";

export interface ProviderTemplate {
  id: string;
  name: string;
  tagline: string;
  baseUrl: string;
  apiFormat: ModelApiFormat;
  defaultChatModel: string;
  suggestedModels: CustomModel[];
  monogram: string;
}

export const PROVIDER_TEMPLATES: ProviderTemplate[] = [
  {
    id: "deepseek",
    name: "DeepSeek",
    tagline: "深度求索 · 官方高速公网 API",
    baseUrl: "https://api.deepseek.com/v1",
    apiFormat: "chat_completions",
    defaultChatModel: "deepseek-chat",
    suggestedModels: [
      { id: "deepseek-chat", name: "DeepSeek V3", tags: ["Chat", "通用"], enabled: true, model_type: "chat" },
      { id: "deepseek-reasoner", name: "DeepSeek R1", tags: ["推理", "思维链"], enabled: true, model_type: "chat" },
    ],
    monogram: "DS",
  },
  {
    id: "openai",
    name: "OpenAI",
    tagline: "GPT-4o / o3-mini · 官方公网网关",
    baseUrl: "https://api.openai.com/v1",
    apiFormat: "chat_completions",
    defaultChatModel: "gpt-4o",
    suggestedModels: [
      { id: "gpt-4o", name: "GPT-4o", tags: ["视觉", "强推理"], enabled: true, model_type: "chat" },
      { id: "gpt-4o-mini", name: "GPT-4o mini", tags: ["快速", "经济"], enabled: true, model_type: "chat" },
      { id: "o3-mini", name: "o3-mini", tags: ["推理", "代码"], enabled: true, model_type: "chat" },
      { id: "text-embedding-3-small", name: "Embedding 3 Small", tags: ["Embedding"], enabled: true, model_type: "embedding" },
    ],
    monogram: "OA",
  },
  {
    id: "anthropic",
    name: "Claude (Anthropic)",
    tagline: "Claude 3.5 Sonnet · 官方 Messages API",
    baseUrl: "https://api.anthropic.com/v1",
    apiFormat: "anthropic_messages",
    defaultChatModel: "claude-3-5-sonnet-20241022",
    suggestedModels: [
      { id: "claude-3-5-sonnet-20241022", name: "Claude 3.5 Sonnet", tags: ["编码", "长文本", "视觉"], enabled: true, model_type: "chat" },
      { id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku", tags: ["超快", "轻量"], enabled: true, model_type: "chat" },
    ],
    monogram: "AN",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    tagline: "全球聚合网关 · 一站调用全球顶尖大模型",
    baseUrl: "https://openrouter.ai/api/v1",
    apiFormat: "chat_completions",
    defaultChatModel: "anthropic/claude-3.5-sonnet",
    suggestedModels: [
      { id: "anthropic/claude-3.5-sonnet", name: "Claude 3.5 Sonnet", tags: ["Chat", "1M"], enabled: true, model_type: "chat" },
      { id: "deepseek/deepseek-r1", name: "DeepSeek R1", tags: ["推理", "开源"], enabled: true, model_type: "chat" },
      { id: "openai/gpt-4o", name: "GPT-4o", tags: ["视觉", "通用"], enabled: true, model_type: "chat" },
    ],
    monogram: "OR",
  },
  {
    id: "siliconflow",
    name: "SiliconFlow (硅基流动)",
    tagline: "国内优质高速大模型 API 聚合网关",
    baseUrl: "https://api.siliconflow.cn/v1",
    apiFormat: "chat_completions",
    defaultChatModel: "deepseek-ai/DeepSeek-V3",
    suggestedModels: [
      { id: "deepseek-ai/DeepSeek-V3", name: "DeepSeek-V3", tags: ["Chat", "高性能"], enabled: true, model_type: "chat" },
      { id: "deepseek-ai/DeepSeek-R1", name: "DeepSeek-R1", tags: ["推理", "开源"], enabled: true, model_type: "chat" },
      { id: "BAAI/bge-m3", name: "BGE-M3", tags: ["Embedding", "多语言"], enabled: true, model_type: "embedding" },
    ],
    monogram: "SF",
  },
  {
    id: "stepfun",
    name: "StepFun (阶跃星辰)",
    tagline: "阶跃星辰千亿级长文本与多模态大模型",
    baseUrl: "https://api.stepfun.com/v1",
    apiFormat: "chat_completions",
    defaultChatModel: "step-1-8k",
    suggestedModels: [
      { id: "step-1-8k", name: "Step-1 8k", tags: ["Chat", "高速"], enabled: true, model_type: "chat" },
      { id: "step-1-32k", name: "Step-1 32k", tags: ["Chat", "长文本"], enabled: true, model_type: "chat" },
    ],
    monogram: "ST",
  },
];

interface ProviderTemplatePickerProps {
  onBack: () => void;
  onSelect: (template: ProviderTemplate | null) => void;
}

export const ProviderTemplatePicker: React.FC<ProviderTemplatePickerProps> = ({
  onBack,
  onSelect,
}) => {
  return (
    <div className="p-5 sm:p-7 space-y-6 animate-fade-in">
      <div className="flex items-center gap-3 pb-5 border-b border-zinc-100">
        <button
          type="button"
          onClick={onBack}
          className="p-1.5 rounded-full text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
          title="返回"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <h3 className="text-base font-semibold text-zinc-900">添加供应商</h3>
          <p className="text-xs text-zinc-400 mt-0.5">选择一个预设，或从空白开始。</p>
        </div>
      </div>

      <div className="space-y-1.5">
        <button
          type="button"
          onClick={() => onSelect(null)}
          className="w-full flex items-center gap-3 rounded-xl px-3 py-3 text-left hover:bg-zinc-50 transition-colors"
        >
          <span className="w-8 h-8 rounded-lg border border-dashed border-zinc-300 flex items-center justify-center text-zinc-500 shrink-0">
            <Plus className="w-4 h-4" />
          </span>
          <span className="flex-1 min-w-0">
            <span className="block text-sm font-medium text-zinc-900">自定义供应商</span>
            <span className="block text-xs text-zinc-400 mt-0.5">手动填写连接信息</span>
          </span>
          <ArrowRight className="w-4 h-4 text-zinc-300" />
        </button>

        {PROVIDER_TEMPLATES.map((template) => (
          <button
            type="button"
            key={template.id}
            onClick={() => onSelect(template)}
            className="w-full flex items-center gap-3 rounded-xl px-3 py-3 text-left hover:bg-zinc-50 transition-colors"
          >
            <span className="w-8 h-8 rounded-lg border border-zinc-200 flex items-center justify-center text-[10px] font-semibold text-zinc-700 shrink-0">
              {template.monogram}
            </span>
            <span className="flex-1 min-w-0">
              <span className="block text-sm font-medium text-zinc-900">{template.name}</span>
              <span className="block text-xs text-zinc-400 mt-0.5">
                {template.apiFormat === "anthropic_messages" ? "Claude Messages" : "OpenAI 兼容"}
              </span>
            </span>
            <ArrowRight className="w-4 h-4 text-zinc-300" />
          </button>
        ))}
      </div>
    </div>
  );
};
