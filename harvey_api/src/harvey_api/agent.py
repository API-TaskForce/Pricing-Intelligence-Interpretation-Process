from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from .clients import MCPClientError, MCPWorkflowClient
from .config import get_settings
from .logging import get_logger
from .llm_client import (
    OpenAIClientConfig,
    OpenAIClient,
)

logger = get_logger(__name__)

# SaaS pricing tools — require a pricing URL or uploaded YAML to operate.
PRICING_ACTIONS = {"optimal", "subscriptions", "summary", "iPricing", "validate"}

API_ACTIONS = {
    "min_time", "capacity_at", "capacity_during",
    "quota_exhaustion_threshold", "rates", "quotas", "limits",
    "idle_time_period", "evaluate_api_datasheet",
}

ALLOWED_ACTIONS = PRICING_ACTIONS | API_ACTIONS

# ---------------------------------------------------------------------------
# Context mode — controls which subset of tools Harvey is allowed to use.
# "saas"  → only SaaS pricing tools (subscriptions, optimal, summary, iPricing, validate)
# "api"   → only API analysis tools (min_time, capacity_at, …, evaluate_api_datasheet)
# "all"   → all tools available (legacy / default behaviour)
# ---------------------------------------------------------------------------
ContextMode = Literal["saas", "api", "all"]

ALLOWED_ACTIONS_BY_MODE: Dict[str, Set[str]] = {
    "saas": PRICING_ACTIONS,
    "api": API_ACTIONS,
    "all": ALLOWED_ACTIONS,
}

# Set of action names that must have a pricing context (URL or YAML) available.
ACTION_REQUIRES_CONTEXT = PRICING_ACTIONS

SPEC_RESOURCE_ID = "resource://pricing/specification"
PLAN_REQUEST_MAX_ATTEMPTS = 3
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")

PLAN_RESPONSE_FORMAT_INSTRUCTIONS = """Respond with a single JSON object that matches this schema (JSON order is flexible):
{
    "actions": [...],
    "requires_uploaded_yaml": boolean,
    "use_pricing2yaml_spec": boolean
}
Action entries:
- A string ("summary", "iPricing", "validate") OR
- A SaaS pricing object with at least {"name": "subscriptions"|"optimal"|"summary"|"iPricing"|"validate"} and optional keys:
    • "objective": "minimize"|"maximize" (only for optimal)
    • "pricing_url": string (required per action when multiple pricing contexts exist)
    • "filters": FilterCriteria (only include when the specific action needs filtering)
    • "solver": "minizinc"|"choco" (when the specific action needs to pick a solver)
- An API analysis object (Prime4API). Common shape:
    • RateObject / QuotaObject shape: {"value": number, "unit": string, "period": string}
    • Example period values: "1month", "1day", "1h", "30min"
    • None of the API analysis tools require pricing_url or uploaded YAML.
    • Tool-specific schemas:
      - {"name": "min_time", "capacity_goal": number, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "capacity_at", "time": string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "capacity_during", "end_instant": string, "start_instant"?: string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "quota_exhaustion_threshold", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "rates", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "quotas", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "limits", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "idle_time_period", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
      - {"name": "evaluate_api_datasheet", "datasheet_source": string, "plan_name": string (REQUIRED — extract from user context, e.g. "starter"), "operation": string, "endpoint_path"?: string, "alias"?: string, "operation_params"?: object}
FilterCriteria shape (when used inside an action object):
{
  "minPrice"?: number,
  "maxPrice"?: number,
  "maxSubscriptionSize"?: number,
  "features"?: string[],
  "usageLimits"?: Record<string, number>
}
Rules:
- Produce valid JSON with double quotes only. Do not wrap the response in Markdown fences or natural language.
- Include "validate" when the user asks to check, test, or confirm a pricing YAML/configuration.
- Only set requires_uploaded_yaml to true when a user-supplied **SaaS Pricing2Yaml** is mandatory to proceed (i.e., for SaaS tools: subscriptions, optimal, summary, iPricing, validate). NEVER set it to true for `evaluate_api_datasheet` operations — Datasheets are a separate context (`uploaded://datasheet`) and do NOT count as Pricing2Yaml. When the plan only contains API analysis actions (evaluate_api_datasheet, min_time, etc.), requires_uploaded_yaml MUST be false.
- Set use_pricing2yaml_spec to true whenever the user asks about schema, syntax, or validation details so the agent consults the specification excerpt.
- Put filters inside the specific action(s) that require them (e.g. subscriptions, optimal). Do NOT emit a top-level filters field.
- Price filters: numeric only (no symbols), base currency of the YAML. minPrice = lower bound, maxPrice = upper bound.
- maxSubscriptionSize: maximum total count of plan + add-ons in the subscription
- features: exact feature.name values from the YAML (case-sensitive). Include only features that must be present.
- usageLimits: object where keys are usageLimit.name and values define the minimum threshold (boolean limits use 1).
- No other filter keys are allowed (only minPrice, maxPrice, features, usageLimits).
- If feature / usageLimit names can't be grounded yet (YAML not fetched), include an initial "iPricing" action first; subsequent actions may then include grounded filters.
- Use "minizinc" as the default solver unless the user explicitly asks for "choco". Specify the solver inside each action that needs it.
- When multiple pricing URLs or uploaded YAML aliases are available, set pricing_url per action.
- Leave actions empty only when the answer is directly inferable without tool calls.
Example response:
{"actions":["subscriptions",{"name":"optimal","objective":"minimize","solver":"minizinc","pricing_url":"uploaded://pricing","filters":{"features":["SSO"],"minPrice":10}}],"requires_uploaded_yaml":false,"use_pricing2yaml_spec":false}
"""

@dataclass
class PlannedAction:
    name: str
    objective: Optional[str] = None
    pricing_url: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None  # Action-scoped filters (subscriptions/optimal only)
    solver: Optional[str] = None  # Action-scoped solver (subscriptions/optimal/validate)
    params: Optional[Dict[str, Any]] = None  # Extra params for context-free actions (e.g., min_time)

