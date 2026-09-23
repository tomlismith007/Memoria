import React from "react";
import type { Citation } from "../../types";
import { PillBadge } from "./PillBadge";

interface MarkdownRendererProps {
  content: string;
  citations?: Citation[];
  activeCitation?: Citation | null;
  onSelectCitation?: (citation: Citation) => void;
  onNavigateWiki?: (pageName: string) => void;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  citations = [],
  activeCitation,
  onSelectCitation,
  onNavigateWiki,
}) => {
  // Helper to render inline elements (bold, code, [[wiki]], [n] citations)
  const renderInline = (text: string) => {
    // Regex for:
    // 1. [[WikiLinks]]
    // 2. [n] citations
    // 3. `code`
    // 4. **bold**
    const tokens = text.split(/(\[\[[^\[\]]+\]\]|\[\d+\]|`[^`]+`|\*\*[^*]+\*\*)/g);

    return tokens.map((tok, idx) => {
      // 1. [[WikiLink]]
      const wikiMatch = tok.match(/^\[\[([^\[\]]+)\]\]$/);
      if (wikiMatch) {
        const pageName = wikiMatch[1];
        return (
          <button
            key={idx}
            type="button"
            onClick={() => onNavigateWiki?.(pageName)}
            className="inline-block mx-0.5 cursor-pointer align-baseline"
          >
            <PillBadge variant="wiki" interactive>
              [[{pageName}]]
            </PillBadge>
          </button>
        );
      }

      // 2. [n] Citation
      const citeMatch = tok.match(/^\[(\d+)\]$/);
      if (citeMatch && citations.length > 0) {
        const refNum = parseInt(citeMatch[1], 10);
        const cit = citations.find((c) => c.ref === refNum);
        const isActive = activeCitation?.ref === refNum;
        return (
          <button
            key={idx}
            type="button"
            onClick={() => cit && onSelectCitation?.(cit)}
            className={`inline-flex items-center px-1.5 py-0.2 mx-0.5 text-xs font-mono font-semibold rounded-full border transition-all cursor-pointer align-baseline select-none ${
              isActive
                ? "bg-blue-600 text-white border-blue-600 scale-105"
                : "bg-blue-50 text-blue-700 border-blue-200/80 hover:bg-blue-100"
            }`}
          >
            [{refNum}]
          </button>
        );
      }

      // 3. `inline code`
      const codeMatch = tok.match(/^`([^`]+)`$/);
      if (codeMatch) {
        return (
          <code
            key={idx}
            className="px-1.5 py-0.5 rounded bg-zinc-100 text-zinc-800 font-mono text-xs border border-zinc-200/60"
          >
            {codeMatch[1]}
          </code>
        );
      }

      // 4. **bold**
      const boldMatch = tok.match(/^\*\*([^*]+)\*\*$/);
      if (boldMatch) {
        return (
          <strong key={idx} className="font-semibold text-zinc-900">
            {boldMatch[1]}
          </strong>
        );
      }

      return <span key={idx}>{tok}</span>;
    });
  };

  // Line-by-line block parser
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBuffer: string[] = [];

  lines.forEach((line, lineIdx) => {
    // Code block toggle
    if (line.trim().startsWith("```")) {
      if (inCodeBlock) {
        elements.push(
          <pre
            key={`code-${lineIdx}`}
            className="bg-zinc-900 text-zinc-100 rounded-2xl p-4 font-mono text-xs overflow-x-auto my-3 leading-relaxed shadow-sm"
          >
            <code>{codeBuffer.join("\n")}</code>
          </pre>
        );
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      return;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      return;
    }

    // Headings
    if (line.startsWith("# ")) {
      elements.push(
        <h1
          key={lineIdx}
          className="text-xl md:text-2xl font-bold text-zinc-900 mt-5 mb-2.5 tracking-tight border-b border-zinc-100 pb-2"
        >
          {renderInline(line.slice(2))}
        </h1>
      );
      return;
    }
    if (line.startsWith("## ")) {
      elements.push(
        <h2
          key={lineIdx}
          className="text-base md:text-lg font-semibold text-zinc-900 mt-4 mb-2 tracking-tight"
        >
          {renderInline(line.slice(3))}
        </h2>
      );
      return;
    }
    if (line.startsWith("### ")) {
      elements.push(
        <h3
          key={lineIdx}
          className="text-sm md:text-base font-semibold text-zinc-800 mt-3 mb-1.5"
        >
          {renderInline(line.slice(4))}
        </h3>
      );
      return;
    }

    // Blockquote
    if (line.startsWith("> ")) {
      elements.push(
        <blockquote
          key={lineIdx}
          className="border-l-2 border-zinc-300 pl-3.5 italic text-zinc-600 my-2.5 text-xs md:text-sm"
        >
          {renderInline(line.slice(2))}
        </blockquote>
      );
      return;
    }

    // Bullet points
    if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
      const bulletText = line.trim().slice(2);
      elements.push(
        <li
          key={lineIdx}
          className="list-disc ml-5 my-1 text-xs md:text-sm text-zinc-700 leading-relaxed"
        >
          {renderInline(bulletText)}
        </li>
      );
      return;
    }

    // Empty lines
    if (!line.trim()) {
      elements.push(<div key={lineIdx} className="h-2" />);
      return;
    }

    // Regular paragraph
    elements.push(
      <p
        key={lineIdx}
        className="text-xs md:text-sm text-zinc-800 leading-relaxed my-1"
      >
        {renderInline(line)}
      </p>
    );
  });

  return <div className="space-y-1 font-sans">{elements}</div>;
};
