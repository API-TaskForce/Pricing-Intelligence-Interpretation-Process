from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

#

from .clients import MCPClientError, MCPWorkflowClient
from .config import get_settings
from .logging import get_logger
from .llm_client import (
    ChatMessage,
    LLMUsage,
    OpenAIClientConfig,
    OpenAIClient,
)

logger = get_logger(__name__)

# ── Action categories ─────────────────────────────────────────────────────────

RATE_QUOTA_ACTIONS: Set[str] = {
    "min_time",
    "capacity_at",
    "quota_exhaustion_threshold",
    "rates",
    "quotas",
    "limits",
    "idle_time_period",
    "capacity_curve_inflection",
}

DATASHEET_ACTIONS: Set[str] = {
    "datasheet_min_time",
    "datasheet_capacity_at",
    "datasheet_quota_exhaustion_threshold",
    "datasheet_idle_time_period",
    "datasheet_rates",
    "datasheet_quotas",
    "datasheet_limits",
    "datasheet_capacity_curve_inflection",
}

NAV_ACTIONS: Set[str] = {
    "datasheet_nav_plans",
    "datasheet_nav_endpoints",
    "datasheet_nav_crf_ranges",
    "datasheet_nav_capacity_units",
    "datasheet_nav_aliases",
}

DEMAND_ACTIONS: Set[str] = {
    "demand_evaluation",
    "demand_evaluation_chart",
}

BUDGET_ACTIONS: Set[str] = {
    "budget_recommendation",
    "budget_recommendation_chart",
}

API_ACTIONS: Set[str] = (
    RATE_QUOTA_ACTIONS | DATASHEET_ACTIONS | NAV_ACTIONS | DEMAND_ACTIONS | BUDGET_ACTIONS
)

PLAN_RESPONSE_MODES = {"answer", "clarify"}
CLARIFICATION_FIELDS = {"plan_name", "endpoint_path", "alias", "capacity_unit", "capacity_request_factor"}

PLAN_REQUEST_MAX_ATTEMPTS = 3
SHORT_REPLY_MAX_WORDS = 6
MAX_HISTORY_TURNS = 20

STANDALONE_TO_DATASHEET: Dict[str, str] = {
    "min_time": "datasheet_min_time",
    "capacity_at": "datasheet_capacity_at",
    "quota_exhaustion_threshold": "datasheet_quota_exhaustion_threshold",
    "rates": "datasheet_rates",
    "quotas": "datasheet_quotas",
    "limits": "datasheet_limits",
    "idle_time_period": "datasheet_idle_time_period",
    "capacity_curve_inflection": "datasheet_capacity_curve_inflection",
}

# Base actions whose chart-producing variant should be used when the caller
# requests that every answer include a visualisation (force_chart). The chart
# variants accept the same params (chart-only extras default safely), so a plain
# rename is enough. capacity_curve_inflection / datasheet_capacity_curve_inflection
# already produce charts and need no remapping.
TO_CHART_VARIANT: Dict[str, str] = {
    "budget_recommendation": "budget_recommendation_chart",
    "demand_evaluation": "demand_evaluation_chart",
}

# Reverse of TO_CHART_VARIANT plus the chart-only tools: used to "suppress" chart
# generation in ask mode so the text answer returns fast.
CHART_TO_BASE: Dict[str, str] = {
    "budget_recommendation_chart": "budget_recommendation",
    "demand_evaluation_chart": "demand_evaluation",
}

# Chart-only tools that have no text-producing counterpart. In ask mode they are
# dropped from execution entirely (regenerated later if the user confirms).
CHART_ONLY_ACTIONS: Set[str] = {
    "capacity_curve_inflection",
    "datasheet_capacity_curve_inflection",
}

# Every action from which a chart could be produced: directly, by upgrading to a
# *_chart variant, or by deriving an inflection capacity-curve from its rate/quota
# (any BoundedRate action) or datasheet params. Drives the "a chart is available"
# signal for the UI and what force_chart can visualise. NAV actions are excluded.
CHART_CAPABLE_ACTIONS: Set[str] = (
    CHART_ONLY_ACTIONS
    | set(TO_CHART_VARIANT.keys())
    | set(TO_CHART_VARIANT.values())
    | RATE_QUOTA_ACTIONS
    | DATASHEET_ACTIONS
)

FORCE_CHART_INSTRUCTION = (
    "CHART PREFERENCE (user setting enabled): The user wants every answer to include a "
    "visualisation whenever one is possible. Whenever the action you choose has a chart "
    "variant, you MUST use that variant: budget_recommendation_chart instead of "
    "budget_recommendation, demand_evaluation_chart instead of demand_evaluation, and "
    "capacity_curve_inflection / datasheet_capacity_curve_inflection for capacity-curve "
    "questions. Never answer in plain text when a *_chart tool can satisfy the question."
)

# ── Prompts ───────────────────────────────────────────────────────────────────

PLAN_RESPONSE_FORMAT_INSTRUCTIONS = """Respond with a single JSON object:
{"actions": [...]}

Action shapes — RateObject/QuotaObject: {"value": number, "unit": string, "period": string}

## Bounded-rate tools (no datasheet)
  {"name": "min_time", "capacity_goal": number, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "capacity_at", "time": string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "quota_exhaustion_threshold", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "rates", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "quotas", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "limits", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "idle_time_period", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "capacity_curve_inflection", "time_interval": string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}

## Datasheet calculation tools
  {"name": "datasheet_min_time", "datasheet_source": string, "capacity_goal": number, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_capacity_at", "datasheet_source": string, "time": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_quota_exhaustion_threshold", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_idle_time_period", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_rates", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_quotas", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_limits", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}
  {"name": "datasheet_capacity_curve_inflection", "datasheet_source": string, "time_interval": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number|string}

## Datasheet navigation tools (always combine with a calc tool — never use alone)
  {"name": "datasheet_nav_plans", "datasheet_source": string}
  {"name": "datasheet_nav_endpoints", "datasheet_source": string, "plan_name"?: string}
  {"name": "datasheet_nav_crf_ranges", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string}
  {"name": "datasheet_nav_capacity_units", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string}
  {"name": "datasheet_nav_aliases", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string}

## Demand evaluation tools — DemandInput: {"label": string, "rate"?: RateObject, "quota"?: [QuotaObject], "duration"?: string, "demand_crf"?: {"<capacity_unit_name>": number}}
- demand_crf key MUST be the actual unit name (e.g. "emails", "MBs") — NEVER use the literal string "unit" as the key.
  Examples: demand_crf={"emails": 1} means 1 email per API call; demand_crf={"MBs": 0.5} means 0.5 MB per call.
  {"name": "demand_evaluation", "datasheet_source": string, "demands": [DemandInput], "time_interval": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number}
  {"name": "demand_evaluation_chart", "datasheet_source": string, "demands": [DemandInput], "time_interval": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number}

## Budget recommendation tools
  {"name": "budget_recommendation", "datasheet_source": string, "desired_capacity": number, "capacity_unit": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "max_budget"?: number, "no_overage"?: boolean, "capacity_request_factor"?: number}
  {"name": "budget_recommendation_chart", "datasheet_source": string, "desired_capacity": number, "capacity_unit": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "max_budget"?: number, "no_overage"?: boolean, "capacity_request_factor"?: number, "time_horizon"?: string}

Rules:
- Valid JSON, double quotes only. No markdown fences or natural language wrapper.
- Leave actions empty only when the answer is directly inferable without any tool call.
- CRITICAL: When an uploaded Datasheet or datasheet URL is present in context, you MUST use datasheet_* tools. NEVER use standalone tools (limits, rates, quotas, min_time, capacity_at, etc.) when a datasheet is available. Standalone tools only work when no datasheet exists and the user provides explicit rate/quota values.
- plan_name is optional for datasheet tools. Omit when the user wants cross-plan results.
- endpoint_path and alias are optional filters — omit when not specified by the user.
- capacity_unit is optional — include when the user specifies a unit (e.g., "emails", "MBs").
- capacity_request_factor is optional — include only when the user explicitly states units per API call.
- Multiple scenarios (different plans, goals, endpoints, time windows) → one action per scenario.
- For demand_evaluation/chart: demands is required and must be a non-empty list.
- For budget_recommendation/chart: desired_capacity and capacity_unit are required.
"""

PLAN_CLARIFICATION_FORMAT_INSTRUCTIONS = """Additional planning rules:
- You may return {"response_mode":"answer"|"clarify","clarification_fields"?: [...], "actions":[...]}.
- response_mode defaults to "answer". Use "clarify" when a precise datasheet answer should wait for user input.
- clarification_fields may contain only: "plan_name", "endpoint_path", "alias", "capacity_unit", "capacity_request_factor".
- In clarify mode, actions may contain NAV tools only. Use the minimum nav calls needed for a grounded follow-up.
- Use conversation history to resolve short follow-up replies like "Pro", "/mail/send", or "500 emails per call".
- CRITICAL — intent recovery from history: when the current message is a short clarification reply (e.g. "para todos los planes y crf 1", "plan pro", "1 email por llamada") and conversation history contains a demand/compatibility question ("puedo mantener", "es compatible", "can I sustain", "aguanta", "soporta", "es viable"), ALWAYS resolve to demand_evaluation — never to datasheet_limits, datasheet_rates, or datasheet_quotas. Reconstruct the full demand from the original question (rate, quota, duration) and apply the clarification values (plan_name, capacity_request_factor) as filters.

Default rule with a datasheet: ask for BOTH plan_name and capacity_request_factor unless exceptions below apply.

Exceptions — when NOT to ask for plan_name:
- User explicitly says "todos los planes", "all plans", "across plans", "compara", "versus".
- User asks an open recommendation or budget question: "qué plan me conviene", "which plan is best", "recomiéndame un plan", "cuál es la opción más barata", "cheapest option", "más económico". In ALL these cases the plan is the OUTPUT of the tool — never ask for it as input.
  Note: "qué plan entre X e Y me conviene" DOES specify plans — extract them and proceed without clarifying.
- Plan was already given in conversation history.
- The datasheet YAML is available in context AND it defines exactly ONE plan — read the plan name directly from the YAML and use it; do NOT ask the user to confirm it.

Exceptions — when NOT to ask for capacity_request_factor:
- No datasheet is present (CRF only makes sense when reading from a datasheet).
- The datasheet does not define CRF ranges (i.e. no capacity_request_factor or crf_ranges field in the YAML). If the datasheet has no CRF concept, never ask for it.
- User already stated units per call (e.g. "1 email por llamada", "500 per request", "crf=10").
- CRF was already established in conversation history.

Other clarification fields:
- Ask for endpoint_path only when the datasheet has multiple distinct endpoints and the answer depends on which one.
- Ask for capacity_unit ONLY when the datasheet genuinely has multiple distinct capacity units AND the user has not specified one.
- The UI provides interactive dropdowns; do NOT suggest typing special keywords like "por defecto".
- Clarification example: {"response_mode":"clarify","clarification_fields":["plan_name","capacity_request_factor"],"actions":[{"name":"datasheet_nav_plans","datasheet_source":"uploaded://datasheet"},{"name":"datasheet_nav_crf_ranges","datasheet_source":"uploaded://datasheet","endpoint_path":"/mail/send"}]}
"""


