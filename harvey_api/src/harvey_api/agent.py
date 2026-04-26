from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .clients import MCPWorkflowClient
from .config import get_settings
from .logging import get_logger
from .llm_client import (
    GeminiClient,
    OpenAIClient,
    OpenAIClientConfig,
)

logger = get_logger(__name__)

RATE_QUOTA_ACTIONS = {
    "min_time",
    "capacity_at",
    "capacity_during",
    "quota_exhaustion_threshold",
    "rates",
    "quotas",
    "limits",
    "idle_time_period",
}

DATASHEET_ACTIONS = {
    "datasheet_min_time",
    "datasheet_capacity_at",
    "datasheet_capacity_during",
    "datasheet_quota_exhaustion_threshold",
    "datasheet_rates",
    "datasheet_quotas",
    "datasheet_limits",
    "datasheet_idle_time_period",
    "datasheet_capacity_curve_inflection",
}

CHART_ACTIONS = {"datasheet_capacity_curve_inflection"}

NAV_ACTIONS = {
    "datasheet_nav_plans",
    "datasheet_nav_endpoints",
    "datasheet_nav_crf_ranges",
    "datasheet_nav_capacity_units",
    "datasheet_nav_aliases",
}

API_ACTIONS = RATE_QUOTA_ACTIONS | DATASHEET_ACTIONS | NAV_ACTIONS

PLAN_REQUEST_MAX_ATTEMPTS = 3
PLAN_RESPONSE_MODES = {"answer", "clarify"}
CLARIFICATION_FIELDS = {
    "plan_name",
    "endpoint_path",
    "alias",
    "capacity_unit",
    "capacity_request_factor",
}
MAX_HISTORY_TURNS = 10
SHORT_REPLY_MAX_WORDS = 5

PLAN_RESPONSE_FORMAT_INSTRUCTIONS = """Respond with a single JSON object:
{"actions": [...]}

Action shapes - RateObject/QuotaObject: {"value": number, "unit": string, "period": string}
  {"name": "min_time", "capacity_goal": number, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "capacity_at", "time": string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "capacity_during", "end_instant": string, "start_instant"?: string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "quota_exhaustion_threshold", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "rates", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "quotas", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "limits", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "idle_time_period", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "datasheet_min_time", "datasheet_source": string, "capacity_goal": number, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number}
  {"name": "datasheet_capacity_at", "datasheet_source": string, "time": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number}
  {"name": "datasheet_capacity_during", "datasheet_source": string, "end_instant": string, "start_instant"?: string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number}
  {"name": "datasheet_quota_exhaustion_threshold", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string}
  {"name": "datasheet_rates", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string}
  {"name": "datasheet_quotas", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string}
  {"name": "datasheet_limits", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string}
  {"name": "datasheet_idle_time_period", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string}
  {"name": "datasheet_capacity_curve_inflection", "datasheet_source": string, "time_interval": string, "plan_name"?: string, "endpoint_path"?: string, "alias"?: string, "capacity_unit"?: string, "capacity_request_factor"?: number}

Nav tools (supplementary context — use alongside calc tools, never alone):
  {"name": "datasheet_nav_plans", "datasheet_source": string}
  {"name": "datasheet_nav_endpoints", "datasheet_source": string, "plan_name"?: string}
  {"name": "datasheet_nav_crf_ranges", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string}
  {"name": "datasheet_nav_capacity_units", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string}
  {"name": "datasheet_nav_aliases", "datasheet_source": string, "plan_name"?: string, "endpoint_path"?: string}

Rules:
- Valid JSON, double quotes only. No markdown fences or natural language wrapper.
- Leave actions empty only when the answer is directly inferable without any tool call.
- When an uploaded Datasheet or Datasheet URL is present in context, route datasheet analysis through datasheet_* actions, not through standalone rate/quota tools.
- plan_name is optional. Omit it when the user does not name a plan and the question should evaluate all plans available in the datasheet.
- endpoint_path is optional. Omit it when the user does not name a specific endpoint.
- alias is optional. Omit it when the user does not name a specific alias/function.
- capacity_unit is optional. Include it when the user specifies a particular unit (e.g., "emails", "MBs").
- capacity_request_factor is optional. Include it only when the user explicitly states how many units they send per API call. When omitted, the API returns 3 automatic scenarios (min/typical/max).
- Multiple scenarios (different plans, goals, endpoints, aliases, or time windows) -> one action per scenario.
- Example: {"actions":[{"name":"datasheet_nav_crf_ranges","datasheet_source":"uploaded://datasheet","plan_name":"pro","endpoint_path":"/mail/send"},{"name":"datasheet_capacity_at","datasheet_source":"uploaded://datasheet","time":"5day","plan_name":"pro","endpoint_path":"/mail/send"}]}
"""