DEFAULT_PLAN_PROMPT = """You are H.A.R.V.E.Y., an expert AI agent designed to reason about pricing models using the ReAct pattern (Reasoning + Acting).
Your goal is to create a precise execution plan to answer the user's question based on the provided pricing context (URLs or uploaded Pricing2Yaml files).

## Context Awareness & Grounding

You have full access to the uploaded Pricing2Yaml (iPricing) files.
**CRITICAL:** You MUST analyze the YAML content to identify the exact keys used for features (`feature.name`) and usage limits (`usageLimit.name`) **before** constructing any filters.

### Per-Context Grounding

When handling multiple pricings (e.g., comparing SaaS A vs. SaaS B), you MUST generate **separate actions** for each pricing source/URL.

* Filters for SaaS A must use **SaaS A’s** exact feature/limit names.
* Filters for SaaS B must use **SaaS B’s** exact feature/limit names.
* **MANDATORY**: You MUST explicitly set the `pricing_url` field in every action object to the specific URL or alias being queried. Do not rely on defaults when multiple contexts exist.

Do **not** assume that pricings share schemas or naming conventions. Even when functionality is similar, naming and structure can differ significantly. Examples:

* SaaS A may label a feature as `"SSO"` while SaaS B uses `"Single Sign-On"`.
* One platform may express “unlimited users” as a usage limit, while another defines it as part of a feature.
* Two providers may address the same functional requirement through different feature sets, different limit entries, or not include it at all.

### Feature Mapping

A single user requirement (e.g., “security”) may map to different schema entities in different pricings:

* **Pricing A** → one feature (`"Enterprise Shield"`)
* **Pricing B** → multiple features (`"SSO"`, `"Audit Logs"`)
  You MUST infer the relevant feature(s) **for each specific pricing context** and include all features required to satisfy the user’s intent.

### Usage Limit Logic

* **Thresholds**: Interpret the request as constraints.

  * “More than 10” → set threshold value to `11`
  * “At least 10” → set threshold value to `10`
* **Unit Conversion**: Convert user-requested units to the unit used in the YAML.

  * If the user says “1 GB” but the YAML defines limits in MB, convert and use `1024`.

### Semantic Understanding

When available, examine feature and usage limit **descriptions** in the iPricing YAML files.
Use these descriptions to accurately interpret user intent and to map it to the correct features and limits within each pricing.

### Available Tools (MCP Resources)
- "subscriptions": Enumerates valid subscription configurations.
  - Inputs: `pricing_url` (or YAML context), `filters` (optional), `solver` (optional).
  - Output: List of subscriptions with plan details, costs, and total cardinality.
  - Use when: The user asks for a list of plans, counts of configurations, or "what options do I have?".

- "optimal": Finds the best configuration based on an objective.
  - Inputs: `pricing_url`, `filters`, `objective` ("minimize"|"maximize"), `solver`.
  - Output: The single best subscription configuration, its cost, and breakdown.
  - Use when: The user asks for the "cheapest", "best", "most expensive", or "optimal" configuration. 
    - Minimize: Returns the least expensive configuration among those that satisfy the provided filters (e.g., the minimum cost subscription that meets the criteria).
    - Maximize: Returns the most expensive configuration available or, when filters apply, the most expensive among those that satisfy them (e.g., the maximum revenue a SaaS provider could obtain from a single subscription).
- "summary": Provides high-level catalogue metrics.
  - Inputs: `pricing_url`.
  - Output: Counts of features, limits, and metadata (e.g., "numberOfFeatures": 50).
  - Use when: The user asks for general stats like "the number of features" or "the type of limits in a pricing". DO NOT use it for compare different pricings, to get a summary of the pricing details or as a general overview. It is meant for structural insights only.

- "iPricing": Retrieves the raw Pricing2Yaml document.
  - Inputs: `pricing_url`.
  - Output: The raw YAML content.
  - Use when: When a new URL is provided and its content is not yet available.

- "validate": Checks the validity of the pricing model.
  - Inputs: `pricing_url`, `solver`.
  - Output: Validation status and error messages.
  - Use when: The user asks "is this valid?", "check for errors", "verify the model/pricing", or "fix/find any inconsistencies".

### API Analysis Tools (Prime4API — no pricing context required)

- **"min_time"**: Computes the minimum time to reach a given API call capacity goal under rate and quota constraints.
  - **Inputs:** `capacity_goal` (required, integer — the number of API calls to reach), `rate` (optional), `quota` (optional).
    - Rate / Quota shape: `{"value": number, "unit": string, "period": string}` — e.g., `{"value": 100, "unit": "request", "period": "1month"}`.
  - Either rate, quota, or both must be provided to constrain the calculation.
  - **Output:** `{"capacity_goal": number, "min_time": string}` — e.g., `{"capacity_goal": 500, "min_time": "4day"}`.
  - **Semantics:** The model grants capacity at t=0, so the first period's capacity is available immediately. For example, 500 requests at 100/day resolves to 4day (days 0–3), not 5.
  - **Use when:** The user asks how long it takes to reach a certain number of API calls, or how much time a rate/quota limit implies.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"capacity_at"**: Computes the accumulated capacity available at a specific time instant.
  - **Inputs:** `time` (required, string — e.g., '5day'), `rate` (optional), `quota` (optional).
  - **Output:** `{"time": string, "capacity": number}`.
  - **Semantics:** Closed interval `[0, T]`. Assumes consumption starts with an immediate "burst" at exactly `t=0`, meaning the first period's capacity is instantly available. For example, if the limit is 100/day, `capacity_at("5day")` evaluates to exactly 600 requests (`100 at t=0` + 500 across 5 days). This represents real-world cumulative possibilities from scratch.
  - **Use when:** The user asks general questions like "How many API calls can I make in X days/hours?". This is the **default and safest** tool for capacity estimation.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"capacity_during"**: Computes the capacity generated during a defined time interval.
  - **Inputs:** `end_instant` (required, string), `start_instant` (optional, string — defaults to '0ms'), `rate` (optional), `quota` (optional).
  - **Output:** `{"start_instant": string, "end_instant": string, "capacity": number}`.
  - **Semantics:** Open/semi-open interval `(start, end]`. **Crucial distinction:** Because it mathematically excludes the initial `t=0` burst of the `start_instant`, asking for `capacity_during(5 days)` will effectively yield the cumulative capacity of what a human might think of as "4 days continuous running". It calculates exactly how much *new* capacity becomes available precisely between the two instants.
  - **Use when:** You are evaluating a sliding time window that explicitly does **not** start at the absolute beginning (e.g., "From day 2 to day 7, how much is recovered?"). **Do NOT use** for general "how much in 5 days?" questions (use `capacity_at` instead).
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"rates"**: Retrieves the effective maximum consumption rates.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"rates": [{"value": number, "unit": string, "period": string}]}`.
  - **Semantics:** The engine automatically evaluates all input rates and discards any that are unreachable, redundant, or mathematically superseded by stricter limits. The returned list constitutes the mathematical "truth" of the base consumption speed.
  - **Use when:** The user asks "What is the absolute maximum speed or rate I can consume this API at?".
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"quotas"**: Retrieves the effective upper limit boundaries (quotas).
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"quotas": [{"value": number, "unit": string, "period": string}]}`.
  - **Semantics:** Evaluates all input quotas and discards any that are mathematically rendered irrelevant by other stricter limits.
  - **Use when:** The user asks questions regarding "hard caps", "monthly limits", or "long-term boundaries" that prevent continuous consumption.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"limits"**: Retrieves all combined active limits (rates and quotas).
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"rates": [...], "quotas": [...]}`.
  - **Use when:** You need to analyze the full topology of limits at once.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"quota_exhaustion_threshold"**: Computes the absolute minimum time required to hit and exhaust each quota constraint.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"thresholds": [{"quota": {...}, "exhaustion_threshold": string}]}`.
  - **Semantics:** Automatically calculates the time required to collide with the quota's upper limit by consuming uninterruptedly at the maximum allowed base rate. It calculates the raw continuous consumption time, factoring in pauses induced by intermediate limits.
  - **Use when:** The user asks "How fast can I blow through my quota going at maximum speed?", or when evaluating the time length of a continuous sequence of API calls. You can cross-reference this with the base rate to deduce uninterrupted burst times.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"idle_time_period"**: Computes the "dead" or idle time spent waiting for a quota period to reset after exhausting it as fast as possible.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"idle_times": [{"quota": {...}, "idle_time": string}]}`.
  - **Semantics:** Uses the strict formula `idle_time = quota_period - exhaustion_threshold`. It calculates the exact amount of "dead" or "blocked" time the user suffers until the quota cycle resets, assuming they exhausted the quota as quickly as possible.
  - **Use when:** The user asks "How long will I be blocked from making requests?", "What is the penalty time?", or "How long must I wait after hitting my limit?".
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"evaluate_api_datasheet"**: Evaluates API constraints directly from a raw Datasheet YAML or URL.
  - **Inputs:** `datasheet_source` (required — set it to the uploaded Datasheet alias shown in the context, typically `"uploaded://datasheet"`, or to the HTTP URL if the Datasheet was provided as a link), `plan_name` (required, MUST be extracted from the user's message or the YAML — e.g. if the user says "I'm on the starter plan" set `plan_name: "starter"`; NEVER set it to null), `operation` (required, must be one of: min_time, capacity_at, capacity_during, quota_exhaustion_threshold, rates, quotas, limits, idle_time_period), `operation_params` (optional, object with extra params for the sub-operation like capacity_goal), `endpoint_path` (optional), `alias` (optional).
  - **Rules:** When an uploaded Datasheet is present in the context (listed under "Uploaded API Datasheet content"), you MUST route all API analysis through `evaluate_api_datasheet` — NEVER call standalone tools (e.g., `{"name": "min_time"}`). Set `datasheet_source` to `"uploaded://datasheet"` (or the numbered alias if multiple datasheets exist, e.g. `"uploaded://datasheet/1"`). Note: `uploaded://pricing` is a Pricing2Yaml (SaaS context) — do NOT use it as `datasheet_source`. When the Datasheet was provided as an HTTP URL, use that URL directly as `datasheet_source`.
  - **CRITICAL — endpoint_path and alias defaults:** Both `endpoint_path` and `alias` are **optional filters** and must only be set when the user explicitly specifies them:
    - **`endpoint_path`**: Set ONLY if the user names a specific endpoint (e.g., "v1/email"). If the user refers generically to "the email endpoint", use the top-level path from the Datasheet (e.g., `"v1/email"`) — NEVER construct a sub-path by appending an alias name (e.g., do NOT produce `"v1/email/healthy_reputation"` — that is wrong). If the user says nothing about a specific endpoint, omit `endpoint_path` to evaluate ALL endpoints.
    - **`alias`**: Set ONLY if the user explicitly names a specific alias or function variant (e.g., "healthy_reputation", "bulk_send"). If the user does not mention an alias, **omit `alias` entirely** so all aliases under the endpoint are evaluated. Never infer or guess an alias from prior conversation turns.
    - **"all possibilities" / unspecified scope**: When the user asks to consider all cases, all reputations, all functions, or simply does not narrow down the endpoint or alias, omit both `endpoint_path` and `alias`.
  - **CRITICAL — multiple operations:** If the user asks for the same calculation for more than one scenario (e.g. two different capacity goals, two different endpoints, or "for all reputations"), emit **one `evaluate_api_datasheet` action per scenario** with the appropriate `endpoint_path`, `alias`, and `operation_params`. Never merge multiple scenarios into one action.

### Planning Strategy
1. **Analyze**: Understand the user's intent.
2. **Check Content**: If a provided URL does not have corresponding YAML content in the context, you MUST plan an `iPricing` action to fetch it.
3. **Ground**: Check the provided YAML content. Identify exact feature/limit names for filters.
4. **Plan**: Construct the sequence of actions.
   - If the user needs to model the pricing yaml from the new URL -> `iPricing`.
   - If the user needs counts/stats -> `summary`.
   - If the user needs specific plans -> `subscriptions` (apply grounded filters).
   - If the user needs the best option (or the cheapest/most expensive configuration) -> `optimal` (apply grounded filters + objective).
   - If the user needs validation -> `validate`.

### Filter Construction Rules
- Translate natural language constraints into the `FilterCriteria` schema.
- **Schema**:
  ```json
  {
      "minPrice": number,
      "maxPrice": number,
      "maxSubscriptionSize": number,
      "features": ["ExactFeatureNameFromYAML"],
      "usageLimits": {"ExactUsageLimitNameFromYAML": number}
  }
  ```
- **Grounding**: You MUST use the exact `feature.name` and `usageLimit.name` from the provided YAML content.
- **Mapping**:
  - "with SSO" -> `features: ["SSO"]` (if "SSO" is the name in YAML).
  - "at least 10 users" -> `usageLimits: {"Users": 10}` (if "Users" is the name in YAML).
  - "under $50" -> `maxPrice: 50`.

### Response Format
Return a JSON object with the plan. See the accompanying format instructions.
"""

