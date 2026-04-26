export type ChatRole = "user" | "assistant";

export interface ChatHistoryMessage {
  role: ChatRole;
  content: string;
}

export type HarveyMode =
  | "sendgrid-2025"
  | "sendgrid-2026"
  | "mailersend"
  | "peertube"
  | "dailymotion";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  chartHtml?: string;
  metadata?: {
    plan?: Record<string, unknown>;
    result?: Record<string, unknown>;
  };
}

export type Kinds = "yaml" | "yaml-url";
export type Origins = "user" | "preset";

export type DatasheetContextItem = {
  id: string;
  kind: Kinds;
  label: string;
  value: string;
  origin?: Origins;
};

export type ContextInputType = {
  kind: Kinds;
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
  demoResponse?: string;
}

export type ChatRequest = {
  question: string;
  datasheet_yaml?: string;
  datasheet_yamls?: string[];
  datasheet_url?: string;
  datasheet_urls?: string[];
  history?: ChatHistoryMessage[];
  api_key?: string;
  query_mode?: "guided" | "autonomous";
};

export interface ClarificationRequest {
  fields: string[];
  availablePlans?: string[];
  availableEndpoints?: string[];
  availableCapacityUnits?: string[];
  availableAliases?: string[];
  crfRanges?: { min?: number; max?: number };
}
