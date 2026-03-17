from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from openai import OpenAI


logger = logging.getLogger(__name__)


@dataclass
class OpenAIClientConfig:
    api_key: str
    model: str
    api_retry_attempts: int = 5
    api_retry_backoff: float = 1.0
    api_retry_backoff_max: float = 8.0
    api_retry_multiplier: float = 2.0


class OpenAIClient:
    """Minimal OpenAI client."""

    def __init__(self, config: OpenAIClientConfig) -> None:
        self._config = config
        self._client = OpenAI(api_key=config.api_key)

    def make_full_request(
        self,
        initial_prompt: str,
        *,
        json_output: bool = True,
    ) -> str:
        logger.info(
            "harvey.llm.request model=%s prompt_length=%d prompt_preview=%s",
            self._config.model,
            len(initial_prompt),
            self._truncate_for_log(initial_prompt),
        )

        try:
            raw_response, finish_reason = self._send_prompt(initial_prompt, self._config.model)
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

    def _send_prompt(self, prompt: str, model: str) -> tuple[str, str]:
        delay = max(self._config.api_retry_backoff, 0.5)
        max_delay = max(self._config.api_retry_backoff_max, delay)
        multiplier = max(self._config.api_retry_multiplier, 1.0)

        for attempt in range(1, self._config.api_retry_attempts + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
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
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            extracted = self._extract_json_document(response)
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

    @staticmethod
    def _extract_json_document(text: str) -> str | None:
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

