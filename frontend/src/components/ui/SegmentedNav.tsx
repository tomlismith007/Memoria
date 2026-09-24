import React from "react";
import { BookOpen, Mail, Sparkles, UploadCloud } from "lucide-react";

export type NavTab = "ask" | "wiki" | "mail" | "ingest";

interface SegmentedNavProps {
  activeTab: NavTab;
  onChange: (tab: NavTab) => void;
}

export const SegmentedNav: React.FC<SegmentedNavProps> = ({
  activeTab,
  onChange,
}) => {
  const tabs: { id: NavTab; label: string; icon: React.ReactNode }[] = [
    { id: "ask", label: "问答与溯源", icon: <Sparkles className="w-4 h-4 md:w-3.5 md:h-3.5" /> },
    { id: "wiki", label: "知识漫游", icon: <BookOpen className="w-4 h-4 md:w-3.5 md:h-3.5" /> },
    { id: "mail", label: "邮件安全", icon: <Mail className="w-4 h-4 md:w-3.5 md:h-3.5" /> },
    { id: "ingest", label: "文档双写", icon: <UploadCloud className="w-4 h-4 md:w-3.5 md:h-3.5" /> },
  ];

  return (
    <div className="flex shrink-0 justify-center">
      <nav className="rounded-full bg-white/90 backdrop-blur-md border border-zinc-200/80 p-0.5 shadow-sm inline-flex items-center gap-0.5 md:gap-1 md:p-1.5">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              aria-label={tab.label}
              aria-current={isActive ? "page" : undefined}
              title={tab.label}
              onClick={() => onChange(tab.id)}
              className={`h-11 w-11 shrink-0 justify-center rounded-full p-0 text-xs font-medium inline-flex items-center gap-2 transition-all duration-150 pill-active cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20 md:h-auto md:w-auto md:px-4 md:py-1.5 ${
                isActive
                  ? "bg-zinc-900 text-white shadow-sm"
                  : "text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100"
              }`}
            >
              {tab.icon}
              <span className="hidden whitespace-nowrap md:inline">{tab.label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
};