@dataclass
class PlannedAction:
    name: str
    params: Optional[Dict[str, Any]] = None


PLAN_PROMPT = """You are H.A.R.V.E.Y., an expert AI agent designed to reason about API rate and quota constraints using the ReAct pattern (Reasoning + Acting).
Your goal is to create a precise execution plan to answer the user's question about API consumption, rate limits, quota constraints, and datasheet-driven pricing plans.

### Prime4API Tools Without Datasheet Context

- "min_time": Computes the minimum time to reach a capacity goal from direct rate/quota objects.
- "capacity_at": Computes the accumulated capacity available at a specific time instant from direct rate/quota objects.
- "capacity_during": Computes the capacity generated in a time interval from direct rate/quota objects.
- "quota_exhaustion_threshold": Computes the minimum time required to exhaust each quota as fast as possible.
- "rates": Retrieves effective maximum consumption rates.
- "quotas": Retrieves effective quota boundaries.
- "limits": Retrieves all active rate and quota limits together.
- "idle_time_period": Computes how long the consumer must wait after exhausting quota as fast as possible.

### Prime4API Datasheet Tools

Use these when the question is about an uploaded datasheet or a datasheet URL.

- "datasheet_min_time": Same semantics as "min_time", but reads constraints from a datasheet.
  Inputs: datasheet_source, capacity_goal, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_capacity_at": Same semantics as "capacity_at", but reads constraints from a datasheet.
  Inputs: datasheet_source, time, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_capacity_during": Same semantics as "capacity_during", but reads constraints from a datasheet.
  Inputs: datasheet_source, end_instant, optional start_instant, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_quota_exhaustion_threshold": Reads quota exhaustion thresholds from a datasheet.
  Inputs: datasheet_source, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_rates": Reads effective rates from a datasheet.
  Inputs: datasheet_source, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_quotas": Reads effective quotas from a datasheet.
  Inputs: datasheet_source, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_limits": Reads combined limits from a datasheet.
  Inputs: datasheet_source, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_idle_time_period": Reads idle time periods from a datasheet.
  Inputs: datasheet_source, optional plan_name, optional endpoint_path, optional alias.
- "datasheet_capacity_curve_inflection": Generates an interactive inflection-point capacity curve chart from a datasheet.
  Returns an embedded HTML document rendered as an interactive visual in the UI — use this when the user asks to visualise, plot, or chart the capacity curve or inflection points.
  Inputs: datasheet_source, time_interval (e.g. '1h', '1day', '1month'), optional plan_name, optional endpoint_path, optional alias, optional capacity_unit, optional capacity_request_factor.

### Datasheet Interpretation Notes

- datasheet_source always points to exactly one source: an uploaded alias such as "uploaded://datasheet" or one remote URL.
- plan_name is optional. If absent, the tool may return results grouped across multiple plans.
- endpoint_path and alias are optional filters. If absent, the tool may return all matching endpoints and aliases.
- Datasheet outputs can be nested by plan, endpoint, alias, dimension, and capacity_request_factor.
- capacity_request_factor (CRF) means the capacity cost per request. Higher CRF means each request consumes more quota/rate budget.
- capacity_unit filters results to a single dimension (e.g., "emails", "MBs"). Include it when the user asks about a specific unit.

### Datasheet Nav Tools

These are supplementary context tools — always combine them with a calc tool, never use alone.

- "datasheet_nav_plans": Lists all plan names in the datasheet. Use when plan names are unknown and cross-plan comparison is needed.
- "datasheet_nav_endpoints": Lists endpoint paths for a plan.
- "datasheet_nav_crf_ranges": Returns the min/max CRF range per capacity unit with a human-readable description.
  INCLUDE THIS alongside any calc tool when the user has NOT specified their batch size or units per API call.
  This gives the answer phase the CRF range to contextualise the 3 automatic scenarios and ask a meaningful follow-up question.
- "datasheet_nav_capacity_units": Lists capacity units available for a plan/endpoint (e.g., "emails", "MBs").
- "datasheet_nav_aliases": Lists endpoint aliases. Use when you need to confirm alias existence.

### Planning Strategy
1. Analyze the user's intent.
2. If the question depends on a datasheet or datasheet URL, choose datasheet_* tools only.
3. If the user asks for a plan-specific answer, include plan_name. Otherwise omit it.
4. If the user asks about one endpoint or alias, include endpoint_path and/or alias. Otherwise omit them.
5. Choose the minimal set of actions needed to answer the question precisely.
6. When the user asks about time/capacity and has NOT specified how many units they send per API call,
   add "datasheet_nav_crf_ranges" to the plan alongside the calc action for the relevant endpoint.
   This enables the answer phase to contextualise the 3 automatic CRF scenarios meaningfully.
   Exception: do NOT add nav tools when the action is "datasheet_capacity_curve_inflection" — charts
   work correctly with just datasheet_source and optional plan_name/endpoint_path. Never ask the user
   for CRF or capacity_unit before generating a chart.
7. Nav actions are supplementary — never replace calc actions with them.
8. If the user says "para todos los planes", "todos los planes", "para todo", "sin filtros", or sends
   a clarification answer from the UI selecting all plans — call the tool immediately with only
   datasheet_source. Omit plan_name, endpoint_path, alias, capacity_unit, and
   capacity_request_factor entirely, even if they were mentioned earlier. Do NOT navigate first,
   do NOT ask for any clarification. The API aggregates across all plans, endpoints, and dimensions
   automatically when no filters are passed.
9. If the user's request is ambiguous (e.g. "genera la curva" with no plan or time_interval
   specified) and you genuinely cannot build the action, return {"actions": []} — the answer phase
   will ask one clarifying question. Only do this once: if the user already answered, always produce
   an action — never return empty actions twice in a row.

### Tool Selection Guide
- Time to reach N calls -> "min_time" or "datasheet_min_time"
- Capacity available at time T -> "capacity_at" or "datasheet_capacity_at"
- Capacity in a non-zero window -> "capacity_during" or "datasheet_capacity_during"
- How fast quota is exhausted -> "quota_exhaustion_threshold" or "datasheet_quota_exhaustion_threshold"
- Effective rate -> "rates" or "datasheet_rates"
- Effective quotas -> "quotas" or "datasheet_quotas"
- All limits -> "limits" or "datasheet_limits"
- Idle or blocked wait time -> "idle_time_period" or "datasheet_idle_time_period"
- Visualise / plot / chart capacity curve -> "datasheet_capacity_curve_inflection" (call directly with datasheet_source + optional plan_name/endpoint_path — no CRF or nav tools needed)
- CRF range for contextualising 3 automatic scenarios -> "datasheet_nav_crf_ranges"
- List available plan names -> "datasheet_nav_plans"
- List endpoints for a plan -> "datasheet_nav_endpoints"
- List capacity units -> "datasheet_nav_capacity_units"
- List aliases -> "datasheet_nav_aliases"

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

**5. Alias mentions — suppress when absent.**
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

**9. HTML chart handling.**
- If the tool result contains an "html" field, the chart is already rendered in the UI as an
  interactive iframe. Do not reproduce or describe the HTML. Briefly explain what the chart shows
  (inflection points, capacity curve shape, time interval) and invite the user to interact with it.

### Response Format
- Use the user's language (Spanish if they wrote in Spanish).
- **Simple results** (one plan, one CRF, one number): answer in one or two natural sentences. Do NOT use bullet lists when the answer fits in a sentence. Do NOT echo back information the user already provided (plan name, unit, CRF) — just state the result.
- **Complex results** (multiple plans, multiple scenarios, or comparison): use Markdown bold headers for plan names, bullet lists for scenarios, bold for key figures.
- Close with the follow-up question when CRF is unknown (rule 4). When no tools ran, ask one clarifying question (rule 8).
"""


