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

export type ModelApiFormat =
  | "chat_completions"
  | "anthropic_messages"
  | "openai_responses";

export interface CustomModel {
  id: string;
  name: string;
  tags: string[];
  enabled: boolean;
  model_type: "chat" | "embedding";
}

export interface CustomProvider {
  id: string;
  name: string;
  base_url: string;
  api_format: ModelApiFormat;
  api_key?: string;
  api_key_set: boolean;
  masked_api_key?: string;
  enabled: boolean;
  models: CustomModel[];
}

export interface ProvidersConfigResponse {
  status: string;
  active_provider_id: string;
  active_chat_model: string;
  active_embed_provider_id: string;
  active_embed_model: string;
  providers: CustomProvider[];
}
