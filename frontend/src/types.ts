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
  citations_verified?: boolean;
}

interface DocumentInfo {
  doc_id: string;
  name: string;
  chunks: number;
}

interface VectorOnlyDoc {
  doc_id: string;
  chunks: number;
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
  vector_only: VectorOnlyDoc[];
}

interface WikiPageSummary {
  name: string;
  links: string[];
}

export interface WikiListResponse {
  pages: WikiPageSummary[];
  lint: {
    broken: [string, string][];
    orphans: string[];
    contradictions: string[];
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
  subject: string;
  sender: string;
  category: "营销" | "通知" | "待办";
  summary: string;
  protected: boolean;
  can_archive: boolean;
}

/** feat-069: live Gmail fetch readiness travels with every triage response. */
export interface MailTriageResponse {
  triages: MailItem[];
  thread_id: string;
  mail_ready: boolean;
  mail_reason: string;
  pending?: string[];
  error?: string;
}

export interface IngestResponse {
  doc_id: string;
  chunks: number;
  wiki_pages: string[];
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
  api_key_set: boolean;
  masked_api_key?: string;
  enabled: boolean;
  models: CustomModel[];
}

export interface ProvidersConfigResponse {
  active_provider_id: string;
  active_chat_model: string;
  active_embed_provider_id: string;
  active_embed_model: string;
  providers: CustomProvider[];
}

/** feat-049: which LLM capabilities are actually configured. */
export interface CapabilityStatus {
  ready: boolean;
  reason: string;
}

export interface HealthResponse {
  capabilities?: {
    llm: CapabilityStatus;
    embed: CapabilityStatus;
    /** feat-069: present since the mail production-wiring feature. */
    mail?: CapabilityStatus;
  };
}

/** Connectivity probe result: one latency and message per protocol half. */
export interface TestResultResponse {
  llm_ok: boolean;
  llm_latency_ms: number;
  llm_message: string;
  embed_ok?: boolean;
  embed_latency_ms?: number;
  embed_message?: string;
}

/** feat-066: a hash-bound approval record for destructive/external actions. */
export type ProposalKind = "archive" | "delete_doc" | "reindex";

export type ProposalStatus =
  | "awaiting_review"
  | "executing"
  | "succeeded"
  | "failed"
  | "outcome_unknown"
  | "denied"
  | "cancelled"
  | "expired";

export interface ProposalMail {
  msg_id: string;
  subject: string;
  sender: string;
  category: string;
}

export interface Proposal {
  id: string;
  kind: ProposalKind;
  payload: {
    thread_id?: string;
    confirmed_ids?: string[];
    msgs?: ProposalMail[];
    doc_id?: string;
    name?: string | null;
    raw_files?: number;
  };
  content_hash: string;
  status: ProposalStatus;
  created_at: string;
  expires_at: string;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

export interface ProposalListResponse {
  proposals: Proposal[];
}

export interface MailArchiveResponse {
  proposal: Proposal | null;
  blocked: string[];
  message: string;
}

export interface ProposalDecideResponse {
  proposal: Proposal;
}

/** feat-068: append-only inbox entry — mark-read only, no delete. */
export interface AppNotification {
  id: string;
  key: string;
  title: string;
  body: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  notifications: AppNotification[];
}