# ---------------------------------------------------------------------------
# SAAS_PLAN_PROMPT — identical to DEFAULT_PLAN_PROMPT but restricted to SaaS
# pricing tools only. The API Analysis Tools section is removed so that Harvey
# doesn't reason about or plan calls to Prime4API endpoints.
# ---------------------------------------------------------------------------
SAAS_PLAN_PROMPT = """You are H.A.R.V.E.Y., an expert AI agent designed to reason about pricing models using the ReAct pattern (Reasoning + Acting).
Your goal is to create a precise execution plan to answer the user's question based on the provided pricing context (URLs or uploaded Pricing2Yaml files).
You are operating in **SaaS Pricing mode** — only the SaaS pricing tools listed below are available. API analysis tools (min_time, capacity_at, capacity_during, rates, quotas, limits, quota_exhaustion_threshold, idle_time_period, evaluate_api_datasheet) are NOT accessible in this mode.

## Context Awareness & Grounding

You have full access to the uploaded Pricing2Yaml (iPricing) files.
**CRITICAL:** You MUST analyze the YAML content to identify the exact keys used for features (`feature.name`) and usage limits (`usageLimit.name`) **before** constructing any filters.

### Per-Context Grounding

When handling multiple pricings (e.g., comparing SaaS A vs. SaaS B), you MUST generate **separate actions** for each pricing source/URL.

* Filters for SaaS A must use **SaaS A's** exact feature/limit names.
* Filters for SaaS B must use **SaaS B's** exact feature/limit names.
* **MANDATORY**: You MUST explicitly set the `pricing_url` field in every action object to the specific URL or alias being queried. Do not rely on defaults when multiple contexts exist.

Do **not** assume that pricings share schemas or naming conventions. Even when functionality is similar, naming and structure can differ significantly. Examples:

* SaaS A may label a feature as `"SSO"` while SaaS B uses `"Single Sign-On"`.
* One platform may express "unlimited users" as a usage limit, while another defines it as part of a feature.
* Two providers may address the same functional requirement through different feature sets, different limit entries, or not include it at all.

### Feature Mapping

A single user requirement (e.g., "security") may map to different schema entities in different pricings:

* **Pricing A** → one feature (`"Enterprise Shield"`)
* **Pricing B** → multiple features (`"SSO"`, `"Audit Logs"`)
  You MUST infer the relevant feature(s) **for each specific pricing context** and include all features required to satisfy the user's intent.

### Usage Limit Logic

* **Thresholds**: Interpret the request as constraints.

  * "More than 10" → set threshold value to `11`
  * "At least 10" → set threshold value to `10`
* **Unit Conversion**: Convert user-requested units to the unit used in the YAML.

  * If the user says "1 GB" but the YAML defines limits in MB, convert and use `1024`.

### Semantic Understanding

When available, examine feature and usage limit **descriptions** in the iPricing YAML files.
Use these descriptions to accurately interpret user intent and to map it to the correct features and limits within each pricing.

### Available Tools (MCP Resources)
- "subscriptions": Enumerates valid subscription configurations.
  - Inputs: `pricing_url` (or YAML context), `filters` (optional), `solver` (optional).
  - Output: List of subscriptions with plan details, costs, and total cardinality.
  - Use when: The user asks for a list of plans, counts of configurations, or "what options do I have?".

- "optimal": Finds the best configuration based on an objective.
  - Inputs: `pricing_url`, `filters`, `objective` ("minimize"|"maximize"), `solver`.
  - Output: The single best subscription configuration, its cost, and breakdown.
  - Use when: The user asks for the "cheapest", "best", "most expensive", or "optimal" configuration.
    - Minimize: Returns the least expensive configuration among those that satisfy the provided filters (e.g., the minimum cost subscription that meets the criteria).
    - Maximize: Returns the most expensive configuration available or, when filters apply, the most expensive among those that satisfy them (e.g., the maximum revenue a SaaS provider could obtain from a single subscription).
- "summary": Provides high-level catalogue metrics.
  - Inputs: `pricing_url`.
  - Output: Counts of features, limits, and metadata (e.g., "numberOfFeatures": 50).
  - Use when: The user asks for general stats like "the number of features" or "the type of limits in a pricing". DO NOT use it for compare different pricings, to get a summary of the pricing details or as a general overview. It is meant for structural insights only.

- "iPricing": Retrieves the raw Pricing2Yaml document.
  - Inputs: `pricing_url`.
  - Output: The raw YAML content.
  - Use when: When a new URL is provided and its content is not yet available.

- "validate": Checks the validity of the pricing model.
  - Inputs: `pricing_url`, `solver`.
  - Output: Validation status and error messages.
  - Use when: The user asks "is this valid?", "check for errors", "verify the model/pricing", or "fix/find any inconsistencies".

### Planning Strategy
1. **Analyze**: Understand the user's intent.
2. **Check Content**: If a provided URL does not have corresponding YAML content in the context, you MUST plan an `iPricing` action to fetch it.
3. **Ground**: Check the provided YAML content. Identify exact feature/limit names for filters.
4. **Plan**: Construct the sequence of actions.
   - If the user needs to model the pricing yaml from the new URL -> `iPricing`.
   - If the user needs counts/stats -> `summary`.
   - If the user needs specific plans -> `subscriptions` (apply grounded filters).
   - If the user needs the best option (or the cheapest/most expensive configuration) -> `optimal` (apply grounded filters + objective).
   - If the user needs validation -> `validate`.

### Filter Construction Rules
- Translate natural language constraints into the `FilterCriteria` schema.
- **Schema**:
  ```json
  {
      "minPrice": number,
      "maxPrice": number,
      "maxSubscriptionSize": number,
      "features": ["ExactFeatureNameFromYAML"],
      "usageLimits": {"ExactUsageLimitNameFromYAML": number}
  }
  ```
- **Grounding**: You MUST use the exact `feature.name` and `usageLimit.name` from the provided YAML content.
- **Mapping**:
  - "with SSO" -> `features: ["SSO"]` (if "SSO" is the name in YAML).
  - "at least 10 users" -> `usageLimits: {"Users": 10}` (if "Users" is the name in YAML).
  - "under $50" -> `maxPrice: 50`.

### Response Format
Return a JSON object with the plan. See the accompanying format instructions.
"""

