import type {
  Citation,
  CustomProvider,
  DocumentListResponse,
  HealthResponse,
  IngestResponse,
  MailArchiveResponse,
  MailTriageResponse,
  AppNotification,
  AskStreamCitations,
  MemoryCreateResponse,
  NotificationListResponse,
  ModelApiFormat,
  Proposal,
  ProposalDecideResponse,
  ProposalKind,
  ProposalListResponse,
  ProvidersConfigResponse,
  TestResultResponse,
  WikiListResponse,
  WikiPageDetail,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`API error ${res.status}: ${errorText}`);
  }
  return res.json();
}

export const api = {
  getWikiPages: (deep = false) =>
    request<WikiListResponse>(`/api/wiki/pages${deep ? "?deep=true" : ""}`),

  archiveMailFact: (msgId: string, page: string, fact: string) =>
    request<{ page: string; added: boolean; message: string }>("/api/mail/fact", {
      method: "POST",
      body: JSON.stringify({ msg_id: msgId, page, fact }),
    }),

  getWikiPage: (name: string) =>
    request<WikiPageDetail>(`/api/wiki/page/${encodeURIComponent(name)}`),

  archiveQA: (question: string, answer: string, citations: Citation[]) =>
    request<{ name: string; message: string }>("/api/wiki/archive-qa", {
      method: "POST",
      body: JSON.stringify({ question, answer, citations }),
    }),

  getMailTriage: () => request<MailTriageResponse>("/api/mail/triage"),

  archiveMail: (confirmed_ids: string[], thread_id: string) =>
    // feat-066: returns a hash-bound proposal; execution happens via decideProposal.
    request<MailArchiveResponse>("/api/mail/archive", {
      method: "POST",
      body: JSON.stringify({ confirmed_ids, thread_id }),
    }),

  listProposals: (status?: string) =>
    request<ProposalListResponse>(
      `/api/proposals${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ),

  createProposal: (kind: ProposalKind, payload: Record<string, unknown>) =>
    request<{ proposal: Proposal }>("/api/proposals", {
      method: "POST",
      body: JSON.stringify({ kind, payload }),
    }),

  decideProposal: (id: string, decision: "approved" | "denied", content_hash: string) =>
    request<ProposalDecideResponse>(`/api/proposals/${encodeURIComponent(id)}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, content_hash }),
    }),

  createMemory: (text: string, source: string) =>
    request<MemoryCreateResponse>("/api/memories", {
      method: "POST",
      body: JSON.stringify({ text, source }),
    }),

  // feat-039: SSE client. Event contract: start -> delta -> citations -> done | error.
  // A thrown error (including AbortError from the caller's signal) never retries.
  askStream: async (
    question: string,
    conversationId: string,
    handlers: {
      signal?: AbortSignal;
      onDelta?: (text: string) => void;
      onCitations?: (payload: AskStreamCitations) => void;
    }
  ) => {
    const res = await fetch(`${BASE_URL}/api/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal: handlers.signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(`API error ${res.status}: ${await res.text()}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const evt = JSON.parse(line.slice("data: ".length));
        if (evt.type === "delta") handlers.onDelta?.(evt.text);
        else if (evt.type === "citations") handlers.onCitations?.(evt);
        else if (evt.type === "error") throw new Error(evt.message);
      }
    }
  },

  listNotifications: (unreadOnly = false) =>
    request<NotificationListResponse>(
      `/api/notifications${unreadOnly ? "?unread=true" : ""}`
    ),

  markNotificationRead: (id: string) =>
    request<{ notification: AppNotification }>(
      `/api/notifications/${encodeURIComponent(id)}/read`,
      { method: "POST" }
    ),

  ingestText: (text: string, origin: string = "web_input.md") =>
    request<IngestResponse>("/api/ingest", {
      method: "POST",
      body: JSON.stringify({ text, origin }),
    }),

  listDocuments: () => request<DocumentListResponse>("/api/documents"),

  // feat-066: delete/reindex run only under an approved proposal — the views
  // compose createProposal + decideProposal; there is no direct destructive call.

  ingestFile: async (file: File): Promise<IngestResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE_URL}/api/ingest/file`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      throw new Error(`File upload failed: ${await res.text()}`);
    }
    return res.json();
  },

  getProviders: () => request<ProvidersConfigResponse>("/api/config/providers"),

  // feat-049: readiness, so the UI can warn before a call fails with a raw 502.
  getHealth: () => request<HealthResponse>("/api/health"),

  saveProvider: (provider: {
    id?: string;
    name: string;
    base_url: string;
    api_format?: ModelApiFormat;
    api_key?: string;
    enabled?: boolean;
    scope?: "chat" | "embedding";
    active_chat_model?: string;
  }) =>
    request<{ provider: CustomProvider }>("/api/config/providers", {
      method: "POST",
      body: JSON.stringify(provider),
    }),

  deleteProvider: (id: string) =>
    request<{ providers: CustomProvider[] }>(
      `/api/config/providers/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),

  saveProviderModel: (
    providerId: string,
    model: {
      id: string;
      name?: string;
      tags?: string[];
      enabled?: boolean;
      model_type?: "chat" | "embedding";
    }
  ) =>
    request<{ provider: CustomProvider }>(
      `/api/config/providers/${encodeURIComponent(providerId)}/models`,
      {
        method: "POST",
        body: JSON.stringify(model),
      }
    ),

  saveProviderModelsBatch: (
    providerId: string,
    models: Array<{
      id: string;
      name?: string;
      tags?: string[];
      enabled?: boolean;
      model_type?: "chat" | "embedding";
    }>
  ) =>
    request<{ provider: CustomProvider }>(
      `/api/config/providers/${encodeURIComponent(providerId)}/models/batch`,
      {
        method: "POST",
        body: JSON.stringify({ models }),
      }
    ),

  deleteProviderModel: (providerId: string, modelId: string) =>
    request<{ provider: CustomProvider }>(
      `/api/config/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}`,
      { method: "DELETE" }
    ),

  testProvider: (providerId: string, modelId?: string, modelType: "chat" | "embedding" = "chat") =>
    request<TestResultResponse>(
      `/api/config/providers/${encodeURIComponent(providerId)}/test`,
      {
      method: "POST",
        body: JSON.stringify({ model_id: modelId || "", model_type: modelType }),
      }
    ),

  testConfig: (params: {
    llm_base_url?: string;
    llm_api_key?: string;
    llm_model?: string;
    api_format?: ModelApiFormat;
    embed_base_url?: string;
    embed_api_key?: string;
    embed_model?: string;
  }) =>
    request<TestResultResponse>("/api/config/test", {
      method: "POST",
      body: JSON.stringify({
        llm_base_url: params.llm_base_url || "",
        llm_api_key: params.llm_api_key || "",
        llm_model: params.llm_model || "",
        api_format: params.api_format || "chat_completions",
        embed_base_url: params.embed_base_url || "",
        embed_api_key: params.embed_api_key || "",
        embed_model: params.embed_model || "",
      }),
    }),

  activateProvider: (
    providerId: string,
    modelId?: string,
    modelType: "chat" | "embedding" = "chat"
  ) =>
    request<{
      active_provider_id: string;
      active_chat_model: string;
      active_embed_provider_id: string;
      active_embed_model: string;
    }>("/api/config/providers/activate", {
      method: "POST",
      body: JSON.stringify({
        provider_id: providerId,
        model_id: modelId || "",
        model_type: modelType,
      }),
    }),

  fetchModels: (
    base_url: string,
    api_key?: string,
    api_format: ModelApiFormat = "chat_completions",
    provider_id?: string
  ) =>
    request<{ models: string[]; message?: string }>("/api/config/models", {
      method: "POST",
      body: JSON.stringify({
        base_url,
        api_key: api_key || "",
        api_format,
        // The UI only has the masked key; the server falls back to the stored
        // credential for this provider when api_key is empty.
        provider_id: provider_id || "",
      }),
    }),
};
