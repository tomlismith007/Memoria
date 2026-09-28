import React from "react";
import { Plus, RefreshCw, X } from "lucide-react";
import { PillButton } from "./PillButton";
import { DeleteConfirmDialog } from "../settings/DeleteConfirmDialog";
import { ProviderSidebar } from "../settings/ProviderSidebar";
import { ModelFormDialog } from "../settings/ModelFormDialog";
import { ProviderDetailForm, ProviderEmptyState } from "../settings/ProviderDetailForm";
import { useProviderConfig } from "../settings/useProviderConfig";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
}) => {
  const ctrl = useProviderConfig(isOpen);
  const {
    providers,
    loading,
    isCreatingNew,
    selectedProvider,
    selectedProviderId,
    activeProviderId,
    activeEmbedProviderId,
    feedback,
    settingsTab,
    formName,
    deleteConfirm,
    setDeleteConfirm,
    refreshProviders,
    handleStartCreate,
    handleSwitchSettingsTab,
    handleSelectProvider,
    handleExecuteDelete,
  } = ctrl;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-zinc-900/40 backdrop-blur-xs animate-fade-in">
      <div
        className="relative w-full max-w-5xl h-[720px] max-h-[92vh] flex flex-col bg-white border border-zinc-200 rounded-2xl shadow-[0_24px_80px_rgba(24,24,27,0.16)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 sm:px-7 py-5 border-b border-zinc-200/80 bg-white z-10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl sm:text-2xl font-semibold text-zinc-950 tracking-[-0.02em]">
                模型设置
              </h2>
              <p className="hidden sm:block text-xs sm:text-sm text-zinc-500 mt-1.5">
                管理模型供应商，配置后可在聊天时选择使用。
              </p>
            </div>

            <div className="flex items-center gap-2">
              {feedback && (
                <span
                  className={`hidden sm:inline text-xs ${
                    feedback.type === "success" ? "text-emerald-600" : "text-rose-600"
                  }`}
                >
                  {feedback.text}
                </span>
              )}
              <button
                type="button"
                onClick={refreshProviders}
                title="重新加载配置"
                className="p-2 rounded-full text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <PillButton
                variant="primary"
                size="sm"
                onClick={handleStartCreate}
                icon={<Plus className="w-3.5 h-3.5" />}
              >
                添加供应商
              </PillButton>
              <button
                type="button"
                onClick={onClose}
                title="关闭"
                className="p-2 rounded-full text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Duplicates SegmentedNav's markup on purpose: SegmentedNav is
              hardcoded to the app's 4 nav tabs, so it is not reusable here. */}
          <div className="mt-4 inline-flex items-center gap-1 rounded-full bg-zinc-100 p-1">
            {(["chat", "embedding"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => handleSwitchSettingsTab(tab)}
                className={`rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  settingsTab === tab
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-800"
                }`}
              >
                {tab === "chat" ? "对话模型" : "向量模型"}
              </button>
            ))}
          </div>
        </div>

        {/* Two-Column Body: Responsive (w-14 on mobile, md:w-56 on desktop) */}
        <div className="flex-1 flex min-h-0 divide-x divide-zinc-200/80 overflow-hidden">
          <ProviderSidebar
            providers={providers}
            loading={loading}
            isCreatingNew={isCreatingNew}
            selectedProviderId={selectedProviderId}
            // The sidebar highlights whichever scope is on screen, so the
            // embedding tab marks the embedding provider as active, not the
            // chat one (they may be different providers entirely).
            activeProviderId={
              settingsTab === "embedding" ? activeEmbedProviderId : activeProviderId
            }
            otherActiveProviderId={
              settingsTab === "embedding" ? activeProviderId : activeEmbedProviderId
            }
            formName={formName}
            onSelectProvider={handleSelectProvider}
            onAddProvider={handleStartCreate}
          />

          {/* Right Column: Provider Details Form OR Empty State */}
          <div className="flex-1 flex flex-col min-w-0 bg-white overflow-y-auto">
            {selectedProvider || isCreatingNew ? (
              <ProviderDetailForm ctrl={ctrl} />
            ) : (
              <ProviderEmptyState ctrl={ctrl} />
            )}
          </div>
        </div>

        <ModelFormDialog ctrl={ctrl} />

        <DeleteConfirmDialog
          target={deleteConfirm}
          onCancel={() => setDeleteConfirm(null)}
          onConfirm={handleExecuteDelete}
        />
      </div>
    </div>
  );
};