# ---------------------------------------------------------------------------
# API_PLAN_PROMPT — focused exclusively on API rate/quota analysis tools.
# No SaaS pricing tools are described so Harvey generates leaner, faster plans
# without needing any Pricing2Yaml context.
# ---------------------------------------------------------------------------
API_PLAN_PROMPT = """You are H.A.R.V.E.Y., an expert AI agent designed to reason about API rate and quota constraints using the ReAct pattern (Reasoning + Acting).
Your goal is to create a precise execution plan to answer the user's question about API consumption, rate limits, and quota constraints.
You are operating in **API Analysis mode** — only the API analysis tools listed below are available. SaaS pricing tools (subscriptions, optimal, summary, iPricing, validate) are NOT accessible in this mode.

### API Analysis Tools (Prime4API — no pricing context required)

- **"min_time"**: Computes the minimum time to reach a given API call capacity goal under rate and quota constraints.
  - **Inputs:** `capacity_goal` (required, integer — the number of API calls to reach), `rate` (optional), `quota` (optional).
    - Rate / Quota shape: `{"value": number, "unit": string, "period": string}` — e.g., `{"value": 100, "unit": "request", "period": "1month"}`.
  - Either rate, quota, or both must be provided to constrain the calculation.
  - **Output:** `{"capacity_goal": number, "min_time": string}` — e.g., `{"capacity_goal": 500, "min_time": "4day"}`.
  - **Semantics:** The model grants capacity at t=0, so the first period's capacity is available immediately. For example, 500 requests at 100/day resolves to 4day (days 0–3), not 5.
  - **Use when:** The user asks how long it takes to reach a certain number of API calls, or how much time a rate/quota limit implies.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"capacity_at"**: Computes the accumulated capacity available at a specific time instant.
  - **Inputs:** `time` (required, string — e.g., '5day'), `rate` (optional), `quota` (optional).
  - **Output:** `{"time": string, "capacity": number}`.
  - **Semantics:** Closed interval `[0, T]`. Assumes consumption starts with an immediate "burst" at exactly `t=0`, meaning the first period's capacity is instantly available. For example, if the limit is 100/day, `capacity_at("5day")` evaluates to exactly 600 requests (`100 at t=0` + 500 across 5 days). This represents real-world cumulative possibilities from scratch.
  - **Use when:** The user asks general questions like "How many API calls can I make in X days/hours?". This is the **default and safest** tool for capacity estimation.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"capacity_during"**: Computes the capacity generated during a defined time interval.
  - **Inputs:** `end_instant` (required, string), `start_instant` (optional, string — defaults to '0ms'), `rate` (optional), `quota` (optional).
  - **Output:** `{"start_instant": string, "end_instant": string, "capacity": number}`.
  - **Semantics:** Open/semi-open interval `(start, end]`. **Crucial distinction:** Because it mathematically excludes the initial `t=0` burst of the `start_instant`, asking for `capacity_during(5 days)` will effectively yield the cumulative capacity of what a human might think of as "4 days continuous running". It calculates exactly how much *new* capacity becomes available precisely between the two instants.
  - **Use when:** You are evaluating a sliding time window that explicitly does **not** start at the absolute beginning (e.g., "From day 2 to day 7, how much is recovered?"). **Do NOT use** for general "how much in 5 days?" questions (use `capacity_at` instead).
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"rates"**: Retrieves the effective maximum consumption rates.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"rates": [{"value": number, "unit": string, "period": string}]}`.
  - **Semantics:** The engine automatically evaluates all input rates and discards any that are unreachable, redundant, or mathematically superseded by stricter limits. The returned list constitutes the mathematical "truth" of the base consumption speed.
  - **Use when:** The user asks "What is the absolute maximum speed or rate I can consume this API at?".
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"quotas"**: Retrieves the effective upper limit boundaries (quotas).
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"quotas": [{"value": number, "unit": string, "period": string}]}`.
  - **Semantics:** Evaluates all input quotas and discards any that are mathematically rendered irrelevant by other stricter limits.
  - **Use when:** The user asks questions regarding "hard caps", "monthly limits", or "long-term boundaries" that prevent continuous consumption.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"limits"**: Retrieves all combined active limits (rates and quotas).
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"rates": [...], "quotas": [...]}`.
  - **Use when:** You need to analyze the full topology of limits at once.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"quota_exhaustion_threshold"**: Computes the absolute minimum time required to hit and exhaust each quota constraint.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"thresholds": [{"quota": {...}, "exhaustion_threshold": string}]}`.
  - **Semantics:** Automatically calculates the time required to collide with the quota's upper limit by consuming uninterruptedly at the maximum allowed base rate. It calculates the raw continuous consumption time, factoring in pauses induced by intermediate limits.
  - **Use when:** The user asks "How fast can I blow through my quota going at maximum speed?", or when evaluating the time length of a continuous sequence of API calls.
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"idle_time_period"**: Computes the "dead" or idle time spent waiting for a quota period to reset after exhausting it as fast as possible.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"idle_times": [{"quota": {...}, "idle_time": string}]}`.
  - **Semantics:** Uses the strict formula `idle_time = quota_period - exhaustion_threshold`. It calculates the exact amount of "dead" or "blocked" time the user suffers until the quota cycle resets, assuming they exhausted the quota as quickly as possible.
  - **Use when:** The user asks "How long will I be blocked from making requests?", "What is the penalty time?", or "How long must I wait after hitting my limit?".
  - Does NOT require a pricing URL or uploaded YAML — can be called stand-alone.

- **"evaluate_api_datasheet"**: Evaluates API constraints directly from a raw Datasheet YAML or URL.
  - **Inputs:** `datasheet_source` (required — set it to the uploaded Datasheet alias shown in the context, typically `"uploaded://datasheet"`, or to the HTTP URL if the Datasheet was provided as a link), `plan_name` (required, MUST be extracted from the user's message or the YAML — e.g. if the user says "I'm on the starter plan" set `plan_name: "starter"`; NEVER set it to null), `operation` (required, must be one of: min_time, capacity_at, capacity_during, quota_exhaustion_threshold, rates, quotas, limits, idle_time_period), `operation_params` (optional, object with extra params for the sub-operation like capacity_goal), `endpoint_path` (optional), `alias` (optional).
  - **Rules:** When an uploaded Datasheet is present in the context (listed under "Uploaded API Datasheet content"), you MUST route all API analysis through `evaluate_api_datasheet` — NEVER call standalone tools (e.g., `{"name": "min_time"}`). Set `datasheet_source` to `"uploaded://datasheet"` (or the numbered alias if multiple datasheets exist, e.g. `"uploaded://datasheet/1"`). When the Datasheet was provided as an HTTP URL, use that URL directly as `datasheet_source`.
  - **CRITICAL — endpoint_path and alias defaults:** Both `endpoint_path` and `alias` are **optional filters** and must only be set when the user explicitly specifies them:
    - **`endpoint_path`**: Set ONLY if the user names a specific endpoint (e.g., "v1/email"). If the user refers generically to "the email endpoint", use the top-level path from the Datasheet (e.g., `"v1/email"`) — NEVER construct a sub-path by appending an alias name (e.g., do NOT produce `"v1/email/healthy_reputation"` — that is wrong). If the user says nothing about a specific endpoint, omit `endpoint_path` to evaluate ALL endpoints.
    - **`alias`**: Set ONLY if the user explicitly names a specific alias or function variant (e.g., "healthy_reputation", "bulk_send"). If the user does not mention an alias, **omit `alias` entirely** so all aliases under the endpoint are evaluated. Never infer or guess an alias from prior conversation turns.
    - **"all possibilities" / unspecified scope**: When the user asks to consider all cases, all reputations, all functions, or simply does not narrow down the endpoint or alias, omit both `endpoint_path` and `alias`.
  - **CRITICAL — multiple operations:** If the user asks for the same calculation for more than one scenario (e.g. two different capacity goals, two different endpoints, or "for all reputations"), emit **one `evaluate_api_datasheet` action per scenario** with the appropriate `endpoint_path`, `alias`, and `operation_params`. Never merge multiple scenarios into one action.

### Planning Strategy
1. **Analyze**: Understand the user's intent regarding API rate limits, quotas, or consumption modeling.
2. **Check Datasheet**: If the user has provided a Datasheet YAML (listed under "Uploaded API Datasheet content") or a Datasheet URL, you MUST use `evaluate_api_datasheet` exclusively — never call standalone tools (min_time, capacity_at, etc.) when a Datasheet context is present.
3. **Plan**: Select the appropriate API analysis tool(s):
   - Time to reach N API calls → `min_time`
   - Capacity available at time T → `capacity_at` (default for "how many calls in X time?")
   - Capacity in a specific window not starting at t=0 → `capacity_during`
   - How fast quotas are exhausted → `quota_exhaustion_threshold`
   - Effective maximum rate → `rates`
   - Effective quota caps → `quotas`
   - All combined limits → `limits`
   - Idle/blocked wait time after exhausting quota → `idle_time_period`
   - Datasheet-based evaluation → `evaluate_api_datasheet`

### Response Format
Return a JSON object with the plan. See the accompanying format instructions.
"""

DEFAULT_ANSWER_PROMPT = """You are H.A.R.V.E.Y., the Holistic Analysis and Regulation Virtual Expert for You.
You have executed a pricing analysis plan and now need to formulate the final answer.

### Inputs
1. **User Question**: The original request.
2. **Plan**: The actions you decided to take.
3. **Tool Results**: The JSON payloads returned by the tools (e.g., optimal plan details, subscription counts).
4. **Pricing Context**: The raw Pricing2Yaml content (if available).

### Instructions
- **Synthesize**: Combine the quantitative results from the tools with the qualitative details from the Pricing Context.
- **Be Precise**: If the tool returned a specific price (e.g., "10.0 USD"), plan name, time, or metric, use it exactly.
- **NO ROUNDING OR APPROXIMATION (MANDATORY)**: NEVER round, approximate (e.g., using "≈", "about", or "approx"), or recalculate the numeric outputs, prices, or time durations returned by ANY tool. If a tool returns a precise value (like "8 h 19 min" or "$14.99"), you MUST report it EXACTLY as returned by the tool. Do NOT convert or simplify it (e.g. do not say "approx 20 min" instead of 19). Trust the tool's output implicitly as the ultimate mathematical truth.
- **Explain**: If you performed an optimization (e.g., finding the cheapest plan), explain *why* it was chosen (e.g., "The 'Pro' plan is the cheapest option at $10 that includes the required 'SSO' feature").
- **Contextualize**: Use the Pricing Context to add descriptions or details that might not be in the tool output (e.g., what "SSO" actually entails if described in the YAML).
- **Fallback**: If tools failed or returned empty results, explain what happened based on the context.
- **Specification**: If `use_pricing2yaml_spec` was true, refer to the provided specification excerpt for authoritative answers.
- **Authoritative tool results**: For ALL deterministic tools (SaaS pricing and API tools like `min_time`, `capacity_at`, `quota_exhaustion_threshold`, etc.), treat the tool's returned value as the definitive, mathematically correct answer. Do NOT perform independent informal calculations or suggest alternative values that contradict the tool output. If the result seems counterintuitive, explain the model's conventions as described in the plan — do not second-guess the computation. Do NOT add hypothetical caveats about alternative window-reset semantics, alternate interpretations, or different timing conventions unless the user explicitly asks about those assumptions.
"""