@dataclass
class PlannedAction:
    name: str
    params: Optional[Dict[str, Any]] = None


PLAN_PROMPT = """You are H.A.R.V.E.Y., an expert AI agent designed to reason about API rate and quota constraints using the ReAct pattern (Reasoning + Acting).
Your goal is to create a precise execution plan to answer the user's question about API consumption, rate limits, quota constraints, and pricing plans.

### Tools Without Datasheet Context

- **"min_time"**: Computes the minimum time to reach a capacity goal from direct rate/quota objects.
  - **Use when:** The user asks how long it takes to reach N API calls and provides rate/quota directly.

- **"capacity_at"**: Computes the accumulated capacity at a specific time instant from rate/quota objects.
  - **Use when:** The user asks "How many API calls in X days?" and provides rate/quota directly.

- **"quota_exhaustion_threshold"**: Computes the minimum time to exhaust each quota at max rate.
  - **Use when:** "How fast can I blow through my quota?"

- **"rates"**: Retrieves effective maximum consumption rates.
- **"quotas"**: Retrieves effective quota boundaries.
- **"limits"**: Retrieves all combined active limits (rates and quotas).
- **"idle_time_period"**: Computes blocked wait time after exhausting quota at max speed.

- **"capacity_curve_inflection"**: Generates an interactive inflection-point capacity curve chart (no datasheet).
  - **Inputs:** time_interval (e.g. "1h", "1day"), rate/quota objects.
  - **Returns:** {"html": "..."} — embedded Plotly chart.
  - **Use when:** The user wants to visualise capacity over time with raw rate/quota data.

### Datasheet Calculation Tools

Use these when a datasheet is uploaded or referenced via URL.

- **"datasheet_min_time"**: Min time to capacity goal from datasheet.
- **"datasheet_capacity_at"**: Capacity at time T from datasheet.
- **"datasheet_quota_exhaustion_threshold"**: Time to exhaust quotas from datasheet.
- **"datasheet_idle_time_period"**: Idle time after quota exhaustion from datasheet.
- **"datasheet_rates"**: Effective rates from datasheet.
- **"datasheet_quotas"**: Effective quota limits from datasheet.
- **"datasheet_limits"**: Combined rate+quota limits from datasheet.

Common optional inputs: plan_name, endpoint_path, alias, capacity_unit, capacity_request_factor.
datasheet_source: uploaded alias (e.g. "uploaded://datasheet") or HTTP URL.

- **"datasheet_capacity_curve_inflection"**: Interactive inflection-point capacity curve chart from datasheet.
  - **Inputs:** datasheet_source, time_interval (e.g. "1h", "1day", "1month"), optional filters.
  - **Returns:** {"html": "..."} — embedded Plotly chart.
  - **Use when:** The user asks to visualise, plot, or chart the capacity curve from a datasheet.

### Datasheet Navigation Tools

These are supplementary — always combine with a calc tool, never use alone.

- **"datasheet_nav_plans"**: Lists all plan names. Use when plan names are unknown.
- **"datasheet_nav_endpoints"**: Lists endpoint paths for a plan.
- **"datasheet_nav_capacity_units"**: Lists capacity units (e.g., "emails", "MBs").
- **"datasheet_nav_aliases"**: Lists endpoint aliases.
- **"datasheet_nav_crf_ranges"**: Returns min/max CRF range per capacity unit.
  INCLUDE THIS alongside any calc tool when the user has NOT specified their batch size / units per API call.

### Demand Evaluation Tools

Use these when the user wants to know if their consumption pattern fits within plan limits.

- **"demand_evaluation"**: Evaluates whether plans satisfy custom demand patterns. Returns YES/NO/DEPENDS per plan/endpoint/demand.
  - **Inputs:** datasheet_source, demands (list of demand scenarios), time_interval, optional filters.
  - DemandInput shape: {"label": string, "rate"?: RateObj, "quota"?: [QuotaObj], "duration"?: string, "demand_crf"?: {"<capacity_unit_name>": number}}
    - demand_crf key = the actual capacity unit name (e.g. {"emails": 1}, {"MBs": 0.5}) — NEVER use the literal key "unit"
  - **Use when:** The user provides explicit rate AND/OR quota values and asks whether they are feasible/compatible/sustainable. The trigger is intent, not phrasing — any of these should map to demand_evaluation:
    - "¿Puedo mantener 10 RPS y 2.000 emails/día durante 30 días?" → rate={value:10,unit:"requests",period:"1s"}, quota=[{value:2000,unit:"emails",period:"1day"}], duration="30days"
    - "¿Es viable enviar 500 req/min con un límite de 10k emails/mes?" → rate={value:500,unit:"requests",period:"1min"}, quota=[{value:10000,unit:"emails",period:"1month"}]
    - "¿Aguanta el plan si envío 5 peticiones/s y 1.000 emails/hora?" → same mapping
    - "Si envío a 10 RPS, ¿podré cumplir con 2.000 correos diarios?" → same
    - "Can I sustain X req/s and Y/month?" → same pattern
    - "Does my workload fit the free tier?" → demand_evaluation
    - "¿Es compatible mi uso con el plan?" → demand_evaluation
    - "¿Soporta el plan X RPS?" (only rate, no quota) → demand_evaluation with only rate
    - "¿Aguanto la cuota si envío 1.000 emails/día?" (only quota) → demand_evaluation with only quota
  - **CRITICAL:** Use demand_evaluation as a SINGLE action. NEVER decompose this into separate datasheet_rates + datasheet_quotas + manual comparison calls. demand_evaluation does the comparison internally and returns YES/NO/DEPENDS per plan.

- **"demand_evaluation_chart"**: Interactive chart of plan capacity curves vs demand curves.
  - **Returns:** {"html": "..."} — embedded Plotly chart.
  - **Use when:** The user asks to visualise or chart the demand vs capacity comparison.

### Budget Recommendation Tools

Use these when the user wants to find the cheapest plan for a capacity goal.

- **"budget_recommendation"**: Recommends best plans by cost for a desired capacity.
  - **Inputs:** datasheet_source, desired_capacity (number), capacity_unit (string), optional filters.
  - **Returns:** plan recommendations with base_cost, overage_cost, total_cost, affordable, time_to_capacity.
  - **Use when:** "Which plan is cheapest to reach 500k emails?" or "What plan fits my budget of $200?"

- **"budget_recommendation_chart"**: Interactive chart showing cost vs capacity + capacity vs time.
  - **Returns:** {"html": "..."} — embedded Plotly chart.
  - **Use when:** The user asks to visualise plan costs or compare plans graphically.

### Datasheet Notes

- datasheet_source: always an uploaded alias (e.g. "uploaded://datasheet") or one HTTP URL.
- plan_name: optional. Omit to get results across all plans.
- endpoint_path: optional. Omit to get results across all endpoints.
- capacity_request_factor (CRF): units consumed per API call. Any value within the datasheet's CRF range is valid.
  - Single unit: plain number + set capacity_unit (e.g., capacity_unit="emails", capacity_request_factor=1).
  - Multiple units simultaneously: JSON string dict where keys are the actual capacity unit names from the
    datasheet (as returned by datasheet_nav_capacity_units) and values are the user-specified amounts.
    Example with emails+MBs: capacity_request_factor='{"emails":1,"MBs":0.256}'.
    Any unit name is valid as a key — use whatever units the datasheet defines (e.g. "tokens", "requests",
    "images", "credits", etc.).
  - CRITICAL: when the user specifies CRF values for multiple dimensions, you MUST pass them as a JSON
    string dict — NEVER use rate/quota params to convey the user's CRF intent.
    datasheet_* tools ignore rate/quota fields; capacity_request_factor is the only way to specify CRF.
- When CRF is omitted, prime4api returns 3 automatic scenarios (min/typical/max CRF).

### Planning Rules
1. Analyse the user's intent.
2. CRITICAL: If a datasheet or datasheet URL is present → ALWAYS use datasheet_* tools. This is non-negotiable. Never use standalone tools (limits, rates, quotas, min_time, capacity_at, quota_exhaustion_threshold, idle_time_period, capacity_curve_inflection) when any datasheet context exists.
3. CRITICAL: If the user provides explicit rate AND/OR quota values and asks whether they are feasible/sustainable/compatible → ALWAYS use demand_evaluation as a SINGLE action. Map the rate to demands[].rate and the quota to demands[].quota. NEVER substitute this with separate datasheet_rates + datasheet_quotas calls — that approach does not answer the compatibility question, it only retrieves limits.
4. If the user asks which plan is cheapest / fits a budget → use budget_recommendation or budget_recommendation_chart.
5. If the user asks to visualise a chart → use the corresponding *_chart tool.
6. When the user has NOT specified CRF/batch size and no datasheet chart is requested → add datasheet_nav_crf_ranges alongside the calc tool.
7. When the user already named a plan (e.g. "plan pro"), include plan_name in the action — never clarify for it.
8. When the user asks for all plans or a comparison → omit plan_name; do NOT clarify.
9. If the user says "para todos los planes" / "todos los planes" / "sin filtros" → call the tool with only datasheet_source, no filters at all.
10. Return {"actions": []} only when you genuinely cannot determine any action. The answer phase will ask one clarifying question.

### Response Format
Return a JSON object with the plan. See the accompanying format instructions.
"""

