export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  metadata?: {
    plan?: Record<string, unknown>;
    result?: Record<string, unknown>;
  };
}

export type Kinds = "yaml";
export type Origins = "user" | "preset";

export type DatasheetContextItem = {
  id: string;
  kind: "yaml";
  label: string;
  value: string;
  origin?: Origins;
};

export type ContextInputType = {
  kind: "yaml";
  label: string;
  value: string;
  origin?: Origins;
};

export interface PromptPreset {
  id: string;
  label: string;
  description: string;
  question: string;
  context: ContextInputType[];
}

export type ChatRequest = {
  question: string;
  datasheet_yaml?: string;
  datasheet_yamls?: string[];
  api_key?: string;
};
