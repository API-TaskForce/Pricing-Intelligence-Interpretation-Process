import type { ChatRequest, DatasheetContextItem } from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8086";

export async function uploadDatasheet(
  filename: string,
  content: string,
  credentials: string
): Promise<string> {
  const form = new FormData();
  form.append(
    "file",
    new File([content], filename, { type: "application/yaml" })
  );
  const response = await fetch(API_BASE_URL + "/upload", {
    method: "POST",
    headers: { Authorization: `Basic ${credentials}` },
    body: form,
  });
  if (!response.ok) {
    throw new Error(`Upload failed for ${filename}`);
  }
  const json = await response.json();
  return json.filename;
}

export async function deleteDatasheet(
  filename: string,
  credentials: string
): Promise<void> {
  const response = await fetch(API_BASE_URL + "/pricing/" + filename, {
    method: "DELETE",
    headers: { Authorization: `Basic ${credentials}` },
  });
  if (!response.ok) {
    throw new Error(`Cannot delete item ${filename}`);
  }
}

export function buildChatPayload(
  items: Pick<DatasheetContextItem, "kind" | "value">[]
): Pick<ChatRequest, "datasheet_yaml" | "datasheet_yamls" | "datasheet_url" | "datasheet_urls"> {
  const yamls = Array.from(new Set(
    items.filter((i) => i.kind === "yaml").map((i) => i.value)
  ));
  const urls = Array.from(new Set(
    items.filter((i) => i.kind === "yaml-url").map((i) => i.value)
  ));

  const payload: ReturnType<typeof buildChatPayload> = {};

  if (yamls.length === 1) payload.datasheet_yaml = yamls[0];
  else if (yamls.length > 1) payload.datasheet_yamls = yamls;

  if (urls.length === 1) payload.datasheet_url = urls[0];
  else if (urls.length > 1) payload.datasheet_urls = urls;

  return payload;
}

export async function chatWithAgent(
  body: ChatRequest,
  credentials: string
) {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Basic ${credentials}`,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let message = `API returned ${response.status}`;
    try {
      const detail = await response.json();
      if (typeof detail?.detail === "string") {
        message = detail.detail;
      }
    } catch (parseError) {
      console.error("Failed to parse error response", parseError);
    }
    throw new Error(message);
  }

  return await response.json();
}
