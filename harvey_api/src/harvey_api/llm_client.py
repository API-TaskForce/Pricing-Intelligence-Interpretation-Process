from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from typing import Optional

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from openai import OpenAI


logger = logging.getLogger(__name__)

# Standard chat message format used throughout the codebase.
# role must be "system", "user", or "assistant".
ChatMessage = Dict[str, str]


@dataclass
class OpenAIClientConfig:
    api_key: str
    model: str
    base_url: Optional[str] = None
    api_retry_attempts: int = 5
    api_retry_backoff: float = 1.0
    api_retry_backoff_max: float = 8.0
    api_retry_multiplier: float = 2.0


class OpenAIClient:
    """Minimal OpenAI client."""

    def __init__(self, config: OpenAIClientConfig) -> None:
        self._config = config
        self._client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def make_full_request(
        self,
        messages: List[ChatMessage],
        *,
        json_output: bool = True,
    ) -> str:
        total_length = sum(len(m.get("content", "")) for m in messages)
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        logger.info(
            "harvey.llm.request model=%s messages=%d total_length=%d last_user_preview=%s",
            self._config.model,
            len(messages),
            total_length,
            self._truncate_for_log(last_user),
        )

        try:
            raw_response, finish_reason = self._send_prompt(messages, self._config.model)
        except RateLimitError as exc:
            logger.error("harvey.llm.rate_limit_failure model=%s", self._config.model)
            raise RuntimeError("LLM rate limit reached. Please retry shortly.") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            logger.error("harvey.llm.transport_failure model=%s error=%s", self._config.model, exc)
            raise RuntimeError("LLM connection problem. Please retry shortly.") from exc
        except OpenAIError as exc:
            logger.error("harvey.llm.generic_failure model=%s error=%s", self._config.model, exc)
            raise RuntimeError("LLM service failure. Please retry shortly.") from exc

        cleaned_response = self._normalize_response(raw_response)

        logger.info(
            "harvey.llm.response model=%s finish_reason=%s response_length=%d response_preview=%s cleaned_preview=%s",
            self._config.model,
            finish_reason,
            len(raw_response),
            self._truncate_for_log(raw_response),
            self._truncate_for_log(cleaned_response),
        )

        if json_output:
            parsed = self._ensure_json_response(cleaned_response)
            logger.info(
                "harvey.llm.complete model=%s json_length=%d json_preview=%s",
                self._config.model,
                len(parsed),
                self._truncate_for_log(parsed),
            )
            return parsed

        logger.info(
            "harvey.llm.complete model=%s text_length=%d text_preview=%s",
            self._config.model,
            len(cleaned_response),
            self._truncate_for_log(cleaned_response),
        )
        return cleaned_response

    def _send_prompt(self, messages: List[ChatMessage], model: str) -> tuple[str, str]:
        delay = max(self._config.api_retry_backoff, 0.5)
        max_delay = max(self._config.api_retry_backoff_max, delay)
        multiplier = max(self._config.api_retry_multiplier, 1.0)

        for attempt in range(1, self._config.api_retry_attempts + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                )
                message = completion.choices[0].message
                content = message.content or ""
                finish_reason = completion.choices[0].finish_reason or ""
                self._log_completion_message(completion, message, content, finish_reason)
                return content, finish_reason
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                delay = self._handle_api_retry(
                    model=model,
                    attempt=attempt,
                    delay=delay,
                    max_delay=max_delay,
                    multiplier=multiplier,
                    error=exc,
                )
            except APIError:
                raise
            except OpenAIError as exc:
                logger.error("harvey.llm.unexpected_api_error model=%s error=%s", model, exc)
                raise

        raise ValueError("LLM request retries exhausted.")

    def _handle_api_retry(
        self,
        *,
        model: str,
        attempt: int,
        delay: float,
        max_delay: float,
        multiplier: float,
        error: Exception,
    ) -> float:
        final_attempt = attempt >= self._config.api_retry_attempts
        if isinstance(error, RateLimitError):
            if final_attempt:
                logger.error(
                    "harvey.llm.rate_limit_exhausted model=%s attempts=%d",
                    model,
                    attempt,
                )
                raise error
            logger.warning(
                "harvey.llm.rate_limited model=%s attempt=%d sleep=%.2fs",
                model,
                attempt,
                delay,
            )
        else:
            if final_attempt:
                logger.error(
                    "harvey.llm.transport_error model=%s attempts=%d error=%s",
                    model,
                    attempt,
                    error,
                )
                raise error
            logger.warning(
                "harvey.llm.transport_retry model=%s attempt=%d sleep=%.2fs error=%s",
                model,
                attempt,
                delay,
                error,
            )

        time.sleep(delay)
        return min(delay * multiplier, max_delay)

    def _log_completion_message(
        self,
        completion: Any,
        message: Any,
        content: str,
        finish_reason: str,
    ) -> None:
        raw_message: Dict[str, Any] = {
            "role": getattr(message, "role", None),
            "content": content,
        }
        if hasattr(message, "model_dump"):
            try:
                raw_message = message.model_dump()  # type: ignore[assignment]
            except Exception:
                pass

        usage = None
        if hasattr(completion, "usage"):
            usage = getattr(completion, "usage")
            if hasattr(usage, "model_dump"):
                try:
                    usage = usage.model_dump()
                except Exception:
                    pass

        if not content.strip():
            logger.warning(
                "harvey.llm.empty_content",
                raw_message=raw_message,
                finish_reason=finish_reason,
                usage=usage,
            )
        else:
            logger.debug(
                "harvey.llm.raw_message",
                raw_message=raw_message,
                finish_reason=finish_reason,
                usage=usage,
            )

    @staticmethod
    def _normalize_response(response: str) -> str:
        stripped = response.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            return "\n".join(lines[1:-1]).strip()
        return stripped

    @staticmethod
    def _truncate_for_log(text: str, max_length: int = 2000) -> str:
        if len(text) <= max_length:
            return text
        truncated = text[:max_length]
        omitted = len(text) - max_length
        return f"{truncated}... <truncated {omitted} chars>"

    def _ensure_json_response(self, response: str) -> str:
        return _ensure_json(response)

    @staticmethod
    def _extract_json_document(text: str) -> str | None:
        return _extract_json_document(text)


