import type {
  AskResponse,
  Citation,
  CustomModel,
  CustomProvider,
  IngestResponse,
  MailItem,
  ModelApiFormat,
  ProvidersConfigResponse,
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
  ask: (question: string) =>
    request<AskResponse>("/api/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  getWikiPages: () => request<WikiListResponse>("/api/wiki/pages"),

  getWikiPage: (name: string) =>
    request<WikiPageDetail>(`/api/wiki/page/${encodeURIComponent(name)}`),

  archiveQA: (question: string, answer: string, citations: Citation[]) =>
    request<{ name: string; message: string }>("/api/wiki/archive-qa", {
      method: "POST",
      body: JSON.stringify({ question, answer, citations }),
    }),

  getMailTriage: () =>
    request<{ triages: MailItem[]; error?: string }>("/api/mail/triage"),

  archiveMail: (confirmed_ids: string[]) =>
    request<{
      archived: string[];
      blocked: string[];
      message: string;
    }>("/api/mail/archive", {
      method: "POST",
      body: JSON.stringify({ confirmed_ids }),
    }),

  ingestText: (text: string, origin: string = "web_input.md") =>
    request<IngestResponse>("/api/ingest", {
      method: "POST",
      body: JSON.stringify({ text, origin }),
    }),

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

  saveProvider: (provider: {
    id?: string;
    name: string;
    base_url: string;
    api_format?: ModelApiFormat;
    api_key?: string;
    enabled?: boolean;
    scope?: "chat" | "embedding";
    active_chat_model?: string;
    active_embed_model?: string;
  }) =>
    request<{ status: string; provider: CustomProvider }>("/api/config/providers", {
      method: "POST",
      body: JSON.stringify(provider),
    }),

  deleteProvider: (id: string) =>
    request<{ status: string; providers: CustomProvider[] }>(
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
    request<{ status: string; model: CustomModel; provider: CustomProvider }>(
      `/api/config/providers/${encodeURIComponent(providerId)}/models`,
      {
        method: "POST",
        body: JSON.stringify(model),
      }
    ),

  deleteProviderModel: (providerId: string, modelId: string) =>
    request<{ status: string; provider: CustomProvider }>(
      `/api/config/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}`,
      { method: "DELETE" }
    ),

  testProvider: (providerId: string, modelId?: string, modelType: "chat" | "embedding" = "chat") =>
    request<{
      status: string;
      llm_ok: boolean;
      llm_latency_ms: number;
      llm_message: string;
      embed_ok?: boolean;
      embed_latency_ms?: number;
      embed_message?: string;
    }>(`/api/config/providers/${encodeURIComponent(providerId)}/test`, {
      method: "POST",
      body: JSON.stringify({ model_id: modelId || "", model_type: modelType }),
    }),

  testConfig: (params: {
    llm_base_url?: string;
    llm_api_key?: string;
    llm_model?: string;
    api_format?: ModelApiFormat;
    embed_base_url?: string;
    embed_api_key?: string;
    embed_model?: string;
  }) =>
    request<{
      status: string;
      llm_ok: boolean;
      llm_latency_ms: number;
      llm_message: string;
      embed_ok?: boolean;
      embed_latency_ms?: number;
      embed_message?: string;
    }>("/api/config/test", {
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
      status: string;
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
    api_format: ModelApiFormat = "chat_completions"
  ) =>
    request<{ status: string; models: string[] }>("/api/config/models", {
      method: "POST",
      body: JSON.stringify({
        base_url,
        api_key: api_key || "",
        api_format,
      }),
    }),
};
