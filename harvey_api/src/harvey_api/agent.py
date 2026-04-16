from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .clients import MCPWorkflowClient
from .config import get_settings
from .logging import get_logger
from .llm_client import (
    OpenAIClientConfig,
    OpenAIClient,
    GeminiClient,
)

logger = get_logger(__name__)

API_ACTIONS = {
    "min_time", "capacity_at", "capacity_during",
    "quota_exhaustion_threshold", "rates", "quotas", "limits",
    "idle_time_period", "evaluate_api_datasheet",
}

PLAN_REQUEST_MAX_ATTEMPTS = 3

PLAN_RESPONSE_FORMAT_INSTRUCTIONS = """Respond with a single JSON object:
{"actions": [...]}

Action shapes — RateObject/QuotaObject: {"value": number, "unit": string, "period": string}
  {"name": "min_time", "capacity_goal": number, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "capacity_at", "time": string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "capacity_during", "end_instant": string, "start_instant"?: string, "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "quota_exhaustion_threshold", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "rates", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "quotas", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "limits", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "idle_time_period", "rate"?: RateObject|[RateObject], "quota"?: QuotaObject|[QuotaObject]}
  {"name": "evaluate_api_datasheet", "datasheet_source": string, "plan_name": string (REQUIRED), "operation": string, "operation_params"?: object, "endpoint_path"?: string, "alias"?: string}

Rules:
- Valid JSON, double quotes only. No markdown fences or natural language wrapper.
- Leave actions empty only when the answer is directly inferable without any tool call.
- When an uploaded Datasheet is present in context, route ALL analysis through evaluate_api_datasheet — never call standalone tools.
- Multiple scenarios (different goals, endpoints, aliases) → one action per scenario.
- Example: {"actions":[{"name":"capacity_at","time":"5day","rate":{"value":100,"unit":"request","period":"1day"}}]}
"""


@dataclass
class PlannedAction:
    name: str
    params: Optional[Dict[str, Any]] = None


