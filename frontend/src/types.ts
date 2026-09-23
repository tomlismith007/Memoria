export interface Citation {
  ref: number;
  doc_id: string;
  chunk: number;
  start: number;
}

export interface AskResponse {
  text: string;
  source: "wiki" | "rag+wiki";
  wiki_pages: string[];
  citations: Citation[];
}

export interface WikiPageSummary {
  name: string;
  links: string[];
  length: number;
}

export interface WikiListResponse {
  pages: WikiPageSummary[];
  lint: {
    broken: [string, string][];
    orphans: string[];
  };
}

export interface WikiPageDetail {
  name: string;
  content: string;
  links: string[];
  backlinks: string[];
}

export interface MailItem {
  id: string;
  msg_id: string;
  subject: string;
  sender: string;
  snippet: string;
  category: "营销" | "通知" | "待办";
  summary: string;
  protected: boolean;
  can_archive: boolean;
}

export interface IngestResponse {
  doc_id: string;
  chunks: number;
  wiki_pages: string[];
  origin?: string;
  filename?: string;
}
