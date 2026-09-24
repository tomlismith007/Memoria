import React from "react";
import { Box, Loader2, Plus } from "lucide-react";
import type { CustomProvider } from "../../types";

interface ProviderSidebarProps {
  providers: CustomProvider[];
  loading: boolean;
  isCreatingNew: boolean;
  showTemplatePicker: boolean;
  selectedProviderId: string;
  activeProviderId: string;
  formName: string;
  onSelectProvider: (providerId: string) => void;
  onOpenTemplatePicker: () => void;
}

export const ProviderSidebar: React.FC<ProviderSidebarProps> = ({
  providers,
  loading,
  isCreatingNew,
  showTemplatePicker,
  selectedProviderId,
  activeProviderId,
  formName,
  onSelectProvider,
  onOpenTemplatePicker,
}) => {
  return (
    <aside className="w-20 md:w-60 shrink-0 flex flex-col border-r border-zinc-200/80 bg-zinc-50/50 p-2 md:p-4">
      <div className="hidden md:flex items-center justify-between mb-4">
        <span className="text-xs font-medium text-zinc-500">供应商</span>
        <button
          type="button"
          onClick={onOpenTemplatePicker}
          className="text-zinc-400 hover:text-zinc-900 transition-colors"
          title="添加供应商"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {loading && providers.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-zinc-400">
          <Loader2 className="w-4 h-4 animate-spin" />
        </div>
      ) : providers.length === 0 && !isCreatingNew && !showTemplatePicker ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center">
          <Box className="w-5 h-5 text-zinc-300" />
          <span className="hidden md:block text-xs text-zinc-400">暂无供应商</span>
          <button
            type="button"
            onClick={onOpenTemplatePicker}
            className="hidden md:inline text-xs text-zinc-700 hover:text-black transition-colors"
          >
            添加一个
          </button>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-1">
          {providers.map((provider) => {
            const isSelected =
              !isCreatingNew && !showTemplatePicker && provider.id === selectedProviderId;
            const isActive = provider.id === activeProviderId;
            const isConfigured = Boolean(provider.base_url) && provider.enabled;
            const monogram = provider.name.trim().slice(0, 2).toUpperCase() || "LLM";

            return (
              <button
                type="button"
                key={provider.id}
                onClick={() => onSelectProvider(provider.id)}
                title={`${provider.name} (${provider.base_url})`}
                className={`w-full flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors ${
                  isSelected
                    ? "bg-white text-zinc-900 border border-zinc-300 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
                    : "border border-transparent text-zinc-600 hover:bg-white/80"
                }`}
              >
                <span className="w-6 h-6 rounded-lg border border-zinc-200 bg-white flex items-center justify-center text-[9px] font-semibold shrink-0">
                  {monogram}
                </span>
                <span className="flex-1 min-w-0 truncate text-sm hidden md:block">
                  {provider.name}
                </span>
                <span
                  title={isConfigured ? "已启用" : "未就绪或已禁用"}
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    isActive
                      ? "bg-emerald-500"
                      : isConfigured
                      ? "bg-zinc-300"
                      : "bg-zinc-200"
                  }`}
                />
              </button>
            );
          })}

          {isCreatingNew && (
            <div className="px-2.5 py-2">
              <div className="hidden md:block text-[11px] text-zinc-400 mb-2">草稿</div>
              <div className="flex items-center gap-2.5 rounded-xl border border-dashed border-zinc-300 px-2.5 py-2 text-zinc-700">
                <span className="w-6 h-6 rounded-lg bg-zinc-900 text-white flex items-center justify-center shrink-0">
                  <Plus className="w-3.5 h-3.5" />
                </span>
                <span className="text-sm truncate hidden md:block">
                  {formName.trim() || "新建供应商"}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );
};
