import React, { useCallback, useEffect, useState } from "react";
import { NavTab, SegmentedNav } from "./components/ui/SegmentedNav";
import { AskView } from "./views/AskView";
import { WikiView } from "./views/WikiView";
import { MailView } from "./views/MailView";
import { IngestView } from "./views/IngestView";

import { Settings } from "lucide-react";
import { SettingsModal } from "./components/ui/SettingsModal";
import { api } from "./api";
import type { ProvidersConfigResponse } from "./types";

interface ActiveModelInfo {
  providerName: string;
  modelName: string;
}

const DEFAULT_MODEL_INFO: ActiveModelInfo = {
  providerName: "自定义供应商",
  modelName: "默认模型",
};

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>("ask");
  const [selectedWikiPage, setSelectedWikiPage] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modelInfo, setModelInfo] = useState<ActiveModelInfo>(DEFAULT_MODEL_INFO);
  const [providersData, setProvidersData] = useState<ProvidersConfigResponse | null>(null);

  const refreshModelInfo = useCallback(async () => {
    try {
      const data = await api.getProviders();
      setProvidersData(data);
      const active = data.providers.find((p) => p.id === data.active_provider_id);
      if (!active) {
        setModelInfo(DEFAULT_MODEL_INFO);
        return;
      }
      const model = active.models.find(
        (m) => m.id === data.active_chat_model && m.model_type === "chat"
      );
      setModelInfo({
        providerName: active.name,
        modelName: model?.name || data.active_chat_model || "默认模型",
      });
    } catch {}
  }, []);

  // Refresh on mount and whenever the settings modal closes, so the ask
  // page always reflects saved provider/model state.
  useEffect(() => {
    if (settingsOpen) return;
    refreshModelInfo();
  }, [settingsOpen, refreshModelInfo]);

  const handleSelectModel = useCallback(
    async (providerId: string, modelId: string) => {
      try {
        await api.activateProvider(providerId, modelId, "chat");
        await refreshModelInfo();
      } catch {}
    },
    [refreshModelInfo]
  );

  const handleNavigateWiki = (pageName: string) => {
    setSelectedWikiPage(pageName);
    setActiveTab("wiki");
  };

  return (
    <div className="min-h-screen min-w-0 flex flex-col bg-canvas text-ink-primary font-sans antialiased selection:bg-zinc-200">
      {/* Top Floating Capsule Nav Header */}
      <header className="sticky top-0 z-40 py-3 sm:py-4 px-3 sm:px-4 bg-canvas/80 backdrop-blur-md">
        <div className="max-w-5xl mx-auto min-w-0 flex items-center justify-between gap-2">
          <div className="flex shrink-0 items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-zinc-900 text-white flex items-center justify-center font-bold text-xs shadow-sm">
              M
            </div>
            <span className="hidden whitespace-nowrap font-semibold text-sm tracking-tight text-zinc-900 md:inline">
              Memoria
            </span>
          </div>

          <SegmentedNav activeTab={activeTab} onChange={setActiveTab} />

          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-1.5 text-[11px] text-zinc-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="hidden sm:inline">本地就绪</span>
            </div>
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              title="模型与系统配置"
              className="h-11 w-11 shrink-0 rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20 md:h-auto md:w-auto"
            >
              <Settings className="w-5 h-5 md:w-4 md:h-4" />
            </button>
          </div>
        </div>
      </header>

      <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 max-w-5xl w-full mx-auto px-4 md:px-8 py-4 flex flex-col">
        {activeTab === "ask" && (
          <AskView
            onNavigateWiki={handleNavigateWiki}
            activeModelInfo={modelInfo}
            providers={providersData?.providers ?? []}
            activeProviderId={providersData?.active_provider_id ?? ""}
            activeChatModel={providersData?.active_chat_model ?? ""}
            onSelectModel={handleSelectModel}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        )}
        {activeTab === "wiki" && <WikiView initialPage={selectedWikiPage} />}
        {activeTab === "mail" && <MailView />}
        {activeTab === "ingest" && <IngestView onNavigateWiki={handleNavigateWiki} />}
      </main>
    </div>
  );
};

export default App;