class HarveyAgent:
    def __init__(self, workflow: MCPWorkflowClient) -> None:
        self._workflow = workflow
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for natural language orchestration")
        client_config = OpenAIClientConfig(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        self._llm = OpenAIClient(client_config)
        self._planning_prompt: Optional[str] = None
        self._answer_prompt: Optional[str] = None
        self._spec_excerpt: Optional[str] = None

    async def handle_question(
        self,
        question: str,
        pricing_urls: Optional[List[str]] = None,
        yaml_contents: Optional[List[str]] = None,
        datasheet_contents: Optional[List[str]] = None,
        mode: str = "all",
    ) -> Dict[str, Any]:
        # Resolve the set of actions permitted for this context mode.
        # Falls back to ALLOWED_ACTIONS for unrecognised mode values.
        allowed_actions: Set[str] = ALLOWED_ACTIONS_BY_MODE.get(mode, ALLOWED_ACTIONS)

        provided_urls = self._deduplicate(pricing_urls or [])
        provided_yamls = [content for content in (yaml_contents or []) if content]
        provided_datasheets = [content for content in (datasheet_contents or []) if content]
        detected_urls = self._extract_urls_from_question(question)
        combined_urls = self._deduplicate(provided_urls + detected_urls)
        yaml_alias_map = self._build_yaml_alias_map(provided_yamls)
        datasheet_alias_map = self._build_datasheet_alias_map(provided_datasheets)
        # Merged map used for alias resolution during action execution.
        combined_alias_map = {**yaml_alias_map, **datasheet_alias_map}

        plan = await self._generate_plan(
            question,
            pricing_urls=combined_urls,
            yaml_alias_map=yaml_alias_map,
            datasheet_alias_map=datasheet_alias_map,
            mode=mode,
        )
        self._validate_yaml_requirement(plan, provided_yamls)

        actions = self._normalize_actions(plan.get("actions"), allowed_actions=allowed_actions)
        objective = self._resolve_default_objective(plan)
        self._apply_legacy_fields(plan, actions)
        default_reference = self._resolve_default_reference(
            plan_reference=plan.get("pricing_url"),
            plan_references=plan.get("pricing_urls"),
            available_urls=combined_urls,
            yaml_aliases=list(combined_alias_map.keys()),
        )

        results, last_payload = await self._execute_actions(
            actions=actions,
            default_reference=default_reference,
            available_urls=combined_urls,
            # filters now action-scoped; legacy top-level filters already distributed.
            objective=objective,
            yaml_alias_map=combined_alias_map,
            allowed_actions=allowed_actions,
        )

        payload_for_answer, result_payload = self._compose_results_payload(actions, results, last_payload)
        answer = await self._generate_answer(question, plan, payload_for_answer, combined_alias_map)

        self._strip_deprecated_plan_fields(plan)
        return {"plan": plan, "result": result_payload, "answer": answer}

    def _resolve_default_objective(self, plan: Dict[str, Any]) -> str:
        legacy_objective = plan.get("objective")
        return legacy_objective if legacy_objective in ("minimize", "maximize") else "minimize"

    def _apply_legacy_fields(self, plan: Dict[str, Any], actions: List[PlannedAction]) -> None:
        """Distribute legacy top-level fields to per-action when needed (backward compatibility)."""
        # Legacy top-level filters
        legacy_filters = self._extract_filters(plan.get("filters"))
        if legacy_filters:
            for action in actions:
                if action.name in ("subscriptions", "optimal") and action.filters is None:
                    action.filters = legacy_filters

        # Legacy top-level solver
        legacy_solver = plan.get("solver")
        if legacy_solver in ("minizinc", "choco"):
            for action in actions:
                if action.name in ("subscriptions", "optimal", "validate") and action.solver is None:
                    action.solver = legacy_solver

    def _strip_deprecated_plan_fields(self, plan: Dict[str, Any]) -> None:
        for deprecated in ["intent_summary", "filters", "objective", "pricing_url", "solver", "refresh"]:
            plan.pop(deprecated, None)

    async def _generate_plan(
        self,
        question: str,
        pricing_urls: List[str],
        yaml_alias_map: Dict[str, str],
        datasheet_alias_map: Optional[Dict[str, str]] = None,
        mode: str = "all",
    ) -> Dict[str, Any]:
        plan_prompt = self._get_planning_prompt(mode)
        spec_excerpt: Optional[str] = None
        if self._should_include_spec(question):
            spec_excerpt = await self._get_spec_excerpt()

        base_messages = self._build_plan_request_messages(
            plan_prompt=plan_prompt,
            question=question,
            pricing_urls=pricing_urls,
            yaml_alias_map=yaml_alias_map,
            datasheet_alias_map=datasheet_alias_map or {},
            spec_excerpt=spec_excerpt,
        )

        attempt_errors: List[str] = []
        for _ in range(PLAN_REQUEST_MAX_ATTEMPTS):
            attempt_messages = list(base_messages)
            if attempt_errors:
                attempt_messages.append(
                    "Previous attempt issues: " + attempt_errors[-1]
                )
                attempt_messages.append(
                    "Return a corrected JSON plan that satisfies all requirements."
                )

            try:
                text = await asyncio.to_thread(
                    self._llm.make_full_request,
                    "\n".join(attempt_messages),
                    json_output=True,
                )
            except ValueError as exc:
                attempt_errors.append(f"LLM response was not valid JSON: {exc}")
                continue

            try:
                plan = self._parse_plan_text(
                    text=text,
                    question=question,
                    pricing_urls=pricing_urls,
                    yaml_alias_map=yaml_alias_map,
                    allow_fallback=False,
                )
            except ValueError as exc:
                attempt_errors.append(str(exc))
                continue

            return plan

        raise ValueError(
            "Failed to obtain a planning response that satisfies tool requirements. "
            + (attempt_errors[-1] if attempt_errors else "")
        )

    def _build_plan_request_messages(
        self,
        *,
        plan_prompt: str,
        question: str,
        pricing_urls: List[str],
        yaml_alias_map: Dict[str, str],
        datasheet_alias_map: Dict[str, str],
        spec_excerpt: Optional[str],
    ) -> List[str]:
        messages: List[str] = [plan_prompt, PLAN_RESPONSE_FORMAT_INSTRUCTIONS]
        messages.append(f"Question: {question}")
        self._append_pricing_urls_message(messages, pricing_urls)
        self._append_yaml_alias_messages(messages, yaml_alias_map)
        self._append_datasheet_messages(messages, datasheet_alias_map)
        self._append_spec_excerpt_message(messages, spec_excerpt)
        return messages

    def _append_pricing_urls_message(self, messages: List[str], pricing_urls: List[str]) -> None:
        if pricing_urls:
            messages.append("Pricing URLs detected/provided (use as-is when planning):")
            for index, url in enumerate(pricing_urls, start=1):
                messages.append(f"{index}. {url}")
            return
        messages.append("Pricing URLs detected/provided: None")

    def _append_yaml_alias_messages(
        self,
        messages: List[str],
        yaml_alias_map: Dict[str, str],
        chunk_size: int = 4000,
        header: Optional[str] = None,
    ) -> None:
        if not yaml_alias_map:
            messages.append("Uploaded Pricing2Yaml aliases: None")
            return

        default_header = (
            "Uploaded Pricing2Yaml content (full, chunked). Use exact feature.name and usageLimit.name from these documents when constructing filters:"
        )
        messages.append(header or default_header)
        for alias, content in yaml_alias_map.items():
            total_len = len(content or "")
            if not content:
                messages.append(f"{alias}: <empty content>")
                continue
            chunks = [content[i : i + chunk_size] for i in range(0, total_len, chunk_size)]
            total_chunks = len(chunks)
            messages.append(f"{alias}: length={total_len} chars; chunks={total_chunks}")
            for idx, chunk in enumerate(chunks, start=1):
                messages.append(f"YAML[{alias}] chunk {idx}/{total_chunks}:")
                messages.append(chunk)

    def _append_datasheet_messages(
        self,
        messages: List[str],
        datasheet_alias_map: Dict[str, str],
        chunk_size: int = 4000,
    ) -> None:
        if not datasheet_alias_map:
            return
        self._append_yaml_alias_messages(
            messages,
            datasheet_alias_map,
            chunk_size=chunk_size,
            header="Uploaded API Datasheet content (full, chunked). Use these as datasheet_source in evaluate_api_datasheet actions:",
        )

    def _append_spec_excerpt_message(
        self,
        messages: List[str],
        spec_excerpt: Optional[str],
    ) -> None:
        if not spec_excerpt:
            return
        messages.append("Pricing2Yaml specification:")
        messages.append(spec_excerpt)

    async def _generate_answer(
        self,
        question: str,
        plan: Dict[str, Any],
        payload: Dict[str, Any],
        yaml_alias_map: Dict[str, str],
    ) -> str:
        answer_prompt = self._get_answer_prompt()
        messages = [answer_prompt]
        messages.append(f"Question: {question}")
        messages.append(f"Plan: {json.dumps(plan, ensure_ascii=False)}")
        payload_summary = self._summarize_tool_payload(payload)
        if payload_summary:
            messages.append(
                f"Tool payload summary: {json.dumps(payload_summary, ensure_ascii=False)}"
            )

        payload_chunks = self._serialise_payload_chunks(payload)
        total_chunks = len(payload_chunks)
        for index, chunk in enumerate(payload_chunks, start=1):
            messages.append(f"Tool payload chunk {index}/{total_chunks}:")
            messages.append(chunk)

        self._append_yaml_alias_messages(
            messages,
            yaml_alias_map,
            header="Reference Pricing2Yaml content (for context):",
        )

        if self._should_include_spec(question, plan):
            spec_excerpt = await self._get_spec_excerpt()
            if spec_excerpt:
                messages.append("Pricing2Yaml specification:")
                messages.append(spec_excerpt)

        response = await asyncio.to_thread(
            self._llm.make_full_request,
            "\n".join(messages),
            json_output=False,
        )
        return response or "No answer could be generated."

    def _parse_plan_text(
        self,
        *,
        text: str,
        question: str,
        pricing_urls: List[str],
        yaml_alias_map: Dict[str, str],
        allow_fallback: bool = True,
    ) -> Dict[str, Any]:
        cleaned = text.strip()
        if not cleaned:
            logger.error("harvey.agent.plan_empty", question=question)
            raise ValueError(
                "H.A.R.V.E.Y. returned an empty planning response. Please retry your question."
            )

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        extracted = self._extract_first_json_block(cleaned)
        if extracted is not None:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                logger.warning(
                    "harvey.agent.plan_partial_json_failed",
                    question=question,
                    fragment=extracted[:500],
                )

        if allow_fallback:
            inferred = self._derive_plan_from_text(
                cleaned,
                question,
                pricing_urls,
                yaml_alias_map,
            )
            if inferred is not None:
                logger.info(
                    "harvey.agent.plan_inferred", question=question, plan=inferred
                )
                return inferred

        logger.error("harvey.agent.plan_unparsed", question=question, raw=cleaned[:1000])
        raise ValueError("Failed to interpret H.A.R.V.E.Y.'s plan. Please rephrase your request.")

    def _derive_plan_from_text(
        self,
        text: str,
        question: Optional[str],
        pricing_urls: List[str],
        yaml_alias_map: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        contexts: List[str] = []
        contexts.extend(pricing_urls)
        contexts.extend(yaml_alias_map.keys())
        if not contexts:
            return None

        combined = f"{(question or '').lower()}\n{text.lower()}"
        actions = self._collect_inferred_actions(combined)
        if not actions:
            return None

        default_reference: Optional[str] = None
        if len(contexts) == 1:
            default_reference = contexts[0]

        return {
            "actions": actions,
            "pricing_url": default_reference,
            "requires_uploaded_yaml": False,
            "intent_summary": self._build_intent_summary(question),
            "objective": "minimize",
            "filters": None,
            "use_pricing2yaml_spec": False,
        }

    def _collect_inferred_actions(self, combined: str) -> List[Any]:
        actions: List[Any] = []

        def contains_any(keywords: List[str]) -> bool:
            return any(keyword in combined for keyword in keywords)

        if contains_any(["summary", "summarise", "summarize", "synopsis", "overview"]):
            actions.append("summary")

        if contains_any(
            [
                "iPricing",
                "i-pricing",
                "pricing yaml",
                "pricing2yaml",
                "pricing 2 yaml",
                "yaml file",
                "download yaml",
                "export yaml",
                "raw yaml",
                "yaml output",
            ]
        ):
            actions.append("iPricing")

        if contains_any(
            [
                "validate",
                "validation",
                "is it valid",
                "check validity",
                "verify yaml",
                "lint yaml",
                "any errors",
                "error in pricing",
                "solver error",
            ]
        ):
            actions.append("validate")

        if contains_any(
            [
                "subscriptions(",
                "subscriptions tool",
                "call the subscriptions",
                "number of different subscription",
                "number of different subscriptions",
                "number of subscriptions",
                "how many subscriptions",
                "how many subscription",
                "subscription count",
                "count of subscriptions",
                "total subscriptions",
                "total number of subscription",
                "enumerate the subscription",
                "number of plans",
                "how many plans",
                "plan count",
                "configuration count",
            ]
        ):
            actions.append("subscriptions")

        if contains_any(
            [
                "best subscription",
                "best plan",
                "best option",
                "cheapest",
                "cheapest plan",
                "least expensive",
                "optimal",
                "minimize",
                "minimise",
                "optimal(",
                "lowest cost",
                "lowest price",
                "minimum price",
                "most affordable",
                "best value",
            ]
        ):
            actions.append({"name": "optimal", "objective": "minimize"})

        if contains_any(
            [
                "most expensive",
                "most expensive plan",
                "priciest",
                "highest priced",
                "highest cost",
                "maximize",
                "maximise",
                "maximize objective",
                "maximum price",
                "premium plan",
            ]
        ):
            actions.append({"name": "optimal", "objective": "maximize"})

        deduped: List[Any] = []
        seen: Set[str] = set()
        for action in actions:
            key = json.dumps(action, sort_keys=True) if isinstance(action, dict) else str(action)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(action)

        return deduped

    def _build_intent_summary(self, question: Optional[str]) -> str:
        if not question:
            return "Plan inferred from non-JSON planning response."
        shortened = question if len(question) <= 160 else f"{question[:157]}..."
        return f"Plan inferred for question: {shortened}"

    def _serialise_payload_chunks(self, payload: Dict[str, Any], chunk_size: int = 4000) -> List[str]:
        if not payload:
            return ["{}"]
        payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(payload_text) <= chunk_size:
            return [payload_text]
        return [payload_text[i : i + chunk_size] for i in range(0, len(payload_text), chunk_size)]

    def _summarize_tool_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not payload:
            return None

        summary: Dict[str, Any] = {}
        cardinalities = self._collect_field_values(payload, "cardinality")
        last_cardinality = self._select_last_int(cardinalities)
        if last_cardinality is not None:
            summary["cardinality"] = last_cardinality

        validation_states = self._collect_field_values(payload, "valid")
        last_validation = self._select_last_bool(validation_states)
        if last_validation is not None:
            summary["valid"] = last_validation

        pricing_yaml_values = [
            value for value in self._collect_field_values(payload, "pricing_yaml") if isinstance(value, str)
        ]
        if pricing_yaml_values:
            summary["pricingYamlLength"] = len(pricing_yaml_values[-1])

        subscriptions = self._extract_subscriptions_list(payload)
        if subscriptions is not None:
            summary["subscriptionCount"] = len(subscriptions)
            missing_cost_plans = [
                entry.get("subscription", {}).get("plan")
                for entry in subscriptions
                if not self._is_numeric_cost(entry.get("cost"))
            ]
            if missing_cost_plans:
                summary["nonNumericCostPlans"] = [plan for plan in missing_cost_plans if plan]

        optimal_entry = self._extract_optimal_entry(payload)
        if optimal_entry:
            summary["bestPlan"] = optimal_entry

        return summary or None

    def _collect_field_values(self, node: Any, key: str) -> List[Any]:
        collected: List[Any] = []

        def visit(current: Any) -> None:
            if isinstance(current, dict):
                if key in current:
                    collected.append(current[key])
                for value in current.values():
                    visit(value)
            elif isinstance(current, list):
                for item in current:
                    visit(item)

        visit(node)
        return collected

    def _select_last_int(self, values: List[Any]) -> Optional[int]:
        for value in reversed(values):
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        return None

    def _select_last_bool(self, values: List[Any]) -> Optional[bool]:
        for value in reversed(values):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "false"}:
                    return lowered == "true"
        return None

    def _extract_subscriptions_list(self, payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        for value in self._collect_field_values(payload, "subscriptions"):
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return None

    def _extract_optimal_entry(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for value in reversed(self._collect_field_values(payload, "optimal")):
            if isinstance(value, dict):
                subscription = value.get("subscription")
                plan = None
                add_ons: Optional[List[str]] = None
                if isinstance(subscription, dict):
                    plan = subscription.get("plan")
                    add_ons_value = subscription.get("addOns")
                    if isinstance(add_ons_value, list):
                        add_ons = [str(item) for item in add_ons_value]
                return {
                    "plan": plan,
                    "cost": value.get("cost"),
                    "addOns": add_ons,
                }
        return None

    def _is_numeric_cost(self, cost: Any) -> bool:
        if cost is None:
            return False
        if isinstance(cost, (int, float)):
            return True
        if isinstance(cost, str):
            stripped = cost.replace("€", "").replace("$", "").replace(",", "").strip()
            try:
                float(stripped)
            except ValueError:
                return False
            return True
        return False

    def _validate_yaml_requirement(self, plan: Dict[str, Any], yaml_contents: List[str]) -> None:
        if plan.get("requires_uploaded_yaml") and not yaml_contents:
            raise ValueError(
                "H.A.R.V.E.Y. needs a Pricing2Yaml file to proceed. Please upload one and retry."
            )

    def _normalize_actions(
        self, raw_actions: Any, *, allowed_actions: Optional[Set[str]] = None
    ) -> List[PlannedAction]:
        normalized: List[PlannedAction] = []
        if raw_actions in (None, []):
            return normalized
        if not isinstance(raw_actions, list):
            logger.warning("harvey.agent.invalid_actions", requested=raw_actions)
            return normalized

        for entry in raw_actions:
            planned_action = self._parse_action_entry(entry, allowed_actions=allowed_actions)
            if planned_action:
                normalized.append(planned_action)

        return normalized

    def _parse_action_entry(
        self,
        entry: Any,
        *,
        allowed_actions: Optional[Set[str]] = None,
        silent: bool = False,
    ) -> Optional[PlannedAction]:
        """Convert a raw action entry into a PlannedAction with minimal branching.
        Accepts either a string (action name) or an object containing name plus optional fields.
        Invalid inputs return None and optionally log a warning.
        allowed_actions restricts which action names are accepted (mode enforcement).
        """
        # Use the provided allow-list; default to the full set for backward compatibility.
        effective_allowed: Set[str] = allowed_actions if allowed_actions is not None else ALLOWED_ACTIONS

        def warn(event: str, **kwargs: Any) -> None:
            if not silent:
                logger.warning(event, **kwargs)

        # Fast path: simple string action
        if isinstance(entry, str):
            return PlannedAction(name=entry) if entry in effective_allowed else None

        # SILENT OVERRIDE: If the LLM incorrectly tries to use a standalone abstract tool
        # but the request is associated with a context, forcibly convert it to evaluate_api_datasheet.
        # Only applies when evaluate_api_datasheet itself is in the allowed set (i.e. API or all mode).
        if (
            "evaluate_api_datasheet" in effective_allowed
            and entry.get("name") in API_ACTIONS
            and entry.get("name") != "evaluate_api_datasheet"
        ):
            # We delay populating the actual datasheet_source to _run_single_action,
            # but we tag it to ensure it gets converted.
            original_name = entry["name"]
            entry["operation"] = original_name
            entry["name"] = "evaluate_api_datasheet"
            
            # Move specific parameters into operation_params if needed
            op_params = {}
            if "capacity_goal" in entry:
                op_params["capacity_goal"] = entry.pop("capacity_goal")
            if "time" in entry:
                op_params["time"] = entry.pop("time")
            if op_params:
                entry["operation_params"] = op_params
            
            # Note: We deliberately leave datasheet_source out if it wasn't provided,
            # so the auto-injector in _run_single_action handles it.
            warn("harvey.agent.overrode_standalone_tool", original=original_name)

        name = entry.get("name")
        if name not in effective_allowed:
            warn("harvey.agent.invalid_action_object", requested=entry)
            return None

        # Context-free API action — extract its specific params and return early.
        if name in API_ACTIONS:
            params: Dict[str, Any] = {}
            if name == "evaluate_api_datasheet":
                params["datasheet_source"] = entry.get("datasheet_source")
                params["plan_name"] = entry.get("plan_name")
                params["operation"] = entry.get("operation")
                if "operation_params" in entry:
                    params["operation_params"] = entry.get("operation_params")
                if "endpoint_path" in entry:
                    params["endpoint_path"] = entry.get("endpoint_path")
                if "alias" in entry:
                    params["alias"] = entry.get("alias")
                return PlannedAction(name=name, params=params)

            # min_time specific
            if entry.get("capacity_goal") is not None:
                params["capacity_goal"] = entry["capacity_goal"]
            # capacity_at specific
            if entry.get("time") is not None:
                params["time"] = entry["time"]
            # capacity_during specific
            if entry.get("end_instant") is not None:
                params["end_instant"] = entry["end_instant"]
            if entry.get("start_instant") is not None:
                params["start_instant"] = entry["start_instant"]
            # common rate/quota
            if entry.get("rate") is not None:
                params["rate"] = entry["rate"]
            if entry.get("quota") is not None:
                params["quota"] = entry["quota"]
            return PlannedAction(name=name, params=params or None)

        objective = entry.get("objective")
        if objective not in (None, "minimize", "maximize"):
            warn("harvey.agent.invalid_objective", action=name, objective=objective)
            objective = None

        pricing_url = entry.get("pricing_url") or entry.get("url")
        if pricing_url is not None and not isinstance(pricing_url, str):
            warn("harvey.agent.invalid_pricing_url", action=name, pricing_url=pricing_url)
            pricing_url = None

        raw_filters = entry.get("filters")
        action_filters = self._extract_filters(raw_filters) if raw_filters is not None else None
        if raw_filters is not None and action_filters is None:
            warn("harvey.agent.invalid_action_filters", action=name, filters=raw_filters)

        solver = entry.get("solver")
        if solver not in (None, "minizinc", "choco"):
            warn("harvey.agent.invalid_solver", action=name, solver=solver)
            solver = None

        return PlannedAction(
            name=name,
            objective=objective,
            pricing_url=pricing_url,
            filters=action_filters,
            solver=solver,
        )

    def _extract_filters(self, raw_filters: Any) -> Optional[Dict[str, Any]]:
        if raw_filters is None or raw_filters == {}:
            return None
        if isinstance(raw_filters, dict):
            return raw_filters
        logger.warning("harvey.agent.invalid_filters", provided=raw_filters)
        return None

    def _resolve_default_reference(
        self,
        *,
        plan_reference: Any,
        plan_references: Any,
        available_urls: List[str],
        yaml_aliases: List[str],
    ) -> Optional[str]:
        references: List[str] = []

        def _append(value: Any) -> None:
            if isinstance(value, str) and value.strip():
                references.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    _append(item)

        _append(plan_reference)
        _append(plan_references)

        for reference in references:
            return reference

        total_contexts = len(available_urls) + len(yaml_aliases)
        if total_contexts == 1:
            if available_urls:
                return available_urls[0]
            return yaml_aliases[0]
        return None

    async def _execute_actions(
        self,
        *,
        actions: List[PlannedAction],
        default_reference: Optional[str],
        available_urls: List[str],
        objective: str,
        yaml_alias_map: Dict[str, str],
        allowed_actions: Optional[Set[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not actions:
            return [], None

        # Hard enforcement: even if the LLM somehow produced an action that bypassed
        # the prompt-level restriction, we reject it here before any MCP call is made.
        effective_allowed: Set[str] = allowed_actions if allowed_actions is not None else ALLOWED_ACTIONS
        for action in actions:
            if action.name not in effective_allowed:
                raise ValueError(
                    f"Action '{action.name}' is not permitted in the current context mode. "
                    f"Allowed actions: {sorted(effective_allowed)}."
                )

        self._ensure_pricing_context(
            actions,
            default_reference=default_reference,
            available_urls=available_urls,
            yaml_alias_map=yaml_alias_map,
        )

        results: List[Dict[str, Any]] = []
        last_payload: Optional[Dict[str, Any]] = None

        for index, action in enumerate(actions):
            action_url, action_yaml, context_reference = self._prepare_action_inputs(
                action=action,
                default_reference=default_reference,
                available_urls=available_urls,
                yaml_alias_map=yaml_alias_map,
            )

            payload = await self._run_single_action(
                action=action,
                url=action_url,
                objective=objective,
                yaml_content=action_yaml,
                default_reference=context_reference or default_reference,
            )

            step_record: Dict[str, Any] = {
                "index": index,
                "action": action.name,
                "payload": payload,
            }
            if action.name == "optimal":
                step_record["objective"] = action.objective or objective
            if action.filters is not None and action.name in ("subscriptions", "optimal"):
                step_record["filters"] = action.filters
            if action.solver:
                step_record["solver"] = action.solver
            if action_url:
                step_record["url"] = action_url
            if context_reference:
                step_record["pricingContext"] = context_reference
            results.append(step_record)
            last_payload = payload

        return results, last_payload

    def _ensure_pricing_context(
        self,
        actions: List[PlannedAction],
        default_reference: Optional[str],
        available_urls: List[str],
        yaml_alias_map: Dict[str, str],
    ) -> None:
        total_contexts = len(available_urls) + len(yaml_alias_map)
        for action in actions:
            reference = action.pricing_url or default_reference
            if reference and not self._is_known_reference(reference, available_urls, yaml_alias_map):
                raise ValueError(
                    f"Unknown pricing context '{reference}'. Use one of: {available_urls + list(yaml_alias_map.keys())}."
                )

            if action.name in ACTION_REQUIRES_CONTEXT:
                self._assert_context_available(
                    reference,
                    total_contexts,
                )

    def _prepare_action_inputs(
        self,
        *,
        action: PlannedAction,
        default_reference: Optional[str],
        available_urls: List[str],
        yaml_alias_map: Dict[str, str],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        reference = self._determine_reference(
            action,
            default_reference,
            available_urls,
            yaml_alias_map,
        )
        action_url: Optional[str] = None
        action_yaml: Optional[str] = None

        if reference:
            if reference in yaml_alias_map:
                action_yaml = yaml_alias_map[reference]
            else:
                action_url = reference

        # For evaluate_api_datasheet, also resolve the datasheet_source alias directly.
        # _determine_reference returns None for this action (it's not in ACTION_REQUIRES_CONTEXT),
        # so action_yaml would otherwise stay None and the alias would reach Prime4API verbatim.
        if action.name == "evaluate_api_datasheet" and action_yaml is None:
            ds_source = (action.params or {}).get("datasheet_source")
            if ds_source and ds_source in yaml_alias_map:
                action_yaml = yaml_alias_map[ds_source]

        return action_url, action_yaml, reference

    def _determine_reference(
        self,
        action: PlannedAction,
        default_reference: Optional[str],
        available_urls: List[str],
        yaml_alias_map: Dict[str, str],
    ) -> Optional[str]:
        reference = action.pricing_url or default_reference
        if reference:
            return reference

        # Context-free actions (e.g., min_time) don't need a pricing reference at all.
        if action.name not in ACTION_REQUIRES_CONTEXT:
            return None

        total_contexts = len(available_urls) + len(yaml_alias_map)
        if total_contexts == 0:
            return None
        if total_contexts == 1:
            if available_urls:
                return available_urls[0]
            return next(iter(yaml_alias_map))

        raise ValueError(
            "Multiple pricing contexts detected. Each action must specify pricing_url to choose which pricing to analyse."
        )

    def _assert_context_available(
        self,
        reference: Optional[str],
        total_contexts: int,
    ) -> None:
        if total_contexts == 0:
            raise ValueError(
                "Provide at least one pricing URL or Pricing2Yaml upload before calling tooling."
            )
        if reference is None and total_contexts > 1:
            raise ValueError(
                "Multiple pricing contexts detected. Set pricing_url on each action to choose the correct pricing source."
            )

    def _is_known_reference(
        self,
        reference: str,
        available_urls: List[str],
        yaml_alias_map: Dict[str, str],
    ) -> bool:
        return (
            reference in yaml_alias_map
            or reference in available_urls
            or self._looks_like_url(reference)
        )

    def _looks_like_url(self, value: str) -> bool:
        return bool(URL_PATTERN.match(value))

    def _deduplicate(self, values: List[str]) -> List[str]:
        seen: Set[str] = set()
        result: List[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _extract_urls_from_question(self, question: str) -> List[str]:
        if not question:
            return []
        matches = URL_PATTERN.findall(question)
        return self._deduplicate(matches)

    def _build_yaml_alias_map(self, yaml_contents: List[str]) -> Dict[str, str]:
        alias_map: "OrderedDict[str, str]" = OrderedDict()
        # Avoid duplicating a single upload with two aliases. If only one pricing
        # is provided, expose a single canonical alias: "uploaded://pricing".
        # For multiple uploads, keep numbered aliases to disambiguate.
        if len(yaml_contents) == 1:
            if yaml_contents[0]:
                alias_map["uploaded://pricing"] = yaml_contents[0]
        else:
            for index, content in enumerate(yaml_contents):
                if not content:
                    continue
                alias = f"uploaded://pricing/{index + 1}"
                alias_map[alias] = content
        return dict(alias_map)

    def _build_datasheet_alias_map(self, datasheet_contents: List[str]) -> Dict[str, str]:
        alias_map: "OrderedDict[str, str]" = OrderedDict()
        if len(datasheet_contents) == 1:
            if datasheet_contents[0]:
                alias_map["uploaded://datasheet"] = datasheet_contents[0]
        else:
            for index, content in enumerate(datasheet_contents):
                if not content:
                    continue
                alias_map[f"uploaded://datasheet/{index + 1}"] = content
        return dict(alias_map)

    async def _run_single_action(
        self,
        *,
        action: PlannedAction,
        url: Optional[str],
        objective: str,
        yaml_content: Optional[str],
        default_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_objective = action.objective or objective
        effective_solver = action.solver or "minizinc"
        if action.name == "evaluate_api_datasheet":
            p = action.params or {}
            source = p.get("datasheet_source")
            if not source and default_reference is not None:
                source = default_reference
            elif not source and url is not None:
                source = url
            # If yaml_content is available and source is not an external URL, pass the
            # actual YAML text directly. Prime4API cannot resolve aliases like
            # "uploaded://pricing" — yaml.safe_load would treat the alias as a YAML
            # scalar (a plain string) and then fail when trying to access .get("plans").
            if yaml_content is not None and (
                source is None or not source.startswith("http")
            ):
                source = yaml_content

            return await self._workflow.run_evaluate_api_datasheet(
                datasheet_source=source,
                plan_name=p.get("plan_name") or "default",
                operation=p.get("operation") or "min_time",
                operation_params=p.get("operation_params"),
                endpoint_path=p.get("endpoint_path"),
                alias=p.get("alias"),
            )
        if action.name == "min_time":
            p = action.params or {}
            return await self._workflow.run_min_time(
                capacity_goal=p.get("capacity_goal", 1),
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "capacity_at":
            p = action.params or {}
            return await self._workflow.run_capacity_at(
                time=p.get("time", "0ms"),
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "capacity_during":
            p = action.params or {}
            return await self._workflow.run_capacity_during(
                end_instant=p.get("end_instant", "0ms"),
                start_instant=p.get("start_instant", "0ms"),
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "quota_exhaustion_threshold":
            p = action.params or {}
            return await self._workflow.run_quota_exhaustion_threshold(
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "rates":
            p = action.params or {}
            return await self._workflow.run_rates(
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "quotas":
            p = action.params or {}
            return await self._workflow.run_quotas(
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "limits":
            p = action.params or {}
            return await self._workflow.run_limits(
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "idle_time_period":
            p = action.params or {}
            return await self._workflow.run_idle_time_period(
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "summary":
            return await self._workflow.run_summary(url=url, yaml_content=yaml_content, refresh=False)
        if action.name == "iPricing":
            return await self._workflow.run_ipricing(
                url=url,
                yaml_content=yaml_content,
                refresh=False,
            )
        if action.name == "subscriptions":
            return await self._workflow.run_subscriptions(
                url=url or "",
                filters=action.filters,
                solver=effective_solver,
                refresh=False,
                yaml_content=yaml_content,
            )
        if action.name == "validate":
            return await self._workflow.run_validate(
                url=url,
                yaml_content=yaml_content,
                solver=effective_solver,
                refresh=False,
            )
        return await self._workflow.run_optimal(
            url=url or "",
            filters=action.filters,
            solver=effective_solver,
            objective=resolved_objective,
            refresh=False,
            yaml_content=yaml_content,
        )

    def _compose_results_payload(
        self,
        actions: List[PlannedAction],
        results: List[Dict[str, Any]],
        last_payload: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not results:
            empty_payload: Dict[str, Any] = {"steps": []}
            return empty_payload, empty_payload

        if len(results) == 1:
            step_record = results[0]
            payload = step_record.get("payload")
            if payload is None:
                payload = last_payload or {}
            return payload, step_record

        combined: Dict[str, Any] = {
            "actions": [action.name for action in actions],
            "steps": results,
        }
        if last_payload is not None:
            combined["lastPayload"] = last_payload
        return combined, combined

    def _get_planning_prompt(self, mode: str = "all") -> str:
        # Return the mode-specific planning prompt. The cached self._planning_prompt
        # is no longer used because the selection is per-request based on mode.
        if mode == "saas":
            return SAAS_PLAN_PROMPT
        if mode == "api":
            return API_PLAN_PROMPT
        return DEFAULT_PLAN_PROMPT

    def _get_answer_prompt(self) -> str:
        if self._answer_prompt is None:
            self._answer_prompt = DEFAULT_ANSWER_PROMPT
        return self._answer_prompt

    @staticmethod
    def _extract_first_json_block(text: str) -> Optional[str]:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "{[":
                continue
            try:
                _, offset = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            end = index + offset
            return text[index:end]
        return None

    async def _get_spec_excerpt(self) -> str:
        if self._spec_excerpt is None:
            text: Optional[str] = None
            try:
                text = await self._workflow.read_resource_text(SPEC_RESOURCE_ID)
            except MCPClientError as exc:
                logger.warning("harvey.agent.spec_resource_fallback", error=str(exc))
            if not text:
                logger.warning("harvey.agent.spec_resource_empty")
            self._spec_excerpt = text
        if not self._spec_excerpt:
            raise ValueError(
                "Pricing2Yaml specification is unavailable. Ensure resource://pricing/specification is "
                "exposed or the local specification file is present."
            )
        return self._spec_excerpt

    def _should_include_spec(self, question: str, plan: Optional[Dict[str, Any]] = None) -> bool:
        if plan and plan.get("use_pricing2yaml_spec"):
            return True
        lowered = question.lower()
        keywords = [
            "pricing2yaml",
            "pricing 2 yaml",
            "yaml spec",
            "schema",
            "syntax",
            "ipricing",
            "validate",
            "validation",
            "valid",
            "invalid",
            "error",
        ]
        return any(keyword in lowered for keyword in keywords)