PLAN_PROMPT = """You are H.A.R.V.E.Y., an expert AI agent designed to reason about API rate and quota constraints using the ReAct pattern (Reasoning + Acting).
Your goal is to create a precise execution plan to answer the user's question about API consumption, rate limits, and quota constraints.

### API Analysis Tools (Prime4API — no pricing context required)

- **"min_time"**: Computes the minimum time to reach a given API call capacity goal under rate and quota constraints.
  - **Inputs:** `capacity_goal` (required, integer — the number of API calls to reach), `rate` (optional), `quota` (optional).
    - Rate / Quota shape: `{"value": number, "unit": string, "period": string}` — e.g., `{"value": 100, "unit": "request", "period": "1month"}`.
  - Either rate, quota, or both must be provided to constrain the calculation.
  - **Output:** `{"capacity_goal": number, "min_time": string}` — e.g., `{"capacity_goal": 500, "min_time": "4day"}`.
  - **Semantics:** The model grants capacity at t=0, so the first period's capacity is available immediately. For example, 500 requests at 100/day resolves to 4day (days 0–3), not 5.
  - **Use when:** The user asks how long it takes to reach a certain number of API calls, or how much time a rate/quota limit implies.

- **"capacity_at"**: Computes the accumulated capacity available at a specific time instant.
  - **Inputs:** `time` (required, string — e.g., '5day'), `rate` (optional), `quota` (optional).
  - **Output:** `{"time": string, "capacity": number}`.
  - **Semantics:** Closed interval `[0, T]`. Assumes consumption starts with an immediate "burst" at exactly `t=0`, meaning the first period's capacity is instantly available. For example, if the limit is 100/day, `capacity_at("5day")` evaluates to exactly 600 requests (`100 at t=0` + 500 across 5 days).
  - **Use when:** The user asks general questions like "How many API calls can I make in X days/hours?". This is the **default and safest** tool for capacity estimation.

- **"capacity_during"**: Computes the capacity generated during a defined time interval.
  - **Inputs:** `end_instant` (required, string), `start_instant` (optional, string — defaults to '0ms'), `rate` (optional), `quota` (optional).
  - **Output:** `{"start_instant": string, "end_instant": string, "capacity": number}`.
  - **Semantics:** Open/semi-open interval `(start, end]`. Because it excludes the initial `t=0` burst, asking for `capacity_during(5 days)` yields the cumulative capacity of 4 days continuous running.
  - **Use when:** Evaluating a sliding window that does **not** start at the absolute beginning. **Do NOT use** for general "how much in 5 days?" questions (use `capacity_at`).

- **"rates"**: Retrieves the effective maximum consumption rates.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"rates": [{"value": number, "unit": string, "period": string}]}`.
  - **Use when:** The user asks "What is the absolute maximum speed or rate I can consume this API at?".

- **"quotas"**: Retrieves the effective upper limit boundaries (quotas).
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"quotas": [{"value": number, "unit": string, "period": string}]}`.
  - **Use when:** The user asks about "hard caps", "monthly limits", or "long-term boundaries".

- **"limits"**: Retrieves all combined active limits (rates and quotas).
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"rates": [...], "quotas": [...]}`.
  - **Use when:** You need to analyze the full topology of limits at once.

- **"quota_exhaustion_threshold"**: Computes the absolute minimum time required to hit and exhaust each quota constraint.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"thresholds": [{"quota": {...}, "exhaustion_threshold": string}]}`.
  - **Use when:** The user asks "How fast can I blow through my quota going at maximum speed?".

- **"idle_time_period"**: Computes the idle time spent waiting for a quota period to reset after exhausting it as fast as possible.
  - **Inputs:** `rate` (optional), `quota` (optional).
  - **Output:** `{"idle_times": [{"quota": {...}, "idle_time": string}]}`.
  - **Semantics:** `idle_time = quota_period - exhaustion_threshold`.
  - **Use when:** The user asks "How long will I be blocked from making requests?" or "How long must I wait after hitting my limit?".

- **"evaluate_api_datasheet"**: Evaluates API constraints directly from a Datasheet YAML or URL.
  - **Inputs:** `datasheet_source` (required — use the uploaded alias shown in context, typically `"uploaded://datasheet"`, or an HTTP URL), `plan_name` (required, MUST be extracted from the user's message — e.g. "starter"; NEVER null), `operation` (required, one of: min_time, capacity_at, capacity_during, quota_exhaustion_threshold, rates, quotas, limits, idle_time_period), `operation_params` (optional, object), `endpoint_path` (optional), `alias` (optional).
  - **Rules:**
    - When an uploaded Datasheet is present (listed under "Uploaded API Datasheet content"), use `evaluate_api_datasheet` exclusively — never call standalone tools.
    - `endpoint_path`: set ONLY if the user names a specific endpoint. Omit to evaluate ALL endpoints.
    - `alias`: set ONLY if the user explicitly names a specific alias/function. Omit to evaluate all aliases.
    - Multiple scenarios → one action per scenario.

### Planning Strategy
1. **Analyze**: Understand the user's intent regarding API rate limits, quotas, or consumption.
2. **Check Datasheet**: If the user has provided a Datasheet YAML (listed under "Uploaded API Datasheet content") or a Datasheet URL, use `evaluate_api_datasheet` exclusively.
3. **Plan**: Select the appropriate tool(s):
   - Time to reach N API calls → `min_time`
   - Capacity available at time T → `capacity_at` (default for "how many calls in X time?")
   - Capacity in a window not starting at t=0 → `capacity_during`
   - How fast quotas are exhausted → `quota_exhaustion_threshold`
   - Effective maximum rate → `rates`
   - Effective quota caps → `quotas`
   - All combined limits → `limits`
   - Idle/blocked wait time → `idle_time_period`
   - Datasheet-based evaluation → `evaluate_api_datasheet`

### Response Format
Return a JSON object with the plan. See the accompanying format instructions.
"""

