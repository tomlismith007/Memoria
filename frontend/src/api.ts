import type {
  AskResponse,
  Citation,
  IngestResponse,
  MailItem,
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
  health: () => request<{ status: string; version: string }>("/api/health"),

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
};
