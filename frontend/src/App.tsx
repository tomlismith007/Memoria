import React, { useState } from "react";
import { NavTab, SegmentedNav } from "./components/ui/SegmentedNav";
import { AskView } from "./views/AskView";
import { WikiView } from "./views/WikiView";
import { MailView } from "./views/MailView";
import { IngestView } from "./views/IngestView";

import { Settings } from "lucide-react";
import { SettingsModal } from "./components/ui/SettingsModal";

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>("ask");
  const [selectedWikiPage, setSelectedWikiPage] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const handleNavigateWiki = (pageName: string) => {
    setSelectedWikiPage(pageName);
    setActiveTab("wiki");
  };

  return (
    <div className="min-h-screen flex flex-col bg-canvas text-ink-primary font-sans antialiased selection:bg-zinc-200">
      {/* Top Floating Capsule Nav Header */}
      <header className="sticky top-0 z-40 py-4 px-4 bg-canvas/80 backdrop-blur-md">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-zinc-900 text-white flex items-center justify-center font-bold text-xs shadow-sm">
              M
            </div>
            <span className="font-semibold text-sm tracking-tight text-zinc-900">
              Memoria
            </span>
          </div>

          <SegmentedNav activeTab={activeTab} onChange={setActiveTab} />

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-[11px] text-zinc-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="hidden sm:inline">本地就绪</span>
            </div>
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              title="模型与系统配置"
              className="rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors cursor-pointer"
            >
              <Settings className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* Main Content Area */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 md:px-8 py-4 flex flex-col">
        {activeTab === "ask" && <AskView onNavigateWiki={handleNavigateWiki} />}
        {activeTab === "wiki" && <WikiView initialPage={selectedWikiPage} />}
        {activeTab === "mail" && <MailView />}
        {activeTab === "ingest" && <IngestView onNavigateWiki={handleNavigateWiki} />}
      </main>
    </div>
  );
};

export default App;