ANSWER_PROMPT = """You are H.A.R.V.E.Y., the Holistic Analysis and Regulation Virtual Expert for You.
You have executed an API analysis plan and now need to formulate the final answer for the user.
Your answers must be clear, practical, and written as if advising a developer — not dumping raw data.

### Inputs Available to You
1. User Question: The original request.
2. Plan: The actions you decided to take.
3. Tool Results: The JSON payloads returned by the tools.
4. Datasheet Context: The raw Datasheet YAML content or datasheet aliases/URLs when available.
5. Nav Results (if present): Output from nav tools — CRF ranges, available capacity units, plan lists, endpoint lists.

### Core Interpretation Rules

**1. Never expose internal field names to the user.**
- The fields `workload_factor` and `capacity_request_factor` are internal API parameters. Translate them
  to domain language using the capacity_unit from nav results or from context.
  - If the endpoint sends emails and the CRF is the number of emails per call: say "emails per call".
  - If no unit is available, say "units per API call".
  - NEVER write "workload_factor", "factor de capacidad", or "capacity_request_factor" in your answer.

**2. Label CRF scenarios as worst / typical / best case — not as equivalent options.**
- When the tool returns multiple results keyed by different capacity_request_factor values:
  - Lowest CRF → worst case (minimum batch size, most requests needed, slowest)
  - Middle CRF → typical / representative case
  - Highest CRF → best case (maximum batch size, fewest requests, fastest)
- Present them in that order with those labels using a bullet list or table.

**3. Identify the binding constraint.**
- When results span multiple capacity_units, name which one exhausts first — that is the real bottleneck.
  For example: "The daily email quota (200/day) is the binding constraint, not the per-minute rate."

**4. End with a follow-up question when plan and/or CRF are still unknown.**
- If results span multiple plans (no plan_name was specified) and/or multiple CRF scenarios
  (no capacity_request_factor was specified), close with ONE question that covers both at once.
- The UI provides interactive fields; do NOT suggest typing keywords like "por defecto".
- When a nav crf_ranges result is available, reference the actual range.
- Example (both unknown): "¿Quieres acotar los resultados a un plan concreto o a un número de [unidad] por llamada?"
- Example (only CRF unknown): "¿Cuántos [unidad] envías por llamada normalmente? El rango habitual es [min]–[max]."
- Never ask this question if the user already specified a plan or a value.
- If the result contains data for only ONE plan, do NOT suggest trying "another plan" — there is no other plan.

**4b. CRF matching against tool results — check per dimension.**
- When the user explicitly provided a CRF value, inspect the tool results for a row where
  `capacity_request_factor` equals that value.
- If the CRF IS present in the results for a dimension: present ONLY those rows for that dimension.
  Do NOT mention other scenarios, do NOT say it is "not predefined" or "not a pre-defined scenario."
  Just answer using those results directly.
- If the CRF is NOT present in the results for a dimension: state clearly that the exact value is not
  a predefined scenario for that dimension, list the available scenarios matter-of-factly, and let
  the user decide — do NOT ask them to choose again.
- When the user specified multiple CRF values for different dimensions (e.g. "1 email per call and
  0.256 MB per call"), apply this check independently per dimension: a dimension where the CRF
  matches gets the direct answer; a dimension where it does not gets the "not predefined" note.

**5. Overage cost — scan ALL quota dimensions, not just the one the user mentioned.**
- Whenever a quota result contains an `overage_cost` field on any dimension, always surface that
  overage price in your answer — regardless of which capacity_unit the user referred to.
- Multiple dimensions can each carry their own `overage_cost`; report every one that is present.
- A question like "how much overage to reach 40,000 emails?" requires checking every quota in the
  result for an `overage_cost` field, then computing for each: extra units needed × overage price.
- Never say "overage cost is not specified" when it is present on any quota in the result.

**5b. Alias mentions — suppress when absent.**
- Only mention endpoint aliases if the `alias` field was non-null in the tool result. Do not invent
  aliases or mention them when absent.

**6. Do not round or recalculate tool outputs.**
- Quote exact values from tools. Do not approximate or recompute.
- You MAY convert machine-readable durations (e.g., "86400s") to human-readable form ("1 day") for
  readability, but preserve the original precision.

**7. Multi-plan comparisons.**
- When results cover multiple plans, present all of them — even if some show very long times.
  Let the user draw their own conclusions. Order plans consistently (e.g., by name or quota size).

**8. When no tools were executed (empty plan).**
- Ask exactly one clarifying question that covers the two key dimensions at once: plan and CRF
  (or batch size / units per call).
- The UI provides interactive fields for the user to fill in; do NOT suggest typing special keywords.
- Example: "¿Para qué plan y con cuántos [unidad] por llamada quieres el cálculo?"
- Never ask more than one question per turn.

**9. Partial action errors.**
- When a result entry contains an `"error"` key instead of `"payload"`, the tool call failed for
  that action. Report the failure briefly and continue with any results that did succeed.
- If the error message says a capacity_unit "is not available" or lists available dimensions, tell
  the user in plain language: e.g. "Este datasheet no incluye la dimensión MBs — solo rastrea emails
  y requests." List the available dimensions from the error if present. Do not expose raw error text.

**10. HTML chart handling.**
- If the tool result contains an "html" field, the chart is already rendered in the UI as an
  interactive iframe. Do not reproduce or describe the HTML. Briefly explain what the chart shows
  (inflection points, capacity curve shape, time interval) and invite the user to interact with it.

### Response Format
- Use the user's language (Spanish if they wrote in Spanish).
- **Simple results** (one plan, one CRF, one number): answer in one or two natural sentences. Do NOT use bullet lists when the answer fits in a sentence. Do NOT echo back information the user already provided (plan name, unit, CRF) — just state the result.
- **Complex results** (multiple plans, multiple scenarios, or comparison): use Markdown bold headers for plan names, bullet lists for scenarios, bold for key figures.
- Close with the follow-up question when CRF is unknown (rule 4). When no tools ran, ask one clarifying question (rule 8).
"""