PLAN_CLARIFICATION_FORMAT_INSTRUCTIONS = """Additional planning rules:
- You may return {"response_mode":"answer"|"clarify","clarification_fields"?: [...], "actions":[...]}.
- response_mode defaults to "answer". Use "clarify" when a precise datasheet answer should wait for user input.
- clarification_fields may contain only: "plan_name", "endpoint_path", "alias", "capacity_unit", "capacity_request_factor".
- In clarify mode, actions may contain NAV tools only. Use the minimum nav calls needed for a grounded follow-up.
- Use conversation history to resolve short follow-up replies like "Pro", "/mail/send", or "500 emails per call".
- Ask for plan_name only when the user wants one concrete plan answer and has not selected one.
- Do not ask for plan_name when the user explicitly wants all plans or a comparison across plans.
- Ask for endpoint_path only when the datasheet has multiple distinct endpoints and the answer depends on which one.
- Ask for capacity_request_factor when per-call batch size materially changes the requested throughput or timing result.
- Ask for capacity_unit ONLY when the datasheet genuinely has multiple distinct capacity units AND the user has not specified one. If the nav results (e.g. crf_ranges description) already tell you the unit, do NOT ask for it.
- The UI provides interactive dropdowns for the user; do NOT suggest typing special keywords like "por defecto".
- Clarification example: {"response_mode":"clarify","clarification_fields":["plan_name","capacity_request_factor"],"actions":[{"name":"datasheet_nav_plans","datasheet_source":"uploaded://datasheet"},{"name":"datasheet_nav_crf_ranges","datasheet_source":"uploaded://datasheet","endpoint_path":"/mail/send"}]}
"""

