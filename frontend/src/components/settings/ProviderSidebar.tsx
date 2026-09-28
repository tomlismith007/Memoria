import React from "react";
import { Box, Loader2, Plus } from "lucide-react";
import type { CustomProvider } from "../../types";

interface ProviderSidebarProps {
  providers: CustomProvider[];
  loading: boolean;
  isCreatingNew: boolean;
  selectedProviderId: string;
  /** Active provider for the tab currently in view (chat or embedding). */
  activeProviderId: string;
  /** The other scope's active provider, disambiguated when names collide. */
  otherActiveProviderId: string;
  formName: string;
  onSelectProvider: (providerId: string) => void;
  onAddProvider: () => void;
}

export const ProviderSidebar: React.FC<ProviderSidebarProps> = ({
  providers,
  loading,
  isCreatingNew,
  selectedProviderId,
  activeProviderId,
  otherActiveProviderId,
  formName,
  onSelectProvider,
  onAddProvider,
}) => {
  // Two providers may legitimately share a name (e.g. a chat gateway that also
  // serves embeddings). Fall back to the host so the rows stay distinguishable.
  const nameCount = new Map<string, number>();
  for (const p of providers) {
    nameCount.set(p.name, (nameCount.get(p.name) ?? 0) + 1);
  }
  const displayName = (p: CustomProvider) =>
    (nameCount.get(p.name) ?? 0) > 1 ? `${p.name} · ${p.base_url}` : p.name;

  return (
    <aside className="w-20 md:w-60 shrink-0 flex flex-col border-r border-zinc-200/80 bg-zinc-50/50 p-2 md:p-4">
      <div className="hidden md:flex items-center justify-between mb-4">
        <span className="text-xs font-medium text-zinc-500">供应商</span>
        <button
          type="button"
          onClick={onAddProvider}
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
      ) : providers.length === 0 && !isCreatingNew ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center">
          <Box className="w-5 h-5 text-zinc-300" />
          <span className="hidden md:block text-xs text-zinc-400">暂无供应商</span>
          <button
            type="button"
            onClick={onAddProvider}
            className="hidden md:inline text-xs text-zinc-700 hover:text-black transition-colors"
          >
            添加一个
          </button>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-1">
          {providers.map((provider) => {
            const isSelected =
              !isCreatingNew && provider.id === selectedProviderId;
            const isActive = provider.id === activeProviderId;
            const isActiveElsewhere = provider.id === otherActiveProviderId;
            const isConfigured = Boolean(provider.base_url) && provider.enabled;
            const monogram = provider.name.trim().slice(0, 2).toUpperCase() || "LLM";
            const label = displayName(provider);

            return (
              <button
                type="button"
                key={provider.id}
                onClick={() => onSelectProvider(provider.id)}
                title={`${label} (${provider.base_url})`}
                className={`w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
                  isSelected
                    ? "bg-zinc-200/70 text-zinc-900"
                    : "text-zinc-600 hover:bg-zinc-200/50"
                }`}
              >
                <span className="w-6 h-6 rounded-lg border border-zinc-200 bg-white flex items-center justify-center text-[9px] font-semibold shrink-0">
                  {monogram}
                </span>
                <span className="flex-1 min-w-0 truncate text-sm hidden md:block">
                  {label}
                </span>
                <span
                  title={
                    isActive
                      ? "当前生效"
                      : isActiveElsewhere
                      ? "在另一个标签中生效"
                      : isConfigured
                      ? "已启用"
                      : "未就绪或已禁用"
                  }
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    isActive
                      ? "bg-emerald-500"
                      : isActiveElsewhere
                      ? "bg-emerald-300"
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