ANSWER_CLARIFICATION_PROMPT = """Additional answer rules (apply ONLY when Plan.response_mode is "clarify"):
- Do NOT answer the original capacity question yet.
- Use nav results to ask a short, grounded follow-up that helps the user provide the missing selector(s).
- Ask ONLY about the fields listed in clarification_fields. Do NOT ask about any other field
  (e.g. do NOT spontaneously ask for CRF / units per call if it is not in clarification_fields).
- If a nav result for plan_name returns exactly ONE plan, treat that plan as already selected —
  do NOT ask the user to confirm or choose it. Proceed as if plan_name is resolved and ask only
  about the remaining clarification_fields (if any). If there are none left, answer directly.
- If a nav result for capacity_unit returns exactly ONE unit, treat it as already selected similarly.
- Prefer one natural message. Ask in this order when relevant: plan -> endpoint -> alias -> capacity unit -> units per call.
- Do NOT enumerate plan names, endpoint paths, aliases, or capacity units in your follow-up question — the UI already shows all available options as interactive dropdowns. Mentioning them in text is redundant.
- If CRF ranges are available from nav results, state the actual min–max values from the result
  and ask the user what they send per call. NEVER output literal bracket placeholders like [min],
  [max], or [unidad] — always fill in real values from the nav result.
- If nav_crf_ranges returns no ranges (empty list), or was not called, the datasheet has no workload
  dimension — do NOT ask for CRF / units per call at all. Proceed without it.
- Do NOT suggest typing "por defecto" or any special keyword.
- Do not describe worst/typical/best scenarios yet.
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

    async def handle_question(
        self,
        question: str,
        datasheet_contents: Optional[List[str]] = None,
        datasheet_urls: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        force_chart: bool = False,
    ) -> Dict[str, Any]:
        provided_datasheets = [content for content in (datasheet_contents or []) if content]
        datasheet_alias_map = self._build_datasheet_alias_map(provided_datasheets)
        provided_urls = [url for url in (datasheet_urls or []) if url]

        plan, plan_usage = await self._generate_plan(
            question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=provided_urls,
            history=history,
            force_chart=force_chart,
        )

        plan = self._apply_clarification_fallback(
            plan=plan,
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=provided_urls,
            history=history,
        )

        plan = self._budget_tool_override(
            plan=plan,
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=provided_urls,
            history=history,
        )

        plan = self._inject_multi_crf_into_plan(
            plan=plan,
            question=question,
            history=history,
        )

        actions = self._normalize_actions(plan.get("actions"))
        if datasheet_alias_map or provided_urls:
            actions = self._remap_standalone_to_datasheet(
                actions=actions,
                datasheet_alias_map=datasheet_alias_map,
                datasheet_urls=provided_urls,
            )

        # Whether a chart could be produced for this question (independent of
        # whether we actually generate it now). Used by the UI to offer "generate
        # a chart?" in ask mode.
        chart_available = any(a.name in CHART_CAPABLE_ACTIONS for a in actions)

        # Did the user explicitly ask to visualise? The planner only picks a
        # chart tool (capacity_curve_inflection / *_chart) when the question asks
        # for a graph. In that case we never ask again — generate it now.
        explicit_chart_request = any(
            a.name in CHART_ONLY_ACTIONS or a.name in set(TO_CHART_VARIANT.values())
            for a in actions
        )

        if force_chart or explicit_chart_request:
            # Generate the chart now: upgrade budget/demand to their chart variant,
            # and add an inflection capacity-curve for BoundedRate/datasheet
            # capacity questions that have no chart of their own.
            actions = self._remap_to_chart(actions)
            actions = self._ensure_capacity_curve(
                actions, has_datasheet=bool(datasheet_alias_map or provided_urls)
            )
        else:
            # "Ask" mode and no explicit chart request: do NOT spend time
            # generating a chart — suppress chart tools so the text answer comes
            # back fast. The UI asks first and re-requests with force_chart=true
            # only if the user confirms.
            actions = self._suppress_charts(actions)

        results, last_payload = await self._execute_actions(
            actions=actions,
            datasheet_alias_map=datasheet_alias_map,
        )

        payload_for_answer, result_payload = self._compose_results_payload(actions, results, last_payload)
        answer, answer_usage = await self._generate_answer(
            question, plan, payload_for_answer, datasheet_alias_map,
            datasheet_urls=provided_urls, history=history,
        )

        total_usage = plan_usage + answer_usage
        return {
            "plan": plan,
            "result": result_payload,
            "answer": answer,
            "chart_available": chart_available,
            "usage": {"input_tokens": total_usage.input_tokens, "output_tokens": total_usage.output_tokens},
        }

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    async def _generate_plan(
        self,
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        force_chart: bool = False,
    ) -> Dict[str, Any]:
    ) -> tuple[Dict[str, Any], LLMUsage]:
        messages = self._build_plan_request_messages(
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=datasheet_urls,
            history=history,
            force_chart=force_chart,
        )

        attempt_errors: List[str] = []
        total_usage = LLMUsage()
        for _ in range(PLAN_REQUEST_MAX_ATTEMPTS):
            attempt_messages: List[ChatMessage] = list(messages)
            if attempt_errors:
                attempt_messages.append({
                    "role": "user",
                    "content": (
                        f"Previous attempt issues: {attempt_errors[-1]}\n"
                        "Return a corrected JSON plan that satisfies all requirements."
                    ),
                })

            try:
                text, usage = await asyncio.to_thread(
                    self._llm.make_full_request,
                    attempt_messages,
                    json_output=True,
                )
                total_usage = total_usage + usage
            except ValueError as exc:
                attempt_errors.append(f"LLM response was not valid JSON: {exc}")
                continue

            try:
                plan = self._parse_plan_text(text=text, question=question)
            except ValueError as exc:
                attempt_errors.append(str(exc))
                continue

            return self._normalise_plan(plan), total_usage

        raise ValueError(
            "Failed to obtain a valid planning response. "
            + (attempt_errors[-1] if attempt_errors else "")
        )

    def _build_plan_request_messages(
        self,
        *,
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        force_chart: bool = False,
    ) -> List[ChatMessage]:
        has_datasheet = bool(datasheet_alias_map or datasheet_urls)
        system_parts = [PLAN_PROMPT, PLAN_RESPONSE_FORMAT_INSTRUCTIONS]
        if force_chart:
            system_parts.append(FORCE_CHART_INSTRUCTION)
        if has_datasheet:
            system_parts.append(PLAN_CLARIFICATION_FORMAT_INSTRUCTIONS)
        if has_datasheet:
            guidance = self._clarification_priority_text(
                question=question,
                datasheet_alias_map=datasheet_alias_map,
                datasheet_urls=datasheet_urls,
                history=history,
            )
            if guidance:
                system_parts.append(guidance)
            demand_recovery = self._demand_intent_recovery_text(
                question=question,
                history=history,
            )
            if demand_recovery:
                system_parts.append(demand_recovery)
            budget_recovery = self._budget_intent_recovery_text(
                question=question,
                history=history,
            )
            if budget_recovery:
                system_parts.append(budget_recovery)

        messages: List[ChatMessage] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]

        self._append_history_messages(messages, history)

        user_parts = [f"Question: {question}"]
        datasheet_ctx = self._datasheet_context_text(datasheet_alias_map)
        if datasheet_ctx:
            user_parts.append(datasheet_ctx)
        url_ctx = self._url_context_text(datasheet_urls)
        if url_ctx:
            user_parts.append(url_ctx)

        # Inline YAML content for the plan so the LLM can inspect it.
        self._append_datasheet_yaml_parts(user_parts, datasheet_alias_map)

        messages.append({"role": "user", "content": "\n\n".join(user_parts)})
        return messages

    def _append_datasheet_yaml_parts(
        self,
        parts: List[str],
        datasheet_alias_map: Dict[str, str],
        chunk_size: int = 4000,
    ) -> None:
        if not datasheet_alias_map:
            return
        parts.append(
            "Uploaded API Datasheet content (full, chunked). Use these aliases as datasheet_source in datasheet actions:"
        )
        for alias, content in datasheet_alias_map.items():
            total_len = len(content or "")
            if not content:
                parts.append(f"{alias}: <empty content>")
                continue
            chunks = [content[i: i + chunk_size] for i in range(0, total_len, chunk_size)]
            total_chunks = len(chunks)
            parts.append(f"{alias}: length={total_len} chars; chunks={total_chunks}")
            for idx, chunk in enumerate(chunks, start=1):
                parts.append(f"YAML[{alias}] chunk {idx}/{total_chunks}:")
                parts.append(chunk)

    def _datasheet_context_text(self, datasheet_alias_map: Dict[str, str]) -> str:
        if not datasheet_alias_map:
            return ""
        aliases = "\n".join(datasheet_alias_map.keys())
        return (
            "API datasheet aliases loaded. Use each alias as datasheet_source "
            "in datasheet_* actions. The full content is resolved at execution time:\n"
            + aliases
        )

    def _url_context_text(self, datasheet_urls: Optional[List[str]]) -> str:
        if not datasheet_urls:
            return ""
        urls = "\n".join(datasheet_urls)
        return (
            "Remote API datasheet URLs. Pass each URL directly as datasheet_source "
            "in datasheet_* actions. Do not modify the URL:\n"
            + urls
        )

    # ------------------------------------------------------------------
    # Answer generation
    # ------------------------------------------------------------------

    async def _generate_answer(
        self,
        question: str,
        plan: Dict[str, Any],
        payload: Dict[str, Any],
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, LLMUsage]:
        system_parts = [ANSWER_PROMPT]
        if plan.get("response_mode") == "clarify":
            system_parts.append(ANSWER_CLARIFICATION_PROMPT)

        messages: List[ChatMessage] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]

        self._append_history_messages(messages, history)

        user_parts = [
            f"Question: {question}",
            f"Plan: {json.dumps(plan, ensure_ascii=False)}",
        ]

        sanitised = self._humanize_durations_in_payload(self._strip_html_from_payload(payload))
        payload_text = json.dumps(sanitised, ensure_ascii=False, separators=(",", ":"))
        chunk_size = 4000
        chunks = [payload_text[i: i + chunk_size] for i in range(0, len(payload_text), chunk_size)] if payload_text != "{}" else ["{}"]
        for index, chunk in enumerate(chunks, start=1):
            user_parts.append(f"Tool payload chunk {index}/{len(chunks)}:\n{chunk}")

        datasheet_ctx = self._datasheet_context_text(datasheet_alias_map)
        if datasheet_ctx:
            user_parts.append(datasheet_ctx)
        url_ctx = self._url_context_text(datasheet_urls)
        if url_ctx:
            user_parts.append(url_ctx)

        messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        response, usage = await asyncio.to_thread(
            self._llm.make_full_request,
            messages,
            json_output=False,
        )
        return response or "No answer could be generated.", usage

    # ------------------------------------------------------------------
    # Clarify mode
    # ------------------------------------------------------------------

    def _normalise_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(plan, dict):
            return {"response_mode": "answer", "actions": []}

        response_mode = plan.get("response_mode")
        if response_mode not in PLAN_RESPONSE_MODES:
            response_mode = "answer"

        clarification_fields: List[str] = []
        raw_fields = plan.get("clarification_fields")
        if isinstance(raw_fields, list):
            for field in raw_fields:
                if isinstance(field, str) and field in CLARIFICATION_FIELDS and field not in clarification_fields:
                    clarification_fields.append(field)

        normalised: Dict[str, Any] = {
            "response_mode": response_mode,
            "actions": plan.get("actions", []),
        }
        if clarification_fields:
            normalised["clarification_fields"] = clarification_fields
        return normalised

    def _apply_clarification_fallback(
        self,
        *,
        plan: Dict[str, Any],
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        normalised_plan = self._normalise_plan(plan)
        if normalised_plan.get("response_mode") == "clarify":
            clarification_fields: List[str] = list(normalised_plan.get("clarification_fields") or [])
            for field in self._infer_missing_clarification_fields(
                question=question,
                datasheet_alias_map=datasheet_alias_map,
                datasheet_urls=datasheet_urls,
                history=history,
            ):
                if field not in clarification_fields:
                    clarification_fields.append(field)
            if clarification_fields != list(normalised_plan.get("clarification_fields") or []):
                normalised_plan = {**normalised_plan, "clarification_fields": clarification_fields}
            if clarification_fields:
                existing_actions = self._normalize_actions(normalised_plan.get("actions"))
                datasheet_source = self._resolve_single_datasheet_source(
                    datasheet_alias_map=datasheet_alias_map,
                    datasheet_urls=datasheet_urls,
                    actions=existing_actions,
                )
                if datasheet_source:
                    nav_actions = self._build_clarification_nav_actions(
                        datasheet_source=datasheet_source,
                        missing_fields=clarification_fields,
                        actions=existing_actions,
                    )
                    if nav_actions:
                        normalised_plan = {**normalised_plan, "actions": nav_actions}
            return normalised_plan

        missing_fields = self._infer_missing_clarification_fields(
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=datasheet_urls,
            history=history,
        )
        if not missing_fields:
            return normalised_plan

        actions = self._normalize_actions(normalised_plan.get("actions"))
        datasheet_source = self._resolve_single_datasheet_source(
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=datasheet_urls,
            actions=actions,
        )
        if not datasheet_source:
            return normalised_plan

        fallback_actions = self._build_clarification_nav_actions(
            datasheet_source=datasheet_source,
            missing_fields=missing_fields,
            actions=actions,
        )
        if not fallback_actions:
            return normalised_plan

        return {
            "response_mode": "clarify",
            "clarification_fields": missing_fields,
            "actions": fallback_actions,
        }

    def _infer_missing_clarification_fields(
        self,
        *,
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
    ) -> List[str]:
        if not self._has_single_datasheet_context(datasheet_alias_map, datasheet_urls):
            return []
        if not self._looks_like_capacity_question(question):
            return []

        fields: List[str] = []
        if self._should_clarify_plan(question, history):
            plan_count = self._datasheet_plan_count(datasheet_alias_map)
            if plan_count is None or plan_count > 1:
                fields.append("plan_name")
        if self._should_clarify_capacity_request_factor(question, history):
            if self._looks_like_budget_question(question):
                # Budget tool uses CRF for time_to_capacity even when unit already matches — always ask.
                fields.append("capacity_request_factor")
            elif datasheet_urls and not datasheet_alias_map:
                # URL-only datasheet: content unknown at plan time, assume CRF may be present.
                fields.append("capacity_request_factor")
            elif self._datasheet_has_crf(datasheet_alias_map):
                fields.append("capacity_request_factor")
        return fields

    def _datasheet_has_crf(self, datasheet_alias_map: Dict[str, str]) -> bool:
        """Returns True when at least one uploaded datasheet defines CRF ranges."""
        crf_markers = ("capacity_request_factor", "crf_ranges", "crf:", "workload:")
        for content in datasheet_alias_map.values():
            if not content:
                continue
            lowered = content.lower()
            if any(marker in lowered for marker in crf_markers):
                return True
        return False

    @staticmethod
    def _datasheet_plan_count(datasheet_alias_map: Dict[str, str]) -> Optional[int]:
        """Returns the number of plans defined in the first parseable uploaded datasheet YAML."""
        import yaml as _yaml  # local import — avoid top-level dependency at module level
        for content in datasheet_alias_map.values():
            if not content:
                continue
            try:
                parsed = _yaml.safe_load(content)
                if isinstance(parsed, dict) and isinstance(parsed.get("plans"), dict):
                    return len(parsed["plans"])
            except Exception:
                pass
        return None

    def _clarification_priority_text(
        self,
        *,
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        fields = self._infer_missing_clarification_fields(
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=datasheet_urls,
            history=history,
        )
        if not fields:
            return ""
        return (
            "Clarification priority: ask a follow-up before running calc tools if the plan would otherwise be imprecise.\n"
            "Likely missing selectors for this turn: " + ", ".join(fields)
        )

    def _demand_intent_recovery_text(
        self,
        *,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        if not history:
            return ""
        if self._looks_like_demand_question(question):
            return ""
        original_demand: Optional[str] = None
        for item in history:
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content", "")
                if isinstance(content, str) and self._looks_like_demand_question(content):
                    original_demand = content
                    break
        if not original_demand:
            return ""
        return (
            f"CRITICAL — demand intent recovery: the user's original question was a "
            f"demand/compatibility check: \"{original_demand[:150]}\". "
            "The current message is a clarification reply providing plan and/or CRF. "
            "You MUST use demand_evaluation (NEVER datasheet_limits, datasheet_rates, or datasheet_quotas). "
            "Build the demands array from the ORIGINAL question values: "
            "extract the rate (value + unit + period) and quota (value + unit + period) literally from that question. "
            "The demands array MUST contain at least one object with a 'rate' and/or 'quota' field — "
            "never send a demand with only 'demand_crf' or 'duration' and no rate/quota. "
            "Apply the clarification values (plan_name, capacity_request_factor) as top-level action parameters."
        )

    def _budget_intent_recovery_text(
        self,
        *,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        is_current_budget = self._looks_like_budget_question(question)
        original_budget: Optional[str] = None
        if history:
            for item in history:
                if isinstance(item, dict) and item.get("role") == "user":
                    content = item.get("content", "")
                    if isinstance(content, str) and self._looks_like_budget_question(content):
                        original_budget = content
                        break
        if not original_budget and not is_current_budget:
            return ""
        if is_current_budget:
            return (
                "CRITICAL — budget tool enforcement: the current question is about plan cost or budget. "
                "You MUST use budget_recommendation (or budget_recommendation_chart). "
                "NEVER use datasheet_limits, datasheet_rates, or datasheet_quotas for budget/cost questions. "
                "Required params: desired_capacity (number), capacity_unit (string). "
                "Optional: no_overage=true for 'no overages' constraint, max_budget for a spending cap, "
                "capacity_request_factor for batch size."
            )
        return (
            f"CRITICAL — budget intent recovery: the user's original question was a "
            f"budget/cost recommendation: \"{original_budget[:150]}\". "
            "The current message is a follow-up or refinement to that budget question. "
            "You MUST use budget_recommendation (NEVER datasheet_limits, datasheet_rates, or datasheet_quotas). "
            "Pass desired_capacity and capacity_unit from the original question context. "
            "Apply any new constraints from the current message: no_overage=true if user wants no overages, "
            "max_budget if a spending cap is mentioned, capacity_request_factor and plan_name from prior answers."
        )

    def _build_clarification_nav_actions(
        self,
        *,
        datasheet_source: str,
        missing_fields: List[str],
        actions: List[PlannedAction],
    ) -> List[Dict[str, Any]]:
        known_plan = self._first_known_param(actions, "plan_name")
        known_endpoint = self._first_known_param(actions, "endpoint_path")
        nav_actions: List[Dict[str, Any]] = []

        def add_action(name: str, **params: Any) -> None:
            action: Dict[str, Any] = {"name": name, "datasheet_source": datasheet_source}
            for key, value in params.items():
                if value is not None:
                    action[key] = value
            if action not in nav_actions:
                nav_actions.append(action)

        if "plan_name" in missing_fields:
            add_action("datasheet_nav_plans")
        if "endpoint_path" in missing_fields:
            add_action("datasheet_nav_endpoints", plan_name=known_plan)
        if "capacity_unit" in missing_fields:
            add_action("datasheet_nav_capacity_units", plan_name=known_plan, endpoint_path=known_endpoint)
        if "alias" in missing_fields:
            add_action("datasheet_nav_aliases", plan_name=known_plan, endpoint_path=known_endpoint)
        if "capacity_request_factor" in missing_fields:
            add_action("datasheet_nav_capacity_units", plan_name=known_plan, endpoint_path=known_endpoint)
            add_action("datasheet_nav_crf_ranges", plan_name=known_plan, endpoint_path=known_endpoint)
        return nav_actions

    def _resolve_single_datasheet_source(
        self,
        *,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        actions: List[PlannedAction],
    ) -> Optional[str]:
        explicit_sources = self._deduplicate([
            str(source)
            for source in (
                (action.params or {}).get("datasheet_source") for action in actions
            )
            if source
        ])
        if len(explicit_sources) == 1:
            return explicit_sources[0]

        all_sources = self._all_datasheet_sources(datasheet_alias_map, datasheet_urls)
        if len(all_sources) == 1:
            return all_sources[0]
        return None

    def _all_datasheet_sources(
        self,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
    ) -> List[str]:
        return self._deduplicate(list(datasheet_alias_map.keys()) + list(datasheet_urls or []))

    def _has_single_datasheet_context(
        self,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
    ) -> bool:
        return len(self._all_datasheet_sources(datasheet_alias_map, datasheet_urls)) == 1

    def _first_known_param(self, actions: List[PlannedAction], key: str) -> Optional[str]:
        for action in actions:
            value = (action.params or {}).get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _should_clarify_plan(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        if self._looks_like_reply_to_assistant_prompt(question, history, expected="plan"):
            return False
        if self._history_mentions_plan(history):
            return False
        if self._history_mentions_cross_plan(history):
            return False
        if self._asks_for_cross_plan_answer(question) or self._asks_for_plan_recommendation(question):
            return False
        if self._mentions_plan_explicitly(question):
            return False
        if self._looks_like_budget_question(question):
            return False
        return True

    def _should_clarify_capacity_request_factor(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        if self._looks_like_reply_to_assistant_prompt(question, history, expected="capacity_request_factor"):
            return False
        if self._history_mentions_capacity_request_factor(history):
            return False
        if self._mentions_batch_size(question):
            return False
        return True

    def _history_mentions_plan(self, history: Optional[List[Dict[str, str]]]) -> bool:
        return self._history_contains_user_signal(
            history,
            lambda content: self._mentions_plan_explicitly(content),
            expected="plan",
        )

    def _history_mentions_capacity_request_factor(
        self,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        return self._history_contains_user_signal(
            history,
            lambda content: self._mentions_batch_size(content),
            expected="capacity_request_factor",
        )

    def _history_mentions_cross_plan(
        self,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        return self._history_contains_user_signal(
            history,
            lambda content: self._asks_for_cross_plan_answer(content),
            expected="plan",
        )

    def _history_contains_user_signal(
        self,
        history: Optional[List[Dict[str, str]]],
        predicate: Any,
        *,
        expected: str,
    ) -> bool:
        if not history:
            return False
        for index, item in enumerate(history):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if predicate(content):
                return True
            previous = history[index - 1] if index > 0 else None
            if (
                isinstance(previous, dict)
                and previous.get("role") == "assistant"
                and self._is_reply_to_assistant_prompt(
                    content,
                    previous.get("content", ""),
                    expected=expected,
                )
            ):
                return True
        return False

    def _looks_like_capacity_question(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            "cuanto", "cuantos", "cuanta", "cuantas", "cuando",
            "how many", "how much", "how long", "when",
            "puedo mandar", "puedo enviar", "can i send", "can i make",
            "emails", "correos", "requests", "peticiones",
            "capacity", "capacidad", "throughput",
            "tardo", "cuota", "quota", "limite", "límite", "limit",
            "gasto", "agoto", "exhaust", "alcanzar", "llegar", "procesar",
            "tiempo", "time",
        )
        return any(pattern in lowered for pattern in patterns)

    def _looks_like_demand_question(self, text: str) -> bool:
        """Returns True when the question describes a demand pattern to evaluate against limits.
        These questions provide rate/quota explicitly — no clarification needed."""
        lowered = text.lower()
        explicit_patterns = (
            "puedo mantener", "puedo sostener", "can i maintain", "can i sustain",
            "es compatible", "fits within", "is compatible",
            "aguanta", "soporta", "handles", "supports",
            "es posible con", "es factible con", "is it possible",
        )
        if any(p in lowered for p in explicit_patterns):
            return True
        # Also detect: question with both an explicit rate unit AND a quota/daily unit
        has_rate_unit = any(u in lowered for u in (
            "rps", "rpm", "req/s", "/segundo", "/minuto",
            "por segundo", "por minuto", "per second", "per minute",
        ))
        has_quota_unit = any(u in lowered for u in (
            "/día", "/dia", "por día", "por dia", "per day",
            "diario", "diaria", "mensual", "monthly", "/mes", "/month",
        ))
        return has_rate_unit and has_quota_unit

    def _looks_like_info_question(self, text: str) -> bool:
        """Returns True for questions asking about rates/quotas/limits info.
        These never need CRF clarification — the tool returns plan limits directly."""
        lowered = text.lower()
        patterns = (
            "velocidad máxima", "velocidad maxima", "máxima velocidad", "maxima velocidad",
            "tasa máxima", "tasa maxima", "maximum rate", "max rate",
            "cuánto aguanta", "cuanto aguanta",
            "qué límites", "que límites", "qué limites", "que limites",
            "what limits", "what are the limits",
            "cuánta cuota", "cuanta cuota", "how much quota",
            "qué planes", "que planes", "what plans", "list plans",
            "qué endpoints", "que endpoints",
            "qué restricciones", "que restricciones", "what restrictions",
            "cuáles son los límites", "cuales son los limites",
        )
        return any(p in lowered for p in patterns)

    def _looks_like_budget_question(self, text: str) -> bool:
        """Returns True for budget/recommendation questions.
        Plan is the OUTPUT of the tool, not an input — never ask for plan clarification."""
        lowered = text.lower()
        patterns = (
            "qué plan me conviene", "que plan me conviene",
            "which plan", "cheapest", "más barato", "mas barato",
            "más económico", "mas economico", "más económica", "mas economica",
            "opción más barata", "opcion mas barata", "cheapest option",
            "mejor plan", "best plan",
            "presupuesto", "budget",
            "me recomiendas", "recomiéndame", "recomiendame", "recommend",
            "cuánto cuesta", "cuanto cuesta", "how much does it cost",
            "me sale más barato", "me sale mas barato",
            "opción más económica", "opcion mas economica",
            "sin overage", "sin overages", "no overage", "without overage",
            "evitar overage", "avoid overage",
            "no quiero pagar overage", "no quiero pagar overages",
            "no quisiera pagar overage", "no quisiera pagar overages",
            "no quiero overages", "no quisiera overages",
            "sin sobrecargo", "evitar sobrecargo",
            "menor precio", "precio más bajo", "precio mas bajo",
            "menor costo", "costo más bajo", "costo mas bajo",
            "precio posible", "lowest price", "minimum cost",
            "con overage", "con overages", "con sobrecargo",
            "incluyendo overage", "incluyendo overages",
        )
        return any(p in lowered for p in patterns)

    @staticmethod
    def _extract_desired_capacity(text: str) -> Tuple[Optional[float], Optional[str]]:
        pattern = re.compile(
            r'(\d{1,3}(?:[.,]\d{3})*|\d{4,})\s*([kK])?\s*'
            r'(emails?|correos?|requests?|peticiones?|messages?|mensajes?)',
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None, None
        num_str = re.sub(r'[.,]', '', match.group(1))
        try:
            value = float(num_str)
        except ValueError:
            return None, None
        if match.group(2):
            value *= 1000
        unit_raw = match.group(3).lower()
        if any(u in unit_raw for u in ('email', 'correo', 'message', 'mensaje')):
            return value, 'emails'
        if any(u in unit_raw for u in ('request', 'peticion', 'petición')):
            return value, 'requests'
        return value, unit_raw

    @staticmethod
    def _has_no_overage_expression(text: str) -> bool:
        lowered = text.lower()
        if 'overage' not in lowered and 'sobrecargo' not in lowered:
            return False
        return any(neg in lowered for neg in (
            'sin ', 'evitar', 'avoid', 'without',
            'no quiero', 'no quisiera', 'no pagar',
            'no overage', 'no overages', 'no sobrecargo',
        ))

    @staticmethod
    def _has_affirmative_overage_expression(text: str) -> bool:
        lowered = text.lower()
        if 'overage' not in lowered and 'sobrecargo' not in lowered:
            return False
        return any(pos in lowered for pos in (
            'con overage', 'con overages', 'con sobrecargo',
            'incluyendo overage', 'incluyendo overages',
            'incluyera el overage', 'incluyera overage',
            'incluir overage', 'si incluyo', 'si incluyera',
        ))

    def _extract_no_overage_intent(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        if self._has_affirmative_overage_expression(question):
            return False
        if self._has_no_overage_expression(question):
            return True
        if history:
            for item in reversed(history):
                if isinstance(item, dict) and item.get("role") == "user":
                    content = item.get("content", "")
                    if not isinstance(content, str):
                        continue
                    if self._has_affirmative_overage_expression(content):
                        return False
                    if self._has_no_overage_expression(content):
                        return True
        return False

    def _extract_crf_from_context(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Optional[float]:
        crf_re = re.compile(
            r'(?:crf|capacity\s+request\s+factor)\s*(?:de\s+|=\s*|:\s*)?(\d+(?:[.,]\d+)?)',
            re.IGNORECASE,
        )
        per_call_re = re.compile(
            r'(\d+(?:[.,]\d+)?)\s+(?:emails?|correos?|requests?|peticiones?)?\s*'
            r'(?:por\s+llamada|por\s+petici[oó]n|per\s+(?:call|request))',
            re.IGNORECASE,
        )

        def _extract(text: str) -> Optional[float]:
            m = crf_re.search(text)
            if m:
                return float(m.group(1).replace(',', '.'))
            m = per_call_re.search(text)
            if m:
                return float(m.group(1).replace(',', '.'))
            return None

        crf = _extract(question)
        if crf is not None:
            return crf
        if history:
            for item in reversed(history):
                if isinstance(item, dict) and item.get("role") == "user":
                    content = item.get("content", "")
                    if isinstance(content, str):
                        crf = _extract(content)
                        if crf is not None:
                            return crf
        return None

    def _is_budget_clarification_reply(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        if not history:
            return False
        latest_assistant = next(
            (item.get("content", "") for item in reversed(history)
             if isinstance(item, dict) and item.get("role") == "assistant"),
            "",
        )
        if not isinstance(latest_assistant, str) or not latest_assistant.strip():
            return False
        la_lower = latest_assistant.lower()
        asked_for_context = "plan" in la_lower and any(kw in la_lower for kw in (
            "qué plan", "que plan", "cuántos", "cuantos",
            "por llamada", "per call", "qué planes", "que planes",
        ))
        if not asked_for_context:
            return False
        for item in history:
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content", "")
                if isinstance(content, str) and self._looks_like_budget_question(content):
                    return True
        return False

    def _budget_tool_override(
        self,
        *,
        plan: Dict[str, Any],
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        if plan.get("response_mode") == "clarify":
            return plan

        is_budget = self._looks_like_budget_question(question)
        original_budget_question: Optional[str] = None
        if history:
            for item in history:
                if isinstance(item, dict) and item.get("role") == "user":
                    content = item.get("content", "")
                    if isinstance(content, str) and self._looks_like_budget_question(content):
                        original_budget_question = content
                        break

        if not is_budget and not original_budget_question:
            return plan

        actions = self._normalize_actions(plan.get("actions"))
        wrong_actions = [
            a for a in actions
            if a.name in {"datasheet_quotas", "datasheet_rates", "datasheet_limits"}
        ]
        budget_actions = [a for a in actions if a.name in BUDGET_ACTIONS]

        if not wrong_actions or budget_actions:
            return plan

        if not is_budget:
            has_new_capacity = self._extract_desired_capacity(question)[0] is not None
            is_no_overage_now = self._has_no_overage_expression(question)
            is_clarification_reply = self._is_budget_clarification_reply(question, history)
            if not has_new_capacity and not is_no_overage_now and not is_clarification_reply:
                return plan

        desired_capacity, capacity_unit = self._extract_desired_capacity(question)
        if desired_capacity is None and original_budget_question:
            desired_capacity, capacity_unit = self._extract_desired_capacity(original_budget_question)
        if desired_capacity is None and history:
            for item in history:
                if isinstance(item, dict) and item.get("role") == "user":
                    content = item.get("content", "")
                    if isinstance(content, str):
                        desired_capacity, capacity_unit = self._extract_desired_capacity(content)
                        if desired_capacity is not None:
                            break

        if desired_capacity is None or capacity_unit is None:
            logger.warning("harvey.agent.budget_override_skip", question=question[:100])
            return plan

        ds_source = next(
            (str(a.params["datasheet_source"]) for a in wrong_actions
             if a.params and a.params.get("datasheet_source")),
            None,
        )
        if not ds_source:
            all_sources = self._all_datasheet_sources(datasheet_alias_map, datasheet_urls)
            ds_source = all_sources[0] if all_sources else None
        if not ds_source:
            return plan

        no_overage = self._extract_no_overage_intent(question, history)
        crf = self._extract_crf_from_context(question, history)

        new_action: Dict[str, Any] = {
            "name": "budget_recommendation",
            "datasheet_source": ds_source,
            "desired_capacity": desired_capacity,
            "capacity_unit": capacity_unit,
        }
        if no_overage:
            new_action["no_overage"] = True
        if crf is not None:
            new_action["capacity_request_factor"] = crf

        logger.info(
            "harvey.agent.budget_tool_override",
            from_tool=wrong_actions[0].name,
            desired_capacity=desired_capacity,
            capacity_unit=capacity_unit,
            no_overage=no_overage,
            crf=crf,
        )
        return {**plan, "actions": [new_action]}

    # unit synonyms → canonical datasheet unit name
    _UNIT_SYNONYMS: Dict[str, str] = {
        "email": "emails", "emails": "emails",
        "correo": "emails", "correos": "emails",
        "message": "emails", "messages": "emails",
        "mensaje": "emails", "mensajes": "emails",
        "mb": "MBs", "mbs": "MBs",
        "megabyte": "MBs", "megabytes": "MBs",
        "request": "requests", "requests": "requests",
        "peticion": "requests", "peticiones": "requests",
        "petición": "requests",
        "token": "tokens", "tokens": "tokens",
        "credit": "credits", "credits": "credits",
        "image": "images", "images": "images",
        "call": "calls", "calls": "calls",
    }

    _MULTI_CRF_RE = re.compile(
        r'(\d+(?:[.,]\d+)?)\s+'
        r'(emails?|correos?|[Mm][Bb]s?|megabytes?|requests?|petici[oó]nes?|messages?|mensajes?'
        r'|tokens?|credits?|images?|calls?|units?)',
        re.IGNORECASE,
    )

    def _extract_multi_crf_dict(self, text: str) -> Optional[Dict[str, float]]:
        matches = self._MULTI_CRF_RE.findall(text)
        if len(matches) < 2:
            return None
        result: Dict[str, float] = {}
        for num_str, unit in matches:
            try:
                value = float(num_str.replace(",", "."))
            except ValueError:
                continue
            canonical = self._UNIT_SYNONYMS.get(unit.lower(), unit)
            result[canonical] = value
        return result if len(result) >= 2 else None

    def _inject_multi_crf_into_plan(
        self,
        plan: Dict[str, Any],
        question: str,
        history: Optional[list],
    ) -> Dict[str, Any]:
        """
        When user specified multi-dimensional CRF (e.g. '1 email y 0.256 MB') but the planner
        omitted capacity_request_factor from DATASHEET_ACTION entries, inject it here so Prime4API
        returns results for the exact user-specified values instead of all predefined scenarios.
        """
        actions = plan.get("actions")
        if not isinstance(actions, list) or not actions:
            return plan

        multi_crf = self._extract_multi_crf_dict(question)
        if not multi_crf and history:
            for item in reversed(history):
                if isinstance(item, dict) and item.get("role") == "user":
                    content = item.get("content", "")
                    if isinstance(content, str):
                        multi_crf = self._extract_multi_crf_dict(content)
                        if multi_crf:
                            break
        if not multi_crf:
            return plan

        crf_json = json.dumps(multi_crf, separators=(",", ":"))
        new_actions = []
        modified = False
        for action in actions:
            if (
                isinstance(action, dict)
                and action.get("name") in DATASHEET_ACTIONS
                and action.get("capacity_request_factor") is None
            ):
                action = {**action, "capacity_request_factor": crf_json}
                modified = True
            new_actions.append(action)

        if modified:
            logger.info("harvey.agent.multi_crf_injected", crf=crf_json)
            return {**plan, "actions": new_actions}
        return plan

    def _asks_for_cross_plan_answer(self, text: str) -> bool:
        lowered = text.lower()
        patterns = ("todos los planes", "all plans", "across plans", "compar", "vs ", "versus", "entre planes")
        return any(pattern in lowered for pattern in patterns)

    def _asks_for_plan_recommendation(self, text: str) -> bool:
        lowered = text.lower()
        patterns = ("que plan", "qué plan", "which plan", "best plan", "me conviene", "recomiendas", "recommend")
        return any(pattern in lowered for pattern in patterns)

    def _mentions_plan_explicitly(self, text: str) -> bool:
        lowered = text.lower()
        patterns = ("plan ", "plan:", "en el plan", "del plan")
        return any(pattern in lowered for pattern in patterns)

    def _mentions_batch_size(self, text: str) -> bool:
        lowered = text.lower()
        call_patterns = (
            "por llamada", "por peticion", "por petición",
            "per call", "per request", "cada llamada", "each request",
        )
        has_per_call = any(pattern in lowered for pattern in call_patterns)
        has_number = bool(re.search(r"\b\d+(?:[.,]\d+)?\b", lowered))
        if has_per_call and has_number:
            return True
        crf_patterns = ("crf", "capacity request factor", "batch size")
        return any(pattern in lowered for pattern in crf_patterns) and has_number

    def _looks_like_reply_to_assistant_prompt(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
        *,
        expected: str,
    ) -> bool:
        if not history:
            return False
        latest_assistant = next(
            (
                item.get("content", "")
                for item in reversed(history)
                if isinstance(item, dict) and item.get("role") == "assistant"
            ),
            "",
        )
        if not isinstance(latest_assistant, str) or not latest_assistant.strip():
            return False
        question_word_count = len(question.strip().split())
        if question_word_count == 0:
            return False
        return self._is_reply_to_assistant_prompt(question, latest_assistant, expected=expected)

    def _is_reply_to_assistant_prompt(
        self,
        question: str,
        assistant_message: str,
        *,
        expected: str,
    ) -> bool:
        if not isinstance(assistant_message, str) or not assistant_message.strip():
            return False
        question_word_count = len(question.strip().split())
        if question_word_count == 0:
            return False
        latest_lowered = assistant_message.lower()
        question_lowered = question.lower()
        if expected == "plan":
            return "plan" in latest_lowered and question_word_count <= SHORT_REPLY_MAX_WORDS
        if expected == "capacity_request_factor":
            if not any(
                pattern in latest_lowered
                for pattern in ("por llamada", "por petición", "por peticion", "per call", "per request")
            ):
                return False
            return self._mentions_batch_size(question_lowered) or question_word_count <= SHORT_REPLY_MAX_WORDS
        return False

    # ------------------------------------------------------------------
    # Action parsing / normalisation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Demand normalization helpers
    # ------------------------------------------------------------------

    _PERIOD_UNIT_MAP: Dict[str, str] = {
        "SECOND": "s", "SECONDS": "s",
        "MINUTE": "min", "MINUTES": "min",
        "HOUR": "h", "HOURS": "h",
        "DAY": "day", "DAYS": "day",
        "WEEK": "week", "WEEKS": "week",
        "MONTH": "month", "MONTHS": "month",
        "YEAR": "year", "YEARS": "year",
    }

    @classmethod
    def _normalize_period(cls, period: Any) -> Any:
        if not isinstance(period, dict):
            return period
        value = period.get("value", 1)
        unit = str(period.get("unit", "")).upper()
        suffix = cls._PERIOD_UNIT_MAP.get(unit, unit.lower())
        return f"{value}{suffix}"

    @classmethod
    def _normalize_rate_or_quota_obj(cls, obj: Any) -> Any:
        if not isinstance(obj, dict):
            return obj
        result = dict(obj)
        if "period" in result:
            result["period"] = cls._normalize_period(result["period"])
        return result

    @classmethod
    def _fix_demand_crf_keys(cls, demand_crf: Any, demand: dict, capacity_unit: Optional[str]) -> Optional[dict]:
        if not isinstance(demand_crf, dict):
            return demand_crf
        # If the key is literally "unit" the LLM used the wrong format: {"unit": N} instead of {"emails": N}
        if set(demand_crf.keys()) == {"unit"}:
            crf_value = demand_crf["unit"]
            # Prefer the explicit capacity_unit, then infer from quota units
            target = capacity_unit
            if not target:
                for q in (demand.get("quota") or []):
                    if isinstance(q, dict):
                        unit = q.get("unit", "")
                        if unit and unit not in ("requests", "unit"):
                            target = unit
                            break
            if target:
                return {target: crf_value}
            # Cannot determine unit — drop demand_crf so capacity_request_factor takes effect
            return None
        return demand_crf

    @classmethod
    def _normalize_demands(cls, demands: Any, capacity_unit: Optional[str] = None) -> Any:
        if not isinstance(demands, list):
            return demands
        normalized = []
        for demand in demands:
            if not isinstance(demand, dict):
                normalized.append(demand)
                continue
            d = dict(demand)
            if "rate" in d:
                d["rate"] = cls._normalize_rate_or_quota_obj(d["rate"])
            if "quota" in d:
                q = d["quota"]
                if isinstance(q, list):
                    d["quota"] = [cls._normalize_rate_or_quota_obj(item) for item in q]
                else:
                    d["quota"] = cls._normalize_rate_or_quota_obj(q)
            if "demand_crf" in d:
                fixed = cls._fix_demand_crf_keys(d["demand_crf"], d, capacity_unit)
                if fixed is None:
                    d.pop("demand_crf")
                else:
                    d["demand_crf"] = fixed
            # Drop demands that have neither rate nor quota — they carry no evaluation data
            if not d.get("rate") and not d.get("quota"):
                logger.warning("harvey.agent.demand_empty", label=d.get("label"))
                continue
            normalized.append(d)
        return normalized

    def _remap_standalone_to_datasheet(
        self,
        *,
        actions: List[PlannedAction],
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
    ) -> List[PlannedAction]:
        all_sources = self._all_datasheet_sources(datasheet_alias_map, datasheet_urls)
        if not all_sources:
            return actions
        datasheet_source = all_sources[0]
        remapped: List[PlannedAction] = []
        for action in actions:
            new_name = STANDALONE_TO_DATASHEET.get(action.name)
            if new_name is None:
                remapped.append(action)
                continue
            logger.warning(
                "harvey.agent.remap_standalone",
                from_tool=action.name,
                to_tool=new_name,
            )
            old_params = action.params or {}
            new_params: Dict[str, Any] = {"datasheet_source": datasheet_source}
            for key in ("plan_name", "endpoint_path", "alias", "capacity_unit", "capacity_request_factor"):
                if old_params.get(key) is not None:
                    new_params[key] = old_params[key]
            for key in ("capacity_goal", "time", "end_instant", "start_instant", "time_interval"):
                if old_params.get(key) is not None:
                    new_params[key] = old_params[key]
            remapped.append(PlannedAction(name=new_name, params=new_params))
        return remapped

    def _remap_to_chart(self, actions: List[PlannedAction]) -> List[PlannedAction]:
        """Swap base actions for their chart-producing variant (force_chart mode)."""
        remapped: List[PlannedAction] = []
        for action in actions:
            new_name = TO_CHART_VARIANT.get(action.name)
            if new_name is None:
                remapped.append(action)
                continue
            logger.info(
                "harvey.agent.force_chart_remap",
                from_tool=action.name,
                to_tool=new_name,
            )
            remapped.append(PlannedAction(name=new_name, params=action.params))
        return remapped

    def _ensure_capacity_curve(
        self, actions: List[PlannedAction], *, has_datasheet: bool
    ) -> List[PlannedAction]:
        """force_chart mode: if no chart action is present but a capacity/consumption
        action is (any BoundedRate or datasheet calc action), append an inflection
        capacity-curve chart derived from its rate/quota (or datasheet params). The
        original action is kept so the text answer (e.g. the consumption time) stays."""
        chart_present = any(
            a.name in CHART_ONLY_ACTIONS or a.name in set(TO_CHART_VARIANT.values())
            for a in actions
        )
        if chart_present:
            return actions

        if has_datasheet:
            ds_actions = [
                a for a in actions
                if a.name in DATASHEET_ACTIONS and (a.params or {}).get("datasheet_source")
            ]
            if not ds_actions:
                return actions
            first = ds_actions[0]
            p = first.params or {}
            new_params: Dict[str, Any] = {
                "datasheet_source": p["datasheet_source"],
                "time_interval": p.get("time_interval", "1day"),
            }
            if p.get("capacity_unit") is not None:
                new_params["capacity_unit"] = p["capacity_unit"]
            if p.get("capacity_request_factor") is not None:
                new_params["capacity_request_factor"] = p["capacity_request_factor"]
            # Several datasheet actions (e.g. one per plan) means a multi-plan
            # question → chart ALL plans by leaving plan_name/endpoint unset. A
            # single action keeps its plan/endpoint scope.
            if len(ds_actions) == 1:
                for key in ("plan_name", "endpoint_path", "alias"):
                    if p.get(key) is not None:
                        new_params[key] = p[key]
            logger.info(
                "harvey.agent.add_capacity_curve",
                variant="datasheet",
                source_tool=first.name,
                datasheet_actions=len(ds_actions),
            )
            return actions + [
                PlannedAction(name="datasheet_capacity_curve_inflection", params=new_params)
            ]

        for a in actions:
            if a.name not in RATE_QUOTA_ACTIONS:
                continue
            p = a.params or {}
            if p.get("rate") is None and p.get("quota") is None:
                continue
            new_params = {"time_interval": p.get("time_interval", "1day")}
            if p.get("rate") is not None:
                new_params["rate"] = p["rate"]
            if p.get("quota") is not None:
                new_params["quota"] = p["quota"]
            logger.info("harvey.agent.add_capacity_curve", variant="standalone", source_tool=a.name)
            return actions + [PlannedAction(name="capacity_curve_inflection", params=new_params)]
        return actions

    def _suppress_charts(self, actions: List[PlannedAction]) -> List[PlannedAction]:
        """Ask mode: avoid generating charts. Downgrade *_chart tools to their text
        variant and drop chart-only tools so the answer returns fast. The chart is
        (re)generated later via force_chart only if the user confirms."""
        suppressed: List[PlannedAction] = []
        for action in actions:
            if action.name in CHART_ONLY_ACTIONS:
                logger.info("harvey.agent.suppress_chart_drop", tool=action.name)
                continue
            base = CHART_TO_BASE.get(action.name)
            if base is not None:
                logger.info(
                    "harvey.agent.suppress_chart_downgrade",
                    from_tool=action.name,
                    to_tool=base,
                )
                suppressed.append(PlannedAction(name=base, params=action.params))
            else:
                suppressed.append(action)
        return suppressed

    def _normalize_actions(self, raw_actions: Any) -> List[PlannedAction]:
        if not isinstance(raw_actions, list):
            return []
        normalized: List[PlannedAction] = []
        for entry in raw_actions:
            action = self._parse_action_entry(entry)
            if action:
                normalized.append(action)
        return normalized

    def _parse_action_entry(self, entry: Any) -> Optional[PlannedAction]:
        if isinstance(entry, str):
            return PlannedAction(name=entry) if entry in API_ACTIONS else None
        if not isinstance(entry, dict):
            return None

        name = entry.get("name")
        if name not in API_ACTIONS:
            logger.warning("harvey.agent.unknown_action", name=name)
            return None

        params: Dict[str, Any] = {}

        if name in NAV_ACTIONS:
            if entry.get("datasheet_source") is not None:
                params["datasheet_source"] = entry["datasheet_source"]
            for key in ("plan_name", "endpoint_path"):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            return PlannedAction(name=name, params=params)

        if name in DATASHEET_ACTIONS:
            if entry.get("datasheet_source") is not None:
                params["datasheet_source"] = entry["datasheet_source"]
            for key in ("plan_name", "endpoint_path", "alias", "capacity_unit"):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            if entry.get("capacity_request_factor") is not None:
                _crf = entry["capacity_request_factor"]
                if isinstance(_crf, dict):
                    params["capacity_request_factor"] = json.dumps(_crf, separators=(",", ":"))
                    if len(_crf) > 1:
                        params.pop("capacity_unit", None)
                else:
                    params["capacity_request_factor"] = _crf
                    try:
                        _parsed_crf = json.loads(_crf) if isinstance(_crf, str) else None
                        if isinstance(_parsed_crf, dict) and len(_parsed_crf) > 1:
                            params.pop("capacity_unit", None)
                    except (json.JSONDecodeError, TypeError):
                        pass
            if name == "datasheet_min_time" and entry.get("capacity_goal") is not None:
                params["capacity_goal"] = entry["capacity_goal"]
            if name == "datasheet_capacity_at" and entry.get("time") is not None:
                params["time"] = entry["time"]
            if name == "datasheet_capacity_curve_inflection" and entry.get("time_interval") is not None:
                params["time_interval"] = entry["time_interval"]
            return PlannedAction(name=name, params=params)

        if name in DEMAND_ACTIONS:
            if entry.get("datasheet_source") is not None:
                params["datasheet_source"] = entry["datasheet_source"]
            if entry.get("demands") is not None:
                params["demands"] = self._normalize_demands(entry["demands"], entry.get("capacity_unit"))
            if entry.get("time_interval") is not None:
                params["time_interval"] = entry["time_interval"]
            for key in ("plan_name", "endpoint_path", "alias", "capacity_unit"):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            if entry.get("capacity_request_factor") is not None:
                _crf = entry["capacity_request_factor"]
                params["capacity_request_factor"] = json.dumps(_crf, separators=(",", ":")) if isinstance(_crf, dict) else _crf
            return PlannedAction(name=name, params=params)

        if name in BUDGET_ACTIONS:
            if entry.get("datasheet_source") is not None:
                params["datasheet_source"] = entry["datasheet_source"]
            if entry.get("desired_capacity") is not None:
                params["desired_capacity"] = entry["desired_capacity"]
            if entry.get("capacity_unit") is not None:
                params["capacity_unit"] = entry["capacity_unit"]
            for key in ("plan_name", "endpoint_path", "alias"):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            if entry.get("max_budget") is not None:
                params["max_budget"] = entry["max_budget"]
            if entry.get("no_overage") is not None:
                params["no_overage"] = entry["no_overage"]
            if entry.get("capacity_request_factor") is not None:
                _crf = entry["capacity_request_factor"]
                params["capacity_request_factor"] = json.dumps(_crf, separators=(",", ":")) if isinstance(_crf, dict) else _crf
            if name == "budget_recommendation_chart" and entry.get("time_horizon") is not None:
                params["time_horizon"] = entry["time_horizon"]
            return PlannedAction(name=name, params=params)

        # Bounded-rate (no datasheet)
        for key in ("rate", "quota"):
            if entry.get(key) is not None:
                params[key] = entry[key]
        if entry.get("capacity_goal") is not None:
            params["capacity_goal"] = entry["capacity_goal"]
        if entry.get("time") is not None:
            params["time"] = entry["time"]
        if entry.get("end_instant") is not None:
            params["end_instant"] = entry["end_instant"]
        if entry.get("start_instant") is not None:
            params["start_instant"] = entry["start_instant"]
        if entry.get("time_interval") is not None:
            params["time_interval"] = entry["time_interval"]
        return PlannedAction(name=name, params=params or None)

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    async def _execute_actions(
        self,
        *,
        actions: List[PlannedAction],
        datasheet_alias_map: Dict[str, str],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not actions:
            return [], None

        results: List[Dict[str, Any]] = []
        last_payload: Optional[Dict[str, Any]] = None

        for index, action in enumerate(actions):
            yaml_content: Optional[str] = None
            if action.name in (DATASHEET_ACTIONS | NAV_ACTIONS | DEMAND_ACTIONS | BUDGET_ACTIONS):
                ds_source = (action.params or {}).get("datasheet_source")
                if ds_source and ds_source in datasheet_alias_map:
                    yaml_content = datasheet_alias_map[ds_source]

            try:
                payload = await self._run_single_action(action=action, yaml_content=yaml_content)
                results.append({"index": index, "action": action.name, "payload": payload})
                last_payload = payload
            except MCPClientError as exc:
                results.append({"index": index, "action": action.name, "error": str(exc)})

        return results, last_payload

    async def _run_single_action(
        self,
        *,
        action: PlannedAction,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        p = action.params or {}

        def _resolve_source() -> Optional[str]:
            source = p.get("datasheet_source")
            if yaml_content is not None and (source is None or not str(source).startswith("http")):
                return yaml_content
            return source

        if action.name in NAV_ACTIONS:
            source = _resolve_source()
            if action.name == "datasheet_nav_plans":
                return await self._workflow.run_datasheet_nav_plans(datasheet_source=source)
            if action.name == "datasheet_nav_endpoints":
                return await self._workflow.run_datasheet_nav_endpoints(
                    datasheet_source=source, plan_name=p.get("plan_name"))
            if action.name == "datasheet_nav_crf_ranges":
                return await self._workflow.run_datasheet_nav_crf_ranges(
                    datasheet_source=source, plan_name=p.get("plan_name"),
                    endpoint_path=p.get("endpoint_path"))
            if action.name == "datasheet_nav_capacity_units":
                return await self._workflow.run_datasheet_nav_capacity_units(
                    datasheet_source=source, plan_name=p.get("plan_name"),
                    endpoint_path=p.get("endpoint_path"))
            if action.name == "datasheet_nav_aliases":
                return await self._workflow.run_datasheet_nav_aliases(
                    datasheet_source=source, plan_name=p.get("plan_name"),
                    endpoint_path=p.get("endpoint_path"))

        if action.name in DATASHEET_ACTIONS:
            source = _resolve_source()
            common = {
                "datasheet_source": source,
                "plan_name": p.get("plan_name"),
                "endpoint_path": p.get("endpoint_path"),
                "alias": p.get("alias"),
                "capacity_unit": p.get("capacity_unit"),
                "capacity_request_factor": p.get("capacity_request_factor"),
            }
            if action.name == "datasheet_min_time":
                return await self._workflow.run_datasheet_min_time(
                    capacity_goal=p.get("capacity_goal", 1), **common)
            if action.name == "datasheet_capacity_at":
                return await self._workflow.run_datasheet_capacity_at(
                    time=p.get("time", "0ms"), **common)
            if action.name == "datasheet_quota_exhaustion_threshold":
                return await self._workflow.run_datasheet_quota_exhaustion_threshold(**common)
            if action.name == "datasheet_idle_time_period":
                return await self._workflow.run_datasheet_idle_time_period(**common)
            if action.name == "datasheet_rates":
                return await self._workflow.run_datasheet_rates(**common)
            if action.name == "datasheet_quotas":
                return await self._workflow.run_datasheet_quotas(**common)
            if action.name == "datasheet_limits":
                return await self._workflow.run_datasheet_limits(**common)
            if action.name == "datasheet_capacity_curve_inflection":
                return await self._workflow.run_datasheet_capacity_curve_inflection(
                    time_interval=p.get("time_interval", "1day"), **common)

        if action.name in DEMAND_ACTIONS:
            source = _resolve_source()
            common_demand = {
                "datasheet_source": source,
                "demands": p.get("demands", []),
                "time_interval": p.get("time_interval", "1month"),
                "plan_name": p.get("plan_name"),
                "endpoint_path": p.get("endpoint_path"),
                "alias": p.get("alias"),
                "capacity_unit": p.get("capacity_unit"),
                "capacity_request_factor": p.get("capacity_request_factor"),
            }
            if action.name == "demand_evaluation":
                return await self._workflow.run_demand_evaluation(**common_demand)
            if action.name == "demand_evaluation_chart":
                return await self._workflow.run_demand_evaluation_chart(**common_demand)

        if action.name in BUDGET_ACTIONS:
            source = _resolve_source()
            common_budget = {
                "datasheet_source": source,
                "desired_capacity": p.get("desired_capacity", 1),
                "capacity_unit": p.get("capacity_unit", "requests"),
                "plan_name": p.get("plan_name"),
                "endpoint_path": p.get("endpoint_path"),
                "alias": p.get("alias"),
                "max_budget": p.get("max_budget"),
                "no_overage": p.get("no_overage", False),
                "capacity_request_factor": p.get("capacity_request_factor"),
            }
            if action.name == "budget_recommendation":
                return await self._workflow.run_budget_recommendation(**common_budget)
            if action.name == "budget_recommendation_chart":
                return await self._workflow.run_budget_recommendation_chart(
                    time_horizon=p.get("time_horizon"), **common_budget)

        # Bounded-rate (no datasheet)
        if action.name == "min_time":
            return await self._workflow.run_min_time(
                capacity_goal=p.get("capacity_goal", 1),
                rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "capacity_at":
            return await self._workflow.run_capacity_at(
                time=p.get("time", "0ms"),
                rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "quota_exhaustion_threshold":
            return await self._workflow.run_quota_exhaustion_threshold(
                rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "rates":
            return await self._workflow.run_rates(rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "quotas":
            return await self._workflow.run_quotas(rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "limits":
            return await self._workflow.run_limits(rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "idle_time_period":
            return await self._workflow.run_idle_time_period(
                rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "capacity_curve_inflection":
            return await self._workflow.run_capacity_curve_inflection(
                time_interval=p.get("time_interval", "1day"),
                rate=p.get("rate"), quota=p.get("quota"))

        raise ValueError(f"Unknown action: {action.name}")

    # ------------------------------------------------------------------
    # Result composition
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _humanize_duration_ms(ms: float) -> str:
        ms = int(ms)
        if ms < 1000:
            return f"{ms}ms"
        seconds = ms // 1000
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        secs = seconds % 60
        if minutes < 60:
            return f"{minutes}min {secs}s" if secs else f"{minutes}min"
        hours = minutes // 60
        mins = minutes % 60
        if hours < 24:
            return f"{hours}h {mins}min" if mins else f"{hours}h"
        days = hours // 24
        hrs = hours % 24
        return f"{days}d {hrs}h" if hrs else f"{days}d"

    def _humanize_durations_in_payload(self, node: Any) -> Any:
        if isinstance(node, dict):
            result: Dict[str, Any] = {}
            for k, v in node.items():
                if k.endswith("_ms") and isinstance(v, (int, float)):
                    result[k[:-3]] = self._humanize_duration_ms(v)
                else:
                    result[k] = self._humanize_durations_in_payload(v)
            return result
        if isinstance(node, list):
            return [self._humanize_durations_in_payload(item) for item in node]
        return node

    def _strip_html_from_payload(self, node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: "[HTML chart embedded in UI]" if k == "html" and isinstance(v, str) and v.strip().startswith("<")
                else self._strip_html_from_payload(v)
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [self._strip_html_from_payload(item) for item in node]
        return node

    def _serialise_payload_chunks(self, payload: Dict[str, Any], chunk_size: int = 4000) -> List[str]:
        if not payload:
            return ["{}"]
        sanitised = self._strip_html_from_payload(payload)
        payload_text = json.dumps(sanitised, ensure_ascii=False, separators=(",", ":"))
        if len(payload_text) <= chunk_size:
            return [payload_text]
        return [payload_text[i: i + chunk_size] for i in range(0, len(payload_text), chunk_size)]

    # ------------------------------------------------------------------
    # Datasheet alias map
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Message history helpers
    # ------------------------------------------------------------------

    def _append_history_messages(
        self,
        messages: List[ChatMessage],
        history: Optional[List[Dict[str, str]]],
    ) -> None:
        if not history:
            return
        for item in history[-MAX_HISTORY_TURNS:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            stripped = content.strip()
            if not stripped:
                continue
            messages.append({"role": role, "content": stripped})

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _parse_plan_text(self, *, text: str, question: str) -> Dict[str, Any]:
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
                pass
        logger.error("harvey.agent.plan_unparsed", question=question, raw=cleaned[:1000])
        raise ValueError("Failed to interpret H.A.R.V.E.Y.'s plan. Please rephrase your request.")

    def _deduplicate(self, values: List[str]) -> List[str]:
        seen: Set[str] = set()
        result: List[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

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
