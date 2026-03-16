from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from mcp.server.fastmcp import FastMCP  # type: ignore[import]

from .container import container
from .logging import get_logger

settings = container.settings
mcp = FastMCP(
    settings.mcp_server_name,
    host=settings.http_host,
    port=settings.http_port,
)
logger = get_logger(__name__)

# Event names for structured logs
TOOL_INVOKED = "mcp.tool.invoked"
TOOL_COMPLETED = "mcp.tool.completed"
RESOURCE_REQUEST = "mcp.resource.request"
RESOURCE_RESPONSE = "mcp.resource.response"
RESOURCE_ID = "resource://pricing/specification"
VALID_SOLVERS = {"minizinc", "choco"}
INVALID_SOLVER_ERROR = "solver must be either 'minizinc' or 'choco'."

_PRICING2YAML_SPEC_PATH = (
    Path(__file__).resolve().parent.joinpath("docs", "pricing2YamlSpecification.md")
)
try:
    _PRICING2YAML_SPEC = _PRICING2YAML_SPEC_PATH.read_text(encoding="utf-8")
except FileNotFoundError:  # pragma: no cover - deployment safeguard
    _PRICING2YAML_SPEC = ""


@mcp.tool()
async def summary(
    pricing_url: Optional[str] = None,
    pricing_yaml: Optional[str] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Return contextual pricing summary data."""

    if not (pricing_url or pricing_yaml):
        raise ValueError(
            "Either pricing_url or pricing_yaml must be provided for summary."
        )
    logger.info(
        TOOL_INVOKED,
        tool="summary",
        pricing_url=pricing_url,
        has_pricing_yaml=bool(pricing_yaml),
        refresh=refresh,
    )

    result = await container.workflow.run_summary(
        url=pricing_url,
        yaml_content=pricing_yaml,
        refresh=refresh,
    )
    logger.info(TOOL_COMPLETED, tool="summary", result_keys=list(result.keys()))
    return result


@mcp.tool()
async def subscriptions(
    pricing_url: Optional[str] = None,
    pricing_yaml: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    solver: str = "minizinc",
    refresh: bool = False,
) -> Dict[str, Any]:
    """Enumerate subscriptions within the pricing configuration space."""

    if not (pricing_url or pricing_yaml):
        raise ValueError(
            "subscriptions requires pricing_url or pricing_yaml to define the configuration space."
        )

    if solver not in VALID_SOLVERS:
        raise ValueError(INVALID_SOLVER_ERROR)
    logger.info(
        TOOL_INVOKED,
        tool="subscriptions",
        pricing_url=pricing_url,
        has_pricing_yaml=bool(pricing_yaml),
        filters=filters,
        solver=solver,
        refresh=refresh,
    )

    result = await container.workflow.run_subscriptions(
        url=pricing_url or "",
        filters=filters,
        solver=solver,
        refresh=refresh,
        yaml_content=pricing_yaml,
    )
    # Log cardinality if present to make configuration-space size visible in logs
    cardinality = result.get("cardinality") if isinstance(result, dict) else None
    logger.info(TOOL_COMPLETED, tool="subscriptions", cardinality=cardinality)
    return result


@mcp.tool()
async def optimal(
    pricing_url: Optional[str] = None,
    pricing_yaml: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    solver: str = "minizinc",
    objective: str = "minimize",
    refresh: bool = False,
) -> Dict[str, Any]:
    """Compute the optimal subscription under the provided constraints."""

    if not (pricing_url or pricing_yaml):
        raise ValueError(
            "optimal requires pricing_url or pricing_yaml to run analysis."
        )

    if solver not in VALID_SOLVERS:
        raise ValueError(INVALID_SOLVER_ERROR)

    if objective not in {"minimize", "maximize"}:
        raise ValueError("objective must be 'minimize' or 'maximize'.")
    logger.info(
        TOOL_INVOKED,
        tool="optimal",
        pricing_url=pricing_url,
        has_pricing_yaml=bool(pricing_yaml),
        filters=filters,
        solver=solver,
        objective=objective,
        refresh=refresh,
    )

    result = await container.workflow.run_optimal(
        url=pricing_url or "",
        filters=filters,
        solver=solver,
        objective=objective,
        refresh=refresh,
        yaml_content=pricing_yaml,
    )
    logger.info(TOOL_COMPLETED, tool="optimal", keys=list(result.keys()))
    return result


@mcp.tool()
async def validate(
    pricing_url: Optional[str] = None,
    pricing_yaml: Optional[str] = None,
    solver: str = "minizinc",
    refresh: bool = False,
) -> Dict[str, Any]:
    """Validate the pricing configuration against the selected solver."""

    if not (pricing_url or pricing_yaml):
        raise ValueError(
            "validate requires pricing_url or pricing_yaml to run analysis."
        )

    if solver not in VALID_SOLVERS:
        raise ValueError(INVALID_SOLVER_ERROR)

    logger.info(
        TOOL_INVOKED,
        tool="validate",
        pricing_url=pricing_url,
        has_pricing_yaml=bool(pricing_yaml),
        solver=solver,
        refresh=refresh,
    )

    result = await container.workflow.run_validation(
        url=pricing_url,
        solver=solver,
        refresh=refresh,
        yaml_content=pricing_yaml,
    )

    validation_status = None
    if isinstance(result, dict):
        validation_status = result.get("result", {}).get("valid")

    logger.info(TOOL_COMPLETED, tool="validate", valid=validation_status)
    return result


@mcp.tool(name="iPricing")
async def ipricing(
    pricing_url: Optional[str] = None,
    pricing_yaml: Optional[str] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Return the canonical Pricing2Yaml (iPricing) document."""

    if not (pricing_url or pricing_yaml):
        raise ValueError(
            "iPricing requires pricing_url or pricing_yaml to produce an output."
        )

    logger.info(
        TOOL_INVOKED,
        tool="iPricing",
        pricing_url=pricing_url,
        has_pricing_yaml=bool(pricing_yaml),
        refresh=refresh,
    )

    result = await container.workflow.get_ipricing(
        url=pricing_url,
        yaml_content=pricing_yaml,
        refresh=refresh,
    )
    yaml_content = result.get("pricing_yaml", "")
    pricing_yaml_len = len(yaml_content) if isinstance(result, dict) else None
    logger.info(TOOL_COMPLETED, tool="iPricing", pricing_yaml_length=pricing_yaml_len)
    return result

@mcp.resource("resource://pricing/specification")
async def pricing2yaml_specification() -> str:
    """Expose the Pricing2Yaml specification excerpt as a reusable resource."""
    logger.info(RESOURCE_REQUEST, resource=RESOURCE_ID)
    logger.info(RESOURCE_RESPONSE, resource=RESOURCE_ID, length=len(_PRICING2YAML_SPEC))
    return _PRICING2YAML_SPEC


@mcp.tool()
async def min_time(
    capacity_goal: int,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Compute the minimum time to reach a given API call capacity goal.

    Either rate, quota, or both must be provided.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    Returns: {"capacity_goal": int, "min_time": str}
    """
    logger.info(TOOL_INVOKED, tool="min_time", capacity_goal=capacity_goal)
    result = await container.prime4api_client.min_time(
        capacity_goal=capacity_goal,
        rate=rate,
        quota=quota,
    )
    logger.info(TOOL_COMPLETED, tool="min_time", min_time=result.get("min_time"))
    return result


@mcp.tool()
async def capacity_at(
    time: str,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Compute the accumulated capacity available at a specific time instant.

    Either rate, quota, or both must be provided.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    Returns: {"time": str, "capacity": number}
    """
    logger.info(TOOL_INVOKED, tool="capacity_at", time=time)
    result = await container.prime4api_client.capacity_at(
        time=time, rate=rate, quota=quota,
    )
    logger.info(TOOL_COMPLETED, tool="capacity_at", capacity=result.get("capacity"))
    return result


@mcp.tool()
async def capacity_during(
    end_instant: str,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
    start_instant: str = "0ms",
) -> Dict[str, Any]:
    """Compute the capacity generated during a defined time interval.

    Either rate, quota, or both must be provided.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    Returns: {"start_instant": str, "end_instant": str, "capacity": number}
    """
    logger.info(TOOL_INVOKED, tool="capacity_during", end_instant=end_instant, start_instant=start_instant)
    result = await container.prime4api_client.capacity_during(
        end_instant=end_instant, rate=rate, quota=quota, start_instant=start_instant,
    )
    logger.info(TOOL_COMPLETED, tool="capacity_during", capacity=result.get("capacity"))
    return result


@mcp.tool()
async def quota_exhaustion_threshold(
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Compute the minimum time to exhaust each quota constraint at maximum rate.

    Either rate, quota, or both must be provided.
    Returns: {"thresholds": [{"quota": {...}, "exhaustion_threshold": str}]}
    """
    logger.info(TOOL_INVOKED, tool="quota_exhaustion_threshold")
    result = await container.prime4api_client.quota_exhaustion_threshold(rate=rate, quota=quota)
    logger.info(TOOL_COMPLETED, tool="quota_exhaustion_threshold")
    return result


@mcp.tool()
async def rates(
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Retrieve the effective maximum consumption rates after pruning redundant limits.

    Either rate, quota, or both must be provided.
    Returns: {"rates": [{"value": number, "unit": str, "period": str}]}
    """
    logger.info(TOOL_INVOKED, tool="rates")
    result = await container.prime4api_client.rates(rate=rate, quota=quota)
    logger.info(TOOL_COMPLETED, tool="rates")
    return result


@mcp.tool()
async def quotas(
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Retrieve the effective upper-limit quota boundaries after pruning redundant limits.

    Either rate, quota, or both must be provided.
    Returns: {"quotas": [{"value": number, "unit": str, "period": str}]}
    """
    logger.info(TOOL_INVOKED, tool="quotas")
    result = await container.prime4api_client.quotas(rate=rate, quota=quota)
    logger.info(TOOL_COMPLETED, tool="quotas")
    return result


@mcp.tool()
async def limits(
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Retrieve all combined active limits (rates and quotas).

    Either rate, quota, or both must be provided.
    Returns: {"rates": [...], "quotas": [...]}
    """
    logger.info(TOOL_INVOKED, tool="limits")
    result = await container.prime4api_client.limits(rate=rate, quota=quota)
    logger.info(TOOL_COMPLETED, tool="limits")
    return result


@mcp.tool()
async def idle_time_period(
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
) -> Dict[str, Any]:
    """Compute the idle/blocked time after exhausting each quota at maximum speed.

    Either rate, quota, or both must be provided.
    Returns: {"idle_times": [{"quota": {...}, "idle_time": str}]}
    """
    logger.info(TOOL_INVOKED, tool="idle_time_period")
    result = await container.prime4api_client.idle_time_period(rate=rate, quota=quota)
    logger.info(TOOL_COMPLETED, tool="idle_time_period")
    return result


@mcp.tool()
async def evaluate_api_datasheet(
    datasheet_source: str,
    plan_name: str,
    operation: str,
    operation_params: Optional[Dict[str, Any]] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate an API datasheet to resolve dynamic API constraints.

    Returns: {"operation": str, "operation_params": dict, "results": list}
    """
    logger.info(TOOL_INVOKED, tool="evaluate_api_datasheet", plan_name=plan_name, operation=operation)
    result = await container.prime4api_client.evaluate_api_datasheet(
        datasheet_source=datasheet_source,
        plan_name=plan_name,
        operation=operation,
        operation_params=operation_params,
        endpoint_path=endpoint_path,
        alias=alias,
    )
    logger.info(TOOL_COMPLETED, tool="evaluate_api_datasheet")
    return result


def main() -> None:
    mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
