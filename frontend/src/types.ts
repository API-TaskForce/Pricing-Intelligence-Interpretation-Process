export type ChatRole = "user" | "assistant";

/**
 * Context mode — controls which tool set Harvey uses for a given request.
 * "saas" → only SaaS pricing tools (subscriptions, optimal, summary, iPricing, validate)
 * "api"  → only API analysis tools (min_time, capacity_at, …, evaluate_api_datasheet)
 * "all"  → full tool set (default / backward-compatible behaviour)
 */
export type ContextMode = "saas" | "api" | "all";

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

export type Kinds = "url" | "yaml";
export type Origins = "user" | "detected" | "preset" | "agent";

export type PricingContextItem = YamlContextItem | UrlContextItem;

export type YamlContextItem = YamlContextItemInput & {
  id: string;
};

export interface UrlContextItem extends UrlContextItemInput {
  id: string;
}

export type ContextInputType = YamlContextItemInput | UrlContextItemInput;
export type YamlContextItemInput =
  | BaseYamlContextItemInput
  | SphereContextItemInput;

export interface BaseYamlContextItemInput {
  kind: "yaml";
  label: string;
  value: string;
  origin?: Origins;
}

export interface UrlContextItemInput {
  kind: "url";
  label: string;
  url: string;
  value: string;
  origin?: Origins;
  transform: "not-started" | "pending" | "done";
}

export interface SphereContextItemInput {
  sphereId: string;
  kind: "yaml";
  label: string;
  value: string;
  origin: "sphere";
  owner: string;
  collection: string | null;
  pricingName: string;
  version: string;
  yamlPath: string;
}

export interface PromptPreset {
  id: string;
  label: string;
  description: string;
  question: string;
  context: YamlContextItemInput[];
}

export interface NotificationUrlEvent {
  id: string;
  pricing_url: string;
  yaml_content: string;
}

export type ChatRequest = {
  question: string;
  mode?: ContextMode;
} & PricingContextPayload;

export interface PricingContextUrlWithId {
  id: string;
  url: string;
}

export interface PricingContextPayload {
  pricing_url?: PricingContextUrlWithId;
  pricing_urls?: PricingContextUrlWithId[];
  pricing_yaml?: string;
  pricing_yamls?: string[];
  datasheet_yaml?: string;
  datasheet_yamls?: string[];
}
