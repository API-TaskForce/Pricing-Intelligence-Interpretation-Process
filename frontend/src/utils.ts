import { ChatRequest } from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8086";

export function extractHttpReferences(payload: unknown): string[] {
  const results = new Set<string>();
  const visited = new Set<unknown>();

  const visit = (value: unknown) => {
    if (value === null || value === undefined) return;
    if (typeof value === "string") {
      if (/^https?:\/\//i.test(value)) results.add(value);
      return;
    }
    if (typeof value !== "object") return;
    if (visited.has(value)) return;
    visited.add(value);
    if (Array.isArray(value)) { value.forEach(visit); return; }
    Object.values(value).forEach(visit);
  };

  visit(payload);
  return Array.from(results);
}

export async function uploadYamlPricing(
  filename: string,
  content: string
): Promise<string> {
  const form = new FormData();
  form.append(
    "file",
    new File([content], filename, { type: "application/yaml" })
  );
  const response = await fetch(API_BASE_URL + "/upload", {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(`Upload failed for ${filename}`);
  const json = await response.json();
  return json.filename;
}

export async function deleteYamlPricing(filename: string): Promise<void> {
  const response = await fetch(API_BASE_URL + "/datasheet/" + filename, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`Cannot delete item ${filename}`);
}

export function buildChatRequest(
  question: string,
  yamls: string[],
  history: Array<{ role: string; content: string }> = [],
  forceChart = false
): ChatRequest {
  const request: ChatRequest = { question };
  if (yamls.length === 1) {
    request.datasheet_yaml = yamls[0];
  } else if (yamls.length > 1) {
    request.datasheet_yamls = yamls;
  }
  if (history.length > 0) {
    request.history = history;
  }
  if (forceChart) {
    request.force_chart = true;
  }
  return request;
}

export async function chatWithAgent(body: ChatRequest) {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let message = `API returned ${response.status}`;
    try {
      const detail = await response.json();
      if (typeof detail?.detail === "string") message = detail.detail;
    } catch (parseError) {
      console.error("Failed to parse error response", parseError);
    }
    throw new Error(message);
  }

  return await response.json();
}