# ---------------------------------------------------------------------------
# Module-level helpers shared by OpenAIClient and GeminiClient
# ---------------------------------------------------------------------------

def _extract_json_document(text: str) -> str | None:
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


def _ensure_json(response: str) -> str:
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        extracted = _extract_json_document(response)
        if extracted is None:
            raise ValueError("LLM response did not contain valid JSON.")
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM response did not contain valid JSON.") from exc
        response = json.dumps(parsed)
    else:
        response = json.dumps(parsed)
    return response


def _normalize(response: str) -> str:
    stripped = response.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _truncate(text: str, max_length: int = 2000) -> str:
    if len(text) <= max_length:
        return text
    omitted = len(text) - max_length
    return f"{text[:max_length]}... <truncated {omitted} chars>"


# ---------------------------------------------------------------------------
# GeminiClient — uses httpx directly to avoid OpenAI SDK sending extra Google
# auth headers alongside the explicit Bearer token (causes HTTP 400).
# ---------------------------------------------------------------------------

import httpx as _httpx


_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Free-tier Gemini models tried in order when the preferred model returns 429/503/404.
# The configured model (gemini_model in settings) is always tried first; this list
# provides the fallback sequence.
#
# Order rationale: start with fast/lite models (lower quota consumption, more generous
# free-tier limits), escalate to more capable/heavier models when needed.
#
# Models removed from this list:
#   - gemini-1.5-flash, gemini-1.5-flash-8b → retired, return HTTP 404
#   - gemini-2.0-flash, gemini-2.0-flash-lite → deprecated (shutdown June 2026);
#     still functional but will disappear — kept at end of list as last-resort fallbacks
#   - audio/TTS variants → not suitable for text generateContent calls
_GEMINI_FALLBACK_MODELS = [
    # ── Gemini 2.5 series (current stable, confirmed on AI Studio free keys) ─
    "gemini-2.5-flash-lite",        # lightest 2.5, most generous free quota
    "gemini-2.5-flash",             # fast + capable
    "gemini-2.5-pro",               # most capable stable model
    # ── Gemini 2.0 legacy (deprecated, shutdown June 2026) ───────────────────
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]


