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
    { id: "ask", label: "问答与溯源", icon: <Sparkles className="w-3.5 h-3.5" /> },
    { id: "wiki", label: "知识漫游", icon: <BookOpen className="w-3.5 h-3.5" /> },
    { id: "mail", label: "邮件安全", icon: <Mail className="w-3.5 h-3.5" /> },
    { id: "ingest", label: "文档双写", icon: <UploadCloud className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="flex justify-center">
      <nav className="rounded-full bg-white/90 backdrop-blur-md border border-zinc-200/80 p-1.5 shadow-sm inline-flex items-center gap-1">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onChange(tab.id)}
              className={`rounded-full px-4 py-1.5 text-xs font-medium inline-flex items-center gap-2 transition-all duration-150 pill-active cursor-pointer ${
                isActive
                  ? "bg-zinc-900 text-white shadow-sm"
                  : "text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100"
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
};