ANSWER_CLARIFICATION_PROMPT = """Additional answer rules (apply ONLY when Plan.response_mode is "clarify"):
- Do NOT answer the original capacity question yet.
- Use nav results to ask a short, grounded follow-up that helps the user provide the missing selector(s).
- Prefer one natural message. Ask in this order when relevant: plan -> endpoint -> alias -> capacity unit -> units per call.
- Do NOT enumerate plan names, endpoint paths, aliases, or capacity units in your follow-up question — the UI already shows all available options as interactive dropdowns. Mentioning them in text is redundant.
- If CRF ranges are available from nav results, mention the exact min/max range in domain language — this is the only value the UI does not show as a dropdown.
- Do NOT suggest typing "por defecto" or any special keyword.
- Do not describe worst/typical/best scenarios yet.
"""


class HarveyAgent:
    def __init__(self, workflow: MCPWorkflowClient) -> None:
        self._workflow = workflow
        settings = get_settings()
        if not settings.harvey_llm_key:
            raise RuntimeError("HARVEY_LLM_KEY is required for natural language orchestration")
        client_config = OpenAIClientConfig(
            api_key=settings.harvey_llm_key,
            model=settings.openai_model,
        )
        self._llm = OpenAIClient(client_config)

    def _resolve_llm(self, api_key: Optional[str], provider: str) -> OpenAIClient | GeminiClient:
        if not api_key:
            return self._llm
        settings = get_settings()
        if provider == "gemini":
            return GeminiClient(
                OpenAIClientConfig(
                    api_key=api_key,
                    model=settings.gemini_model,
                )
            )
        return OpenAIClient(
            OpenAIClientConfig(
                api_key=api_key,
                model=settings.openai_model,
            )
        )

    async def handle_question(
        self,
        question: str,
        datasheet_contents: Optional[List[str]] = None,
        datasheet_urls: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        api_key: Optional[str] = None,
        provider: str = "openai",
        query_mode: str = "guided",
    ) -> Dict[str, Any]:
        llm = self._resolve_llm(api_key, provider)

        provided_datasheets = [content for content in (datasheet_contents or []) if content]
        datasheet_alias_map = self._build_datasheet_alias_map(provided_datasheets)
        provided_urls = [url for url in (datasheet_urls or []) if url]

        plan = await self._generate_plan(
            question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=provided_urls,
            history=history,
            llm=llm,
            query_mode=query_mode,
        )
        if query_mode != "autonomous":
            plan = self._apply_clarification_fallback(
                plan=plan,
                question=question,
                datasheet_alias_map=datasheet_alias_map,
                datasheet_urls=provided_urls,
                history=history,
            )
        actions = self._normalize_actions(plan.get("actions"))

        results, last_payload = await self._execute_actions(
            actions=actions,
            datasheet_alias_map=datasheet_alias_map,
        )

        payload_for_answer, result_payload = self._compose_results_payload(actions, results, last_payload)
        answer = await self._generate_answer(
            question,
            plan,
            payload_for_answer,
            datasheet_alias_map,
            datasheet_urls=provided_urls,
            history=history,
            llm=llm,
        )

        return {"plan": plan, "result": result_payload, "answer": answer}

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    async def _generate_plan(
        self,
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        llm: Optional[OpenAIClient | GeminiClient] = None,
        query_mode: str = "guided",
    ) -> Dict[str, Any]:
        messages = self._build_plan_request_messages(
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=datasheet_urls,
            history=history,
            query_mode=query_mode,
        )

        attempt_errors: List[str] = []
        effective_llm = llm if llm is not None else self._llm
        for _ in range(PLAN_REQUEST_MAX_ATTEMPTS):
            attempt_messages = list(messages)
            if attempt_errors:
                attempt_messages.append(f"Previous attempt issues: {attempt_errors[-1]}")
                attempt_messages.append("Return a corrected JSON plan that satisfies all requirements.")

            try:
                text = await asyncio.to_thread(
                    effective_llm.make_full_request,
                    "\n".join(attempt_messages),
                    json_output=True,
                )
            except ValueError as exc:
                attempt_errors.append(f"LLM response was not valid JSON: {exc}")
                continue

            try:
                plan = self._parse_plan_text(text)
            except ValueError as exc:
                attempt_errors.append(str(exc))
                continue

            return self._normalise_plan(plan)

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
        query_mode: str = "guided",
    ) -> List[str]:
        messages: List[str] = [PLAN_PROMPT, PLAN_RESPONSE_FORMAT_INSTRUCTIONS]
        if query_mode == "autonomous":
            messages.append(
                "Mode: AUTONOMOUS. Never use response_mode 'clarify'. "
                "Always answer directly using all available plans when plan_name is not specified. "
                "Omit plan_name from actions to evaluate all plans."
            )
        else:
            messages.append(PLAN_CLARIFICATION_FORMAT_INSTRUCTIONS)
        self._append_history_messages(messages, history)
        messages.append(f"Question: {question}")
        self._append_datasheet_messages(messages, datasheet_alias_map)
        self._append_url_references(messages, datasheet_urls)
        if query_mode != "autonomous":
            self._append_clarification_priority_guidance(
                messages,
                question=question,
                datasheet_alias_map=datasheet_alias_map,
                datasheet_urls=datasheet_urls,
                history=history,
            )
        return messages

    def _append_datasheet_messages(
        self,
        messages: List[str],
        datasheet_alias_map: Dict[str, str],
    ) -> None:
        if not datasheet_alias_map:
            return
        messages.append(
            "API datasheet aliases loaded. Use each alias as datasheet_source "
            "in datasheet_* actions. The full content is resolved at execution time:"
        )
        for alias in datasheet_alias_map:
            messages.append(alias)

    def _append_url_references(
        self,
        messages: List[str],
        datasheet_urls: Optional[List[str]],
    ) -> None:
        if not datasheet_urls:
            return
        messages.append(
            "Remote API datasheet URLs. Pass each URL directly as datasheet_source "
            "in datasheet_* actions. Do not modify the URL:"
        )
        for url in datasheet_urls:
            messages.append(url)

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
        llm: Optional[OpenAIClient | GeminiClient] = None,
    ) -> str:
        messages = [ANSWER_PROMPT, ANSWER_CLARIFICATION_PROMPT]
        self._append_history_messages(messages, history)
        messages.append(f"Question: {question}")
        messages.append(f"Plan: {json.dumps(plan, ensure_ascii=False)}")

        summary = self._summarize_tool_payload(payload)
        if summary:
            messages.append(f"Tool payload summary: {json.dumps(summary, ensure_ascii=False)}")

        chunks = self._serialise_payload_chunks(payload)
        for index, chunk in enumerate(chunks, start=1):
            messages.append(f"Tool payload chunk {index}/{len(chunks)}:")
            messages.append(chunk)

        self._append_datasheet_messages(messages, datasheet_alias_map)
        self._append_url_references(messages, datasheet_urls)

        effective_llm = llm if llm is not None else self._llm
        response = await asyncio.to_thread(
            effective_llm.make_full_request,
            "\n".join(messages),
            json_output=False,
        )
        return response or "No answer could be generated."

    # ------------------------------------------------------------------
    # Plan parsing and action normalisation
    # ------------------------------------------------------------------

    def _parse_plan_text(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("H.A.R.V.E.Y. returned an empty planning response. Please retry.")

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        extracted = self._extract_first_json_block(cleaned)
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass

        raise ValueError("Failed to interpret H.A.R.V.E.Y.'s plan. Please rephrase your request.")

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

    def _append_clarification_priority_guidance(
        self,
        messages: List[str],
        *,
        question: str,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
    ) -> None:
        fields = self._infer_missing_clarification_fields(
            question=question,
            datasheet_alias_map=datasheet_alias_map,
            datasheet_urls=datasheet_urls,
            history=history,
        )
        if not fields:
            return

        messages.append(
            "Clarification priority: ask a follow-up before running calc tools if the plan would otherwise be imprecise."
        )
        messages.append(
            "Likely missing selectors for this turn: " + ", ".join(fields)
        )

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
            # Merge LLM-declared fields with heuristic fields so the UI shows everything needed.
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
        if not any(action.name in DATASHEET_ACTIONS for action in actions):
            return normalised_plan

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
            fields.append("plan_name")
        if self._should_clarify_capacity_request_factor(question, history):
            fields.append("capacity_request_factor")
        return fields

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
            add_action(
                "datasheet_nav_capacity_units",
                plan_name=known_plan,
                endpoint_path=known_endpoint,
            )
            add_action(
                "datasheet_nav_crf_ranges",
                plan_name=known_plan,
                endpoint_path=known_endpoint,
            )
        return nav_actions

    def _resolve_single_datasheet_source(
        self,
        *,
        datasheet_alias_map: Dict[str, str],
        datasheet_urls: Optional[List[str]],
        actions: List[PlannedAction],
    ) -> Optional[str]:
        explicit_sources = self._deduplicate(
            [
                str(source)
                for source in (
                    (action.params or {}).get("datasheet_source") for action in actions
                )
                if source
            ]
        )
        if len(explicit_sources) == 1:
            return explicit_sources[0]

        datasheet_sources = self._all_datasheet_sources(datasheet_alias_map, datasheet_urls)
        if len(datasheet_sources) == 1:
            return datasheet_sources[0]
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
        if self._asks_for_cross_plan_answer(question) or self._asks_for_plan_recommendation(question):
            return False
        if self._mentions_plan_explicitly(question):
            return False
        return True

    def _should_clarify_capacity_request_factor(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]],
    ) -> bool:
        if self._looks_like_reply_to_assistant_prompt(question, history, expected="capacity_request_factor"):
            return False
        if self._mentions_batch_size(question):
            return False
        return True

    def _looks_like_capacity_question(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            "cuanto",
            "cuantos",
            "cuanta",
            "cuantas",
            "how many",
            "how much",
            "how long",
            "puedo mandar",
            "puedo enviar",
            "can i send",
            "can i make",
            "emails",
            "correos",
            "requests",
            "peticiones",
            "capacity",
            "capacidad",
            "throughput",
            "tardo",
        )
        return any(pattern in lowered for pattern in patterns)

    def _asks_for_cross_plan_answer(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            "todos los planes",
            "all plans",
            "across plans",
            "compar",
            "vs ",
            "versus",
            "entre planes",
        )
        return any(pattern in lowered for pattern in patterns)

    def _asks_for_plan_recommendation(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            "que plan",
            "qué plan",
            "which plan",
            "best plan",
            "me conviene",
            "recomiendas",
            "recommend",
        )
        return any(pattern in lowered for pattern in patterns)

    def _mentions_plan_explicitly(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            "plan ",
            "plan:",
            "en el plan",
            "del plan",
            "if me centro en el plan",
            "focused on the plan",
        )
        return any(pattern in lowered for pattern in patterns)

    def _mentions_batch_size(self, text: str) -> bool:
        lowered = text.lower()
        if re.search(r"\b\d+(?:[.,]\d+)?\s*(emails?|correos?|mensajes?|mb|mbs|units?)\b", lowered):
            return True
        call_patterns = (
            "por llamada",
            "por peticion",
            "por petición",
            "per call",
            "per request",
            "cada llamada",
            "each request",
        )
        return any(pattern in lowered for pattern in call_patterns) and bool(
            re.search(r"\b\d+(?:[.,]\d+)?\b", lowered)
        )

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

        latest_lowered = latest_assistant.lower()
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
            logger.warning("harvey.agent.unknown_action name=%s", name)
            return None

        params: Dict[str, Any] = {}

        if name in NAV_ACTIONS:
            datasheet_source = entry.get("datasheet_source")
            if datasheet_source is not None:
                params["datasheet_source"] = datasheet_source
            for key in ("plan_name", "endpoint_path"):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            return PlannedAction(name=name, params=params)

        if name in DATASHEET_ACTIONS:
            datasheet_source = entry.get("datasheet_source")
            if datasheet_source is not None:
                params["datasheet_source"] = datasheet_source
            for key in ("plan_name", "endpoint_path", "alias"):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            for key in ("capacity_unit",):
                if entry.get(key) is not None:
                    params[key] = entry[key]
            if entry.get("capacity_request_factor") is not None:
                params["capacity_request_factor"] = entry["capacity_request_factor"]
            if name == "datasheet_min_time" and entry.get("capacity_goal") is not None:
                params["capacity_goal"] = entry["capacity_goal"]
            if name == "datasheet_capacity_at" and entry.get("time") is not None:
                params["time"] = entry["time"]
            if name == "datasheet_capacity_during":
                if entry.get("end_instant") is not None:
                    params["end_instant"] = entry["end_instant"]
                if entry.get("start_instant") is not None:
                    params["start_instant"] = entry["start_instant"]
            if name == "datasheet_capacity_curve_inflection" and entry.get("time_interval") is not None:
                params["time_interval"] = entry["time_interval"]
            return PlannedAction(name=name, params=params)

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
            if action.name in DATASHEET_ACTIONS or action.name in NAV_ACTIONS:
                datasheet_source = (action.params or {}).get("datasheet_source")
                if datasheet_source and datasheet_source in datasheet_alias_map:
                    yaml_content = datasheet_alias_map[datasheet_source]

            payload = await self._run_single_action(action=action, yaml_content=yaml_content)
            results.append({"index": index, "action": action.name, "payload": payload})
            last_payload = payload

        return results, last_payload

    async def _run_single_action(
        self,
        *,
        action: PlannedAction,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = action.params or {}

        if action.name in NAV_ACTIONS:
            source = params.get("datasheet_source")
            if yaml_content is not None and (source is None or not str(source).startswith("http")):
                source = yaml_content
            if action.name == "datasheet_nav_plans":
                return await self._workflow.run_datasheet_nav_plans(datasheet_source=source)
            if action.name == "datasheet_nav_endpoints":
                return await self._workflow.run_datasheet_nav_endpoints(
                    datasheet_source=source,
                    plan_name=params.get("plan_name"),
                )
            if action.name == "datasheet_nav_crf_ranges":
                return await self._workflow.run_datasheet_nav_crf_ranges(
                    datasheet_source=source,
                    plan_name=params.get("plan_name"),
                    endpoint_path=params.get("endpoint_path"),
                )
            if action.name == "datasheet_nav_capacity_units":
                return await self._workflow.run_datasheet_nav_capacity_units(
                    datasheet_source=source,
                    plan_name=params.get("plan_name"),
                    endpoint_path=params.get("endpoint_path"),
                )
            if action.name == "datasheet_nav_aliases":
                return await self._workflow.run_datasheet_nav_aliases(
                    datasheet_source=source,
                    plan_name=params.get("plan_name"),
                    endpoint_path=params.get("endpoint_path"),
                )

        if action.name in DATASHEET_ACTIONS:
            source = params.get("datasheet_source")
            if yaml_content is not None and (source is None or not str(source).startswith("http")):
                source = yaml_content

            common_kwargs = {
                "datasheet_source": source,
                "plan_name": params.get("plan_name"),
                "endpoint_path": params.get("endpoint_path"),
                "alias": params.get("alias"),
            }

            if action.name == "datasheet_min_time":
                return await self._workflow.run_datasheet_min_time(
                    capacity_goal=params.get("capacity_goal", 1),
                    capacity_unit=params.get("capacity_unit"),
                    capacity_request_factor=params.get("capacity_request_factor"),
                    **common_kwargs,
                )
            if action.name == "datasheet_capacity_at":
                return await self._workflow.run_datasheet_capacity_at(
                    time=params.get("time", "0ms"),
                    capacity_unit=params.get("capacity_unit"),
                    capacity_request_factor=params.get("capacity_request_factor"),
                    **common_kwargs,
                )
            if action.name == "datasheet_capacity_during":
                return await self._workflow.run_datasheet_capacity_during(
                    end_instant=params.get("end_instant", "0ms"),
                    start_instant=params.get("start_instant", "0ms"),
                    capacity_unit=params.get("capacity_unit"),
                    capacity_request_factor=params.get("capacity_request_factor"),
                    **common_kwargs,
                )
            if action.name == "datasheet_quota_exhaustion_threshold":
                return await self._workflow.run_datasheet_quota_exhaustion_threshold(**common_kwargs)
            if action.name == "datasheet_rates":
                return await self._workflow.run_datasheet_rates(**common_kwargs)
            if action.name == "datasheet_quotas":
                return await self._workflow.run_datasheet_quotas(**common_kwargs)
            if action.name == "datasheet_limits":
                return await self._workflow.run_datasheet_limits(**common_kwargs)
            if action.name == "datasheet_idle_time_period":
                return await self._workflow.run_datasheet_idle_time_period(**common_kwargs)
            if action.name == "datasheet_capacity_curve_inflection":
                return await self._workflow.run_datasheet_capacity_curve_inflection(
                    time_interval=params.get("time_interval", "1day"),
                    capacity_unit=params.get("capacity_unit"),
                    capacity_request_factor=params.get("capacity_request_factor"),
                    **common_kwargs,
                )

        if action.name == "min_time":
            return await self._workflow.run_min_time(
                capacity_goal=params.get("capacity_goal", 1),
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "capacity_at":
            return await self._workflow.run_capacity_at(
                time=params.get("time", "0ms"),
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "capacity_during":
            return await self._workflow.run_capacity_during(
                end_instant=params.get("end_instant", "0ms"),
                start_instant=params.get("start_instant", "0ms"),
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "quota_exhaustion_threshold":
            return await self._workflow.run_quota_exhaustion_threshold(
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "rates":
            return await self._workflow.run_rates(
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "quotas":
            return await self._workflow.run_quotas(
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "limits":
            return await self._workflow.run_limits(
                rate=params.get("rate"),
                quota=params.get("quota"),
            )
        if action.name == "idle_time_period":
            return await self._workflow.run_idle_time_period(
                rate=params.get("rate"),
                quota=params.get("quota"),
            )

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
            empty: Dict[str, Any] = {"steps": []}
            return empty, empty

        if len(results) == 1:
            step = results[0]
            payload = step.get("payload") or last_payload or {}
            return payload, step

        combined: Dict[str, Any] = {
            "actions": [action.name for action in actions],
            "steps": results,
        }
        if last_payload is not None:
            combined["lastPayload"] = last_payload
        return combined, combined

    # ------------------------------------------------------------------
    # Payload serialisation / summarisation helpers
    # ------------------------------------------------------------------

    def _serialise_payload_chunks(self, payload: Dict[str, Any], chunk_size: int = 4000) -> List[str]:
        if not payload:
            return ["{}"]
        sanitised = self._strip_html_from_payload(payload)
        text = json.dumps(sanitised, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= chunk_size:
            return [text]
        return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]

    def _strip_html_from_payload(self, node: Any) -> Any:
        """Replace large HTML strings with a short placeholder to keep LLM context small."""
        if isinstance(node, dict):
            return {
                k: "[HTML chart embedded in UI]" if k == "html" and isinstance(v, str) and v.strip().startswith("<")
                else self._strip_html_from_payload(v)
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [self._strip_html_from_payload(item) for item in node]
        return node

    def _summarize_tool_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not payload:
            return None
        summary: Dict[str, Any] = {}

        cardinalities = self._collect_field_values(payload, "cardinality")
        last_cardinality = self._select_last_int(cardinalities)
        if last_cardinality is not None:
            summary["cardinality"] = last_cardinality

        validation_states = self._collect_field_values(payload, "valid")
        last_valid = self._select_last_bool(validation_states)
        if last_valid is not None:
            summary["valid"] = last_valid

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

    def _append_history_messages(
        self,
        messages: List[str],
        history: Optional[List[Dict[str, str]]],
    ) -> None:
        if not history:
            return

        sanitized_turns: List[str] = []
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
            sanitized_turns.append(f"{role}: {stripped}")

        if not sanitized_turns:
            return

        messages.append("Conversation history (previous turns only):")
        messages.extend(sanitized_turns)

    # ------------------------------------------------------------------
    # Datasheet alias map
    # ------------------------------------------------------------------

    def _build_datasheet_alias_map(self, datasheet_contents: List[str]) -> Dict[str, str]:
        alias_map: OrderedDict[str, str] = OrderedDict()
        if len(datasheet_contents) == 1:
            if datasheet_contents[0]:
                alias_map["uploaded://datasheet"] = datasheet_contents[0]
        else:
            for index, content in enumerate(datasheet_contents):
                if content:
                    alias_map[f"uploaded://datasheet/{index + 1}"] = content
        return dict(alias_map)

    def _deduplicate(self, values: List[str]) -> List[str]:
        seen: Set[str] = set()
        result: List[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

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
            return text[index : index + offset]
        return None