class GeminiClient:
    """httpx client for the native Gemini REST API (/v1beta/models/.../generateContent).

    Authenticates via '?key=API_KEY' query parameter — no Authorization header is
    sent at all, which completely avoids the 'Multiple authentication credentials'
    error that occurs with the OpenAI-compatible endpoint (/v1beta/openai/...).

    On 429 (rate limit) it transparently retries with the next free-tier model in
    _GEMINI_FALLBACK_MODELS, so students don't hit the per-model quota limits.
    """

    def __init__(self, config: OpenAIClientConfig) -> None:
        self._config = config
        # Build the ordered model list: preferred first, then the rest of the fallbacks.
        seen: set[str] = {config.model}
        self._models: list[str] = [config.model]
        for m in _GEMINI_FALLBACK_MODELS:
            if m not in seen:
                seen.add(m)
                self._models.append(m)

    def make_full_request(self, messages: List[ChatMessage], *, json_output: bool = True) -> str:
        total_length = sum(len(m.get("content", "")) for m in messages)
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        logger.info(
            "harvey.llm.request model=%s messages=%d total_length=%d last_user_preview=%s",
            self._config.model,
            len(messages),
            total_length,
            _truncate(last_user),
        )
        try:
            raw = self._post_with_fallback(messages)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("harvey.llm.generic_failure model=%s error=%s", self._config.model, exc)
            raise RuntimeError("LLM service failure. Please retry shortly.") from exc

        cleaned = _normalize(raw)
        logger.info(
            "harvey.llm.response model=%s response_length=%d", self._config.model, len(raw)
        )

        if json_output:
            return _ensure_json(cleaned)
        return cleaned

    def _post_with_fallback(self, messages: List[ChatMessage]) -> str:
        """Try each model in order; skip to the next on 429 or 404 (model unavailable)."""
        for model in self._models:
            try:
                return self._post(messages, model)
            except (_RateLimitedError, _ModelUnavailableError):
                next_models = self._models[self._models.index(model) + 1:] if model != self._models[-1] else []
                logger.warning(
                    "harvey.llm.rate_limited_fallback model=%s next_models=%s",
                    model,
                    next_models,
                )
                continue
        logger.error("harvey.llm.rate_limit_all_models models=%s", self._models)
        raise RuntimeError("LLM rate limit reached on all available models. Please retry shortly.")

    def _post(self, messages: List[ChatMessage], model: str) -> str:
        url = f"{_GEMINI_NATIVE_BASE}/{model}:generateContent"
        params = {"key": self._config.api_key}

        # Convert OpenAI-style messages to Gemini native format.
        # System messages go into systemInstruction; user/assistant become user/model turns.
        system_parts: List[Dict[str, Any]] = []
        contents: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": content})
            else:
                gemini_role = "model" if role == "assistant" else "user"
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        body: Dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}

        try:
            with _httpx.Client(timeout=120.0) as client:
                response = client.post(
                    url, params=params, json=body,
                    headers={"Content-Type": "application/json"},
                )
        except _httpx.TimeoutException as exc:
            raise RuntimeError("LLM connection problem. Please retry shortly.") from exc
        except _httpx.RequestError as exc:
            raise RuntimeError("LLM connection problem. Please retry shortly.") from exc

        if response.status_code == 429:
            raise _RateLimitedError(model)
        if response.status_code in (404, 503):
            # 404 = model deprecated/retired; 503 = overloaded. Skip to next fallback.
            logger.warning(
                "harvey.llm.model_not_found model=%s status=%d",
                model, response.status_code,
            )
            raise _ModelUnavailableError(model)
        if response.status_code >= 400:
            logger.error(
                "harvey.llm.generic_failure model=%s error=HTTP %d %s",
                model, response.status_code, response.text,
            )
            raise RuntimeError("LLM service failure. Please retry shortly.")

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


class _RateLimitedError(Exception):
    """Internal signal used by GeminiClient to trigger model fallback on 429."""


class _ModelUnavailableError(Exception):
    """Internal signal used by GeminiClient to trigger model fallback on 404 (deprecated/unknown model)."""