ANSWER_PROMPT = """You are H.A.R.V.E.Y., the Holistic Analysis and Regulation Virtual Expert for You.
You have executed an API analysis plan and now need to formulate the final answer.

### Inputs
1. **User Question**: The original request.
2. **Plan**: The actions you decided to take.
3. **Tool Results**: The JSON payloads returned by the tools.
4. **Datasheet Context**: The raw Datasheet YAML content (if available).

### Instructions
- **Synthesize**: Combine the quantitative results from the tools with the qualitative details from the Datasheet Context.
- **Be Precise**: If the tool returned a specific value (e.g., "8 h 19 min"), use it exactly.
- **NO ROUNDING OR APPROXIMATION (MANDATORY)**: NEVER round, approximate, or recalculate numeric outputs or time durations returned by any tool. Trust the tool's output as the ultimate mathematical truth.
- **Explain**: If you performed a computation, explain the result and its implications.
- **Contextualize**: Use the Datasheet Context to add details about the specific plan or endpoint being analysed.
- **Fallback**: If tools failed or returned empty results, explain what happened based on the context.
- **Authoritative tool results**: For ALL deterministic tools, treat the returned value as the definitive, mathematically correct answer. Do NOT perform independent informal calculations or suggest alternative values that contradict the tool output.
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
        """Return a per-request LLM client when the caller supplies a key, else the global admin one."""
        if not api_key:
            return self._llm
        settings = get_settings()
        if provider == "gemini":
            return GeminiClient(OpenAIClientConfig(
                api_key=api_key,
                model=settings.gemini_model,
            ))
        return OpenAIClient(OpenAIClientConfig(
            api_key=api_key,
            model=settings.openai_model,
        ))

    async def handle_question(
        self,
        question: str,
        datasheet_contents: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        provider: str = "openai",
    ) -> Dict[str, Any]:
        llm = self._resolve_llm(api_key, provider)

        provided_datasheets = [c for c in (datasheet_contents or []) if c]
        datasheet_alias_map = self._build_datasheet_alias_map(provided_datasheets)

        plan = await self._generate_plan(question, datasheet_alias_map=datasheet_alias_map, llm=llm)
        actions = self._normalize_actions(plan.get("actions"))

        results, last_payload = await self._execute_actions(
            actions=actions,
            datasheet_alias_map=datasheet_alias_map,
        )

        payload_for_answer, result_payload = self._compose_results_payload(actions, results, last_payload)
        answer = await self._generate_answer(question, plan, payload_for_answer, datasheet_alias_map, llm=llm)

        return {"plan": plan, "result": result_payload, "answer": answer}

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    async def _generate_plan(
        self,
        question: str,
        datasheet_alias_map: Dict[str, str],
        llm: Optional[OpenAIClient | GeminiClient] = None,
    ) -> Dict[str, Any]:
        messages = self._build_plan_request_messages(
            question=question,
            datasheet_alias_map=datasheet_alias_map,
        )

        attempt_errors: List[str] = []
        effective_llm = llm if llm is not None else self._llm
        for _ in range(PLAN_REQUEST_MAX_ATTEMPTS):
            attempt_messages = list(messages)
            if attempt_errors:
                attempt_messages.append("Previous attempt issues: " + attempt_errors[-1])
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

            return plan

        raise ValueError(
            "Failed to obtain a valid planning response. "
            + (attempt_errors[-1] if attempt_errors else "")
        )

    def _build_plan_request_messages(
        self,
        *,
        question: str,
        datasheet_alias_map: Dict[str, str],
    ) -> List[str]:
        messages: List[str] = [PLAN_PROMPT, PLAN_RESPONSE_FORMAT_INSTRUCTIONS]
        messages.append(f"Question: {question}")
        self._append_datasheet_messages(messages, datasheet_alias_map)
        return messages

    def _append_datasheet_messages(
        self,
        messages: List[str],
        datasheet_alias_map: Dict[str, str],
        chunk_size: int = 4000,
    ) -> None:
        if not datasheet_alias_map:
            return
        messages.append(
            "Uploaded API Datasheet content (full, chunked). "
            "Use these as datasheet_source in evaluate_api_datasheet actions:"
        )
        for alias, content in datasheet_alias_map.items():
            total_len = len(content or "")
            if not content:
                messages.append(f"{alias}: <empty content>")
                continue
            chunks = [content[i: i + chunk_size] for i in range(0, total_len, chunk_size)]
            messages.append(f"{alias}: length={total_len} chars; chunks={len(chunks)}")
            for idx, chunk in enumerate(chunks, start=1):
                messages.append(f"Datasheet[{alias}] chunk {idx}/{len(chunks)}:")
                messages.append(chunk)

    # ------------------------------------------------------------------
    # Answer generation
    # ------------------------------------------------------------------

    async def _generate_answer(
        self,
        question: str,
        plan: Dict[str, Any],
        payload: Dict[str, Any],
        datasheet_alias_map: Dict[str, str],
        llm: Optional[OpenAIClient | GeminiClient] = None,
    ) -> str:
        messages = [ANSWER_PROMPT]
        messages.append(f"Question: {question}")
        messages.append(f"Plan: {json.dumps(plan, ensure_ascii=False)}")

        summary = self._summarize_tool_payload(payload)
        if summary:
            messages.append(f"Tool payload summary: {json.dumps(summary, ensure_ascii=False)}")

        chunks = self._serialise_payload_chunks(payload)
        for idx, chunk in enumerate(chunks, start=1):
            messages.append(f"Tool payload chunk {idx}/{len(chunks)}:")
            messages.append(chunk)

        self._append_datasheet_messages(messages, datasheet_alias_map)

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

        if name == "evaluate_api_datasheet":
            params["datasheet_source"] = entry.get("datasheet_source")
            params["plan_name"] = entry.get("plan_name")
            params["operation"] = entry.get("operation")
            for key in ("operation_params", "endpoint_path", "alias"):
                if key in entry:
                    params[key] = entry[key]
            return PlannedAction(name=name, params=params)

        # Common rate/quota fields shared by all other API tools
        for key in ("rate", "quota"):
            if entry.get(key) is not None:
                params[key] = entry[key]
        # Tool-specific required fields
        if entry.get("capacity_goal") is not None:   # min_time
            params["capacity_goal"] = entry["capacity_goal"]
        if entry.get("time") is not None:             # capacity_at
            params["time"] = entry["time"]
        if entry.get("end_instant") is not None:      # capacity_during
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
            # Resolve datasheet YAML content when the source is an uploaded alias.
            yaml_content: Optional[str] = None
            if action.name == "evaluate_api_datasheet":
                ds_source = (action.params or {}).get("datasheet_source")
                if ds_source and ds_source in datasheet_alias_map:
                    yaml_content = datasheet_alias_map[ds_source]

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
        p = action.params or {}

        if action.name == "evaluate_api_datasheet":
            source = p.get("datasheet_source")
            # Replace alias with actual YAML content — Prime4API cannot resolve aliases.
            if yaml_content is not None and (source is None or not source.startswith("http")):
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
            return await self._workflow.run_min_time(
                capacity_goal=p.get("capacity_goal", 1),
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "capacity_at":
            return await self._workflow.run_capacity_at(
                time=p.get("time", "0ms"),
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "capacity_during":
            return await self._workflow.run_capacity_during(
                end_instant=p.get("end_instant", "0ms"),
                start_instant=p.get("start_instant", "0ms"),
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "quota_exhaustion_threshold":
            return await self._workflow.run_quota_exhaustion_threshold(
                rate=p.get("rate"),
                quota=p.get("quota"),
            )
        if action.name == "rates":
            return await self._workflow.run_rates(rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "quotas":
            return await self._workflow.run_quotas(rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "limits":
            return await self._workflow.run_limits(rate=p.get("rate"), quota=p.get("quota"))
        if action.name == "idle_time_period":
            return await self._workflow.run_idle_time_period(
                rate=p.get("rate"),
                quota=p.get("quota"),
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
            "actions": [a.name for a in actions],
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
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= chunk_size:
            return [text]
        return [text[i: i + chunk_size] for i in range(0, len(text), chunk_size)]

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
            return text[index: index + offset]
        return None
