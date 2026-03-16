from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession  # type: ignore[import]
from mcp.client.stdio import StdioServerParameters, stdio_client  # type: ignore[import]
from mcp.client.sse import sse_client  # type: ignore[import]

from ..config import get_settings
from ..logging import get_logger
from ..pricing_context import pricing_context_db
from ..stream import stream
from ..file_manager import FileManager

from sse_starlette import JSONServerSentEvent


logger = get_logger(__name__)


class MCPClientError(Exception):
    """Raised when the MCP server cannot fulfil or process a request."""


class MCPWorkflowClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.transport = settings.mcp_transport

        self._exit_stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._connect_lock = asyncio.Lock()
        self._file_manager = FileManager(settings.harvey_static_dir)

        if self.transport == "stdio":
            self._module = settings.mcp_server_module
            if not self._module:
                raise ValueError("MCP server module must be configured via MCP_SERVER_MODULE")

            self._python_executable = settings.mcp_python_executable or sys.executable
            self._extra_python_paths = self._parse_extra_paths(settings.mcp_extra_python_paths)
            self._server_src, self._inject_server_path = self._locate_mcp_server_sources()
            if self._server_src:
                logger.info("harvey.mcp.server.path", path=str(self._server_src))
            else:
                logger.info("harvey.mcp.server.path_missing")
            self._env = self._build_environment()
        
        elif self.transport == "sse":
            self._url = settings.mcp_server_url
            if not self._url:
                raise ValueError("MCP server URL must be configured via MCP_SERVER_URL for SSE transport")
            # Std/local vars not needed
            self._module = "remote-sse" 
        
        else:
             raise ValueError(f"Unknown MCP transport: {self.transport}")

    async def ensure_connected(self) -> ClientSession:
        if self._session is not None:
            return self._session

        async with self._connect_lock:
            if self._session is not None:
                return self._session

            logger.info("harvey.mcp.launch.start", transport=self.transport, module=self._module)
            exit_stack = AsyncExitStack()
            try:
                if self.transport == "stdio":
                    params = StdioServerParameters(
                        command=self._python_executable,
                        args=["-m", self._module],
                        env=self._env,
                    )
                    reader, writer = await exit_stack.enter_async_context(stdio_client(params))
                elif self.transport == "sse":
                    reader, writer = await exit_stack.enter_async_context(sse_client(self._url))
                
                session = await exit_stack.enter_async_context(ClientSession(reader, writer))
                await session.initialize()

                self._exit_stack = exit_stack
                self._session = session
                logger.info("harvey.mcp.launch.success", transport=self.transport, module=self._module)
                return session
            except Exception as exc:  # pragma: no cover - subprocess launch failure
                logger.error("harvey.mcp.launch.failed", transport=self.transport, error=str(exc))
                await exit_stack.aclose()
                raise MCPClientError("Failed to start/connect the MCP server") from exc

    async def aclose(self) -> None:
        if self._exit_stack is None:
            return
        try:
            await self._exit_stack.aclose()
        finally:
            self._exit_stack = None
            self._session = None
            logger.info("harvey.mcp.launch.stopped", module=self._module)

    async def run_summary(
        self,
        *,
        url: Optional[str],
        yaml_content: Optional[str],
        refresh: bool,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "pricing_url": url,
            "pricing_yaml": yaml_content,
            "refresh": refresh,
        }
        return await self._call_tool("summary", arguments)

    async def run_ipricing(
        self,
        *,
        url: Optional[str],
        yaml_content: Optional[str],
        refresh: bool,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "pricing_url": url,
            "pricing_yaml": yaml_content,
            "refresh": refresh,
        }
        result =  await self._call_tool("iPricing", arguments)
        yaml_content = result.get("pricing_yaml", "")
        self._upload_transformed_pricing(url, yaml_content)
        await self._notify_pricing_upload(url, yaml_content)
        return result

    async def run_subscriptions(
        self,
        *,
        url: str,
        filters: Optional[Dict[str, Any]],
        solver: str,
        refresh: bool,
        yaml_content: Optional[str],
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "pricing_url": url or None,
            "pricing_yaml": yaml_content,
            "filters": filters,
            "solver": solver,
            "refresh": refresh,
        }
        return await self._call_tool("subscriptions", arguments)

    async def run_validate(
        self,
        *,
        url: Optional[str],
        yaml_content: Optional[str],
        solver: str,
        refresh: bool,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "pricing_url": url,
            "pricing_yaml": yaml_content,
            "solver": solver,
            "refresh": refresh,
        }
        return await self._call_tool("validate", arguments)

    async def run_optimal(
        self,
        *,
        url: str,
        filters: Optional[Dict[str, Any]],
        solver: str,
        objective: str,
        refresh: bool,
        yaml_content: Optional[str],
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "pricing_url": url or None,
            "pricing_yaml": yaml_content,
            "filters": filters,
            "solver": solver,
            "objective": objective,
            "refresh": refresh,
        }
        return await self._call_tool("optimal", arguments)

    async def run_min_time(
        self,
        *,
        capacity_goal: int,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {"capacity_goal": capacity_goal}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("min_time", arguments)

    async def run_capacity_at(
        self,
        *,
        time: str,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {"time": time}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("capacity_at", arguments)

    async def run_capacity_during(
        self,
        *,
        end_instant: str,
        start_instant: str = "0ms",
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "end_instant": end_instant,
            "start_instant": start_instant,
        }
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("capacity_during", arguments)

    async def run_quota_exhaustion_threshold(
        self,
        *,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("quota_exhaustion_threshold", arguments)

    async def run_rates(
        self,
        *,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("rates", arguments)

    async def run_quotas(
        self,
        *,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("quotas", arguments)

    async def run_limits(
        self,
        *,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("limits", arguments)

    async def run_idle_time_period(
        self,
        *,
        rate: Optional[Any] = None,
        quota: Optional[Any] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {}
        if rate is not None:
            arguments["rate"] = rate
        if quota is not None:
            arguments["quota"] = quota
        return await self._call_tool("idle_time_period", arguments)

    async def run_evaluate_api_datasheet(
        self,
        *,
        datasheet_source: str,
        plan_name: str,
        operation: str,
        operation_params: Optional[Dict[str, Any]] = None,
        endpoint_path: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "datasheet_source": datasheet_source,
            "plan_name": plan_name,
            "operation": operation,
        }
        if operation_params is not None:
            arguments["operation_params"] = operation_params
        if endpoint_path is not None:
            arguments["endpoint_path"] = endpoint_path
        if alias is not None:
            arguments["alias"] = alias
        return await self._call_tool("evaluate_api_datasheet", arguments)

    async def get_prompt_messages(self, prompt_name: str) -> List[Dict[str, str]]:
        session = await self.ensure_connected()
        try:
            response = await session.get_prompt(prompt_name)
        except Exception as exc:  # pragma: no cover - protocol failure
            logger.error("harvey.mcp.prompt.failed", prompt=prompt_name, error=str(exc))
            raise MCPClientError(f"Failed to fetch prompt '{prompt_name}'") from exc
        return self._normalise_prompt_messages(response)

    async def read_resource_text(self, resource_id: str) -> str:
        session = await self.ensure_connected()
        try:
            response = await session.read_resource(resource_id)
        except Exception as exc:  # pragma: no cover - protocol failure
            logger.error("harvey.mcp.resource.failed", resource=resource_id, error=str(exc))
            raise MCPClientError(f"Failed to read resource '{resource_id}'") from exc
        return self._extract_text_content(response)

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = await self.ensure_connected()
        safe_arguments = dict(arguments)
        if safe_arguments.get("pricing_yaml"):
            safe_arguments["pricing_yaml"] = "<provided>"
        logger.info("harvey.mcp.tool.request", tool=name, arguments=safe_arguments)

        try:
            response = await session.call_tool(name, arguments or {})
        except Exception as exc:  # pragma: no cover - protocol failure
            logger.error("harvey.mcp.tool.failed", tool=name, error=str(exc))
            raise MCPClientError(f"Tool '{name}' failed") from exc

        if getattr(response, "isError", False):
            error_items = self._extract_content_items(response)
            error_text = " | ".join(
                item.get("text", "")
                for item in error_items
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
            )
            logger.error("harvey.mcp.tool.server_error", tool=name, error=error_text)
            raise MCPClientError(f"Tool '{name}' returned an error: {error_text}")

        payload = self._extract_json_payload(name, response)
        logger.info("harvey.mcp.tool.success", tool=name)
        return payload

    def _build_environment(self) -> Dict[str, str]:
        env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH"}}
        python_paths: List[str] = []
        if self._inject_server_path and self._server_src and self._server_src.exists():
            python_paths.append(str(self._server_src))
        python_paths.extend(self._extra_python_paths)

        existing = os.environ.get("PYTHONPATH")
        if existing:
            python_paths.append(existing)

        if python_paths:
            env["PYTHONPATH"] = os.pathsep.join(path for path in python_paths if path)
        return env

    def _locate_mcp_server_sources(self) -> tuple[Optional[Path], bool]:
        repo_path = self._find_repo_server_path()
        if repo_path:
            return repo_path, True

        root_module = self._module.split(".")[0]
        spec = importlib.util.find_spec(root_module)
        if spec is None:
            return None, False
        if spec.submodule_search_locations:
            first_location = next(iter(spec.submodule_search_locations), None)
            if first_location:
                path = Path(first_location)
                if path.exists():
                    return path, False
        origin = getattr(spec, "origin", None)
        if origin:
            path = Path(origin).parent
            if path.exists():
                return path, False
        return None, False

    @staticmethod
    def _find_repo_server_path() -> Optional[Path]:
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent.joinpath("mcp_server", "src")
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _parse_extra_paths(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        segments = [segment.strip() for segment in raw.split(os.pathsep)]
        return [segment for segment in segments if segment]

    def _extract_json_payload(self, tool_name: str, response: Any) -> Dict[str, Any]:
        content_items = self._extract_content_items(response)
        json_chunks: List[Dict[str, Any]] = []
        text_chunks: List[str] = []
        for item in content_items:
            payload = self._json_payload_from_item(item)
            if payload is not None:
                json_chunks.append(payload)
                continue

            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str):
                text_chunks.append(text)

        if json_chunks:
            return self._merge_json_payloads(json_chunks)

        if text_chunks:
            joined_text = "".join(text_chunks)
            parsed = self._try_parse_json(joined_text)
            if isinstance(parsed, dict):
                return parsed

        logger.error("harvey.mcp.tool.no_json", tool=tool_name, raw=content_items)
        raise MCPClientError(f"Tool '{tool_name}' did not return JSON content")

    def _json_payload_from_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        item_type = item.get("type")
        if item_type == "json":
            payload = item.get("json")
            if isinstance(payload, dict):
                return payload
            if payload is not None:
                return {"value": payload}
        if item_type == "text":
            text = item.get("text")
            if isinstance(text, str):
                parsed = self._try_parse_json(text)
                if isinstance(parsed, dict):
                    return parsed
        return None

    def _merge_json_payloads(self, payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for payload in payloads:
            self._deep_merge_dicts(merged, payload)
        return merged

    def _deep_merge_dicts(self, base: Dict[str, Any], incoming: Dict[str, Any]) -> None:
        for key, value in incoming.items():
            if key in base:
                base[key] = self._merge_values(base[key], value)
            else:
                base[key] = value

    def _merge_values(self, current: Any, new_value: Any) -> Any:
        if isinstance(current, dict) and isinstance(new_value, dict):
            merged: Dict[str, Any] = dict(current)
            self._deep_merge_dicts(merged, new_value)
            return merged
        if isinstance(current, list) and isinstance(new_value, list):
            return current + new_value
        if isinstance(current, list):
            return current + [new_value]
        if isinstance(new_value, list):
            return [current] + new_value
        if current == new_value:
            return current
        return new_value

    @staticmethod
    def _try_parse_json(text: str) -> Optional[Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _normalise_prompt_messages(self, response: Any) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if hasattr(response, "model_dump"):
            raw_messages = response.model_dump().get("messages", [])
        else:
            raw_messages = getattr(response, "messages", [])

        for message in raw_messages:
            if hasattr(message, "model_dump"):
                message = message.model_dump()
            if not isinstance(message, dict):
                continue
            role = message.get("role") or "system"
            content = message.get("content")
            text = self._format_message_content(content)
            messages.append({"role": role, "content": text})
        return messages

    def _extract_text_content(self, response: Any) -> str:
        texts: List[str] = []
        for item in self._extract_content_items(response):
            text = self._text_from_content_item(item)
            if text:
                texts.append(text)
        return "\n".join(texts).strip()

    def _text_from_content_item(self, item: Dict[str, Any]) -> str:
        text = item.get("text")
        if isinstance(text, str):
            return text
        if isinstance(text, list):
            parts = [part for part in text if isinstance(part, str)]
            if parts:
                return "\n".join(parts)
        value = item.get("value")
        if isinstance(value, str):
            return value
        json_value = item.get("json")
        if isinstance(json_value, str):
            return json_value
        if isinstance(json_value, dict):
            try:
                return json.dumps(json_value, ensure_ascii=False)
            except TypeError:  # pragma: no cover - non-serialisable
                return str(json_value)
        return ""

    def _extract_content_items(self, payload: Any) -> List[Dict[str, Any]]:
        normalised: List[Dict[str, Any]] = []
        for item in self._iter_raw_content(payload):
            converted = self._normalise_content_entry(item)
            if converted:
                normalised.append(converted)
        return normalised

    def _iter_raw_content(self, payload: Any) -> List[Any]:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump()
            return data.get("content") or data.get("contents") or []
        return getattr(payload, "content", None) or getattr(payload, "contents", [])

    def _normalise_content_entry(self, item: Any) -> Optional[Dict[str, Any]]:
        if item is None:
            return None
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if isinstance(item, dict):
            return item

        extracted: Dict[str, Any] = {}
        for attr in ("type", "text", "json", "value"):
            value = getattr(item, attr, None)
            if value is not None:
                extracted[attr] = value
        return extracted or None

    def _format_message_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return self._format_list_content(content)
        if isinstance(content, dict):
            return self._format_dict_content(content)
        if hasattr(content, "model_dump"):
            return self._format_message_content(content.model_dump())
        text_value = getattr(content, "text", None)
        if text_value is not None:
            return str(text_value)
        return str(content)

    def _format_list_content(self, items: List[Any]) -> str:
        parts = [self._format_message_content(item) for item in items]
        return "\n".join(part for part in parts if part)

    def _format_dict_content(self, data: Dict[str, Any]) -> str:
        text_value = data.get("text")
        if isinstance(text_value, str):
            return text_value

        if "json" in data:
            try:
                return json.dumps(data["json"], ensure_ascii=False)
            except TypeError:  # pragma: no cover - non-serialisable json field
                return str(data["json"])

        if "value" in data:
            return str(data["value"])

        nested = [
            self._format_message_content(value) for value in data.values() if value is not None
        ]
        return "\n".join(part for part in nested if part)


    def _upload_transformed_pricing(self, pricing_url: str, yaml_content: str):

        if pricing_url not in pricing_context_db:
            logger.error("URL \"%s\" could not be saved", pricing_url)
            raise Exception(f"Cannot locate {pricing_url} in context")
        harvey_id = pricing_context_db[pricing_url].id
        filename = f"{harvey_id}.yaml"
        self._file_manager.write_file(filename, yaml_content.encode())
        logger.info("Saving extracted iPricing (URL: \"%s\") to %s", pricing_url, harvey_id)


    async def _notify_pricing_upload(self, pricing_url: str, yaml_content: str):
        logger.info("Sending SSE completion event of %s", pricing_url)
        await stream.asend(
            JSONServerSentEvent(
                event="url_transform",
                data={
                    "id": pricing_context_db[pricing_url].id,
                    "pricing_url": pricing_context_db[pricing_url].url,
                    "yaml_content": yaml_content,
                },
            )
    )
