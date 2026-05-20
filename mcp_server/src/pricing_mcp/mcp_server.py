from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

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

TOOL_INVOKED = "mcp.tool.invoked"
TOOL_COMPLETED = "mcp.tool.completed"


# ── Bounded-rate tools (no datasheet) ─────────────────────────────────────────

@mcp.tool()
async def min_time(
    capacity_goal: int,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Compute the minimum time to reach a given API call capacity goal.

    Either rate, quota, or both must be provided.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    provider_mode: if True (default), capacity is counted at the end of each window (provider semantics).
    Returns: {"capacity_goal": int, "min_time": str}
    """
    logger.info(TOOL_INVOKED, tool="min_time", capacity_goal=capacity_goal)
    result = await container.prime4api_client.min_time(
        capacity_goal=capacity_goal,
        rate=rate,
        quota=quota,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="min_time", min_time=result.get("min_time"))
    return result


@mcp.tool()
async def capacity_at(
    time: str,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Compute the accumulated capacity available at a specific time instant.

    Either rate, quota, or both must be provided.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    provider_mode: if True (default), capacity is counted at the end of each window (provider semantics).
    Returns: {"time": str, "capacity": number}
    """
    logger.info(TOOL_INVOKED, tool="capacity_at", time=time)
    result = await container.prime4api_client.capacity_at(
        time=time, rate=rate, quota=quota, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="capacity_at", capacity=result.get("capacity"))
    return result


@mcp.tool()
async def capacity_during(
    end_instant: str,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
    start_instant: str = "0ms",
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Compute the capacity generated during a defined time interval.

    Either rate, quota, or both must be provided.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    provider_mode: if True (default), capacity is counted at the end of each window (provider semantics).
    Returns: {"start_instant": str, "end_instant": str, "capacity": number}
    """
    logger.info(TOOL_INVOKED, tool="capacity_during", end_instant=end_instant, start_instant=start_instant)
    result = await container.prime4api_client.capacity_during(
        end_instant=end_instant, rate=rate, quota=quota, start_instant=start_instant, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="capacity_during", capacity=result.get("capacity"))
    return result


@mcp.tool()
async def quota_exhaustion_threshold(
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Compute the minimum time to exhaust each quota constraint at maximum rate.

    Either rate, quota, or both must be provided.
    provider_mode: if True (default), provider-centric semantics.
    Returns: {"thresholds": [{"quota": {...}, "exhaustion_threshold": str}]}
    """
    logger.info(TOOL_INVOKED, tool="quota_exhaustion_threshold")
    result = await container.prime4api_client.quota_exhaustion_threshold(rate=rate, quota=quota, provider_mode=provider_mode)
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
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Compute the idle/blocked time after exhausting each quota at maximum speed.

    Either rate, quota, or both must be provided.
    provider_mode: if True (default), provider-centric semantics.
    Returns: {"idle_times": [{"quota": {...}, "idle_time": str}]}
    """
    logger.info(TOOL_INVOKED, tool="idle_time_period")
    result = await container.prime4api_client.idle_time_period(rate=rate, quota=quota, provider_mode=provider_mode)
    logger.info(TOOL_COMPLETED, tool="idle_time_period")
    return result


@mcp.tool()
async def capacity_curve_inflection(
    time_interval: str,
    rate: Optional[Any] = None,
    quota: Optional[Any] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Generate an interactive inflection-point capacity curve chart from rate/quota objects.

    BoundedRate only (requires at least one quota). Returns an HTML document wrapped in {"html": "..."}.
    time_interval examples: '1h', '1day', '1month'.
    Rate / Quota shape: {"value": int, "unit": str, "period": str}
    provider_mode: if True (default), provider-centric semantics.
    """
    logger.info(TOOL_INVOKED, tool="capacity_curve_inflection", time_interval=time_interval)
    html = await container.prime4api_client.capacity_curve_inflection(
        time_interval=time_interval, rate=rate, quota=quota, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="capacity_curve_inflection")
    return {"html": html}


# ── Datasheet calculation tools ───────────────────────────────────────────────

@mcp.tool()
async def datasheet_min_time(
    datasheet_source: str,
    capacity_goal: int,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Calculate minimum time to reach a capacity goal using a datasheet.

    datasheet_source: uploaded alias (e.g. "uploaded://datasheet") or HTTP URL.
    provider_mode: if True (default), provider-centric semantics.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_min_time", capacity_goal=capacity_goal,
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_min_time(
        datasheet_source=datasheet_source, capacity_goal=capacity_goal, plan_name=plan_name,
        endpoint_path=endpoint_path, alias=alias, capacity_unit=capacity_unit,
        capacity_request_factor=capacity_request_factor, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_min_time")
    return result


@mcp.tool()
async def datasheet_capacity_at(
    datasheet_source: str,
    time: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Calculate capacity available at a time instant using a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    time: e.g. '1h', '5day', '1month'.
    provider_mode: if True (default), provider-centric semantics.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_capacity_at", time=time,
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_capacity_at(
        datasheet_source=datasheet_source, time=time, plan_name=plan_name,
        endpoint_path=endpoint_path, alias=alias, capacity_unit=capacity_unit,
        capacity_request_factor=capacity_request_factor, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_capacity_at")
    return result


@mcp.tool()
async def datasheet_capacity_during(
    datasheet_source: str,
    end_instant: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    start_instant: str = "0ms",
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Calculate capacity generated in a time window using a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    provider_mode: if True (default), provider-centric semantics.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_capacity_during", end_instant=end_instant,
                start_instant=start_instant, plan_name=plan_name)
    result = await container.prime4api_client.datasheet_capacity_during(
        datasheet_source=datasheet_source, end_instant=end_instant, plan_name=plan_name,
        endpoint_path=endpoint_path, alias=alias, start_instant=start_instant,
        capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_capacity_during")
    return result


@mcp.tool()
async def datasheet_quota_exhaustion_threshold(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Any] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Calculate time to exhaust each quota at maximum rate using a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    provider_mode: if True (default), provider-centric semantics.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_quota_exhaustion_threshold",
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_quota_exhaustion_threshold(
        datasheet_source=datasheet_source, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_quota_exhaustion_threshold")
    return result


@mcp.tool()
async def datasheet_idle_time_period(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Any] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Calculate idle/blocked time after quota exhaustion using a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    provider_mode: if True (default), provider-centric semantics.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_idle_time_period",
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_idle_time_period(
        datasheet_source=datasheet_source, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_idle_time_period")
    return result


@mcp.tool()
async def datasheet_rates(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Any] = None,
) -> Dict[str, Any]:
    """Extract effective rate limits from a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_rates", plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_rates(
        datasheet_source=datasheet_source, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_rates")
    return result


@mcp.tool()
async def datasheet_quotas(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Any] = None,
) -> Dict[str, Any]:
    """Extract effective quota limits from a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_quotas", plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_quotas(
        datasheet_source=datasheet_source, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_quotas")
    return result


@mcp.tool()
async def datasheet_limits(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Any] = None,
) -> Dict[str, Any]:
    """Extract combined rate and quota limits from a datasheet.

    datasheet_source: uploaded alias or HTTP URL.
    Returns results grouped by plan/endpoint/dimension.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_limits", plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_limits(
        datasheet_source=datasheet_source, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_limits")
    return result


@mcp.tool()
async def datasheet_capacity_curve_inflection(
    datasheet_source: str,
    time_interval: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Generate an interactive inflection-point capacity curve chart from a datasheet.

    Returns an HTML document (Plotly) wrapped in {"html": "<html...>"}.
    time_interval examples: '1h', '1day', '1month'.
    capacity_unit filters the chart to one dimension such as "emails".
    capacity_request_factor represents units per API call, such as emails per call.
    provider_mode: if True (default), provider-centric semantics.
    """
    logger.info(TOOL_INVOKED, tool="datasheet_capacity_curve_inflection",
                time_interval=time_interval, plan_name=plan_name, endpoint_path=endpoint_path)
    html = await container.prime4api_client.datasheet_capacity_curve_inflection(
        datasheet_source=datasheet_source, time_interval=time_interval, plan_name=plan_name,
        endpoint_path=endpoint_path, alias=alias, capacity_unit=capacity_unit,
        capacity_request_factor=capacity_request_factor, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_capacity_curve_inflection")
    return {"html": html}


# ── Datasheet navigation tools ────────────────────────────────────────────────

@mcp.tool()
async def datasheet_nav_plans(
    datasheet_source: str,
) -> Dict[str, Any]:
    """List all plan names available in the datasheet.

    Use this before calc tools when plan names are unknown.
    Returns: {"plans": ["free", "pro", ...]}
    """
    logger.info(TOOL_INVOKED, tool="datasheet_nav_plans")
    result = await container.prime4api_client.datasheet_nav_plans(
        datasheet_source=datasheet_source,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_nav_plans")
    return result


@mcp.tool()
async def datasheet_nav_endpoints(
    datasheet_source: str,
    plan_name: Optional[str] = None,
) -> Dict[str, Any]:
    """List endpoint paths available in the datasheet, optionally filtered by plan.

    Returns: {"endpoints": ["/mail/send", ...]}
    """
    logger.info(TOOL_INVOKED, tool="datasheet_nav_endpoints", plan_name=plan_name)
    result = await container.prime4api_client.datasheet_nav_endpoints(
        datasheet_source=datasheet_source,
        plan_name=plan_name,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_nav_endpoints")
    return result


@mcp.tool()
async def datasheet_nav_crf_ranges(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the min/max CRF range per capacity unit for an endpoint.

    Call this ALONGSIDE a calc tool when the user has not specified their batch size,
    so the answer phase can contextualise the 3 automatic scenarios meaningfully.
    Returns: [{"unit": "emails", "min": 1, "max": 1000, "description": "..."}, ...]
    """
    logger.info(TOOL_INVOKED, tool="datasheet_nav_crf_ranges",
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_nav_crf_ranges(
        datasheet_source=datasheet_source,
        plan_name=plan_name,
        endpoint_path=endpoint_path,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_nav_crf_ranges")
    return result


@mcp.tool()
async def datasheet_nav_capacity_units(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
) -> Dict[str, Any]:
    """List the available capacity units for a plan/endpoint (e.g., 'emails', 'MBs').

    Returns: {"capacity_units": ["emails", "MBs"]}
    """
    logger.info(TOOL_INVOKED, tool="datasheet_nav_capacity_units",
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_nav_capacity_units(
        datasheet_source=datasheet_source,
        plan_name=plan_name,
        endpoint_path=endpoint_path,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_nav_capacity_units")
    return result


@mcp.tool()
async def datasheet_nav_aliases(
    datasheet_source: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
) -> Dict[str, Any]:
    """List aliases defined for an endpoint. Field absent in result if no aliases exist.

    Returns: {"aliases": ["GET", "POST"]} or {}
    """
    logger.info(TOOL_INVOKED, tool="datasheet_nav_aliases",
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.datasheet_nav_aliases(
        datasheet_source=datasheet_source,
        plan_name=plan_name,
        endpoint_path=endpoint_path,
    )
    logger.info(TOOL_COMPLETED, tool="datasheet_nav_aliases")
    return result


# ── Demand evaluation tools ───────────────────────────────────────────────────

@mcp.tool()
async def demand_evaluation(
    datasheet_source: str,
    demands: List[Dict[str, Any]],
    time_interval: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Evaluate whether API plan constraints satisfy custom demand patterns.

    demands: list of demand patterns, each with:
      - label: str (name for this scenario, e.g. "Light Usage")
      - rate: optional {"value": float, "unit": str, "period": str}
      - quota: optional [{"value": float, "unit": str, "period": str}]
      - duration: optional str (e.g. "1month" — creates an implicit quota)
      - demand_crf: optional dict of units per call (e.g. {"emails": 2})
    time_interval: comparison horizon (e.g. "1month", "1day").
    provider_mode: if True (default), provider-centric semantics.

    Returns per-plan/endpoint verdict: YES / NO / DEPENDS for each demand scenario.
    """
    logger.info(TOOL_INVOKED, tool="demand_evaluation", time_interval=time_interval,
                plan_name=plan_name, endpoint_path=endpoint_path)
    result = await container.prime4api_client.demand_evaluation(
        datasheet_source=datasheet_source, demands=demands, time_interval=time_interval,
        plan_name=plan_name, endpoint_path=endpoint_path, alias=alias,
        capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="demand_evaluation")
    return result


@mcp.tool()
async def demand_evaluation_chart(
    datasheet_source: str,
    demands: List[Dict[str, Any]],
    time_interval: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    capacity_unit: Optional[str] = None,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Generate an interactive demand evaluation chart (plan capacity vs demand curves).

    Same parameters as demand_evaluation.
    provider_mode: if True (default), provider-centric semantics.
    Returns an HTML document (Plotly) wrapped in {"html": "<html...>"}.
    """
    logger.info(TOOL_INVOKED, tool="demand_evaluation_chart", time_interval=time_interval,
                plan_name=plan_name)
    html = await container.prime4api_client.demand_evaluation_chart(
        datasheet_source=datasheet_source, demands=demands, time_interval=time_interval,
        plan_name=plan_name, endpoint_path=endpoint_path, alias=alias,
        capacity_unit=capacity_unit, capacity_request_factor=capacity_request_factor,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="demand_evaluation_chart")
    return {"html": html}


# ── Budget recommendation tools ───────────────────────────────────────────────

@mcp.tool()
async def budget_recommendation(
    datasheet_source: str,
    desired_capacity: float,
    capacity_unit: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    max_budget: Optional[float] = None,
    no_overage: bool = False,
    capacity_request_factor: Optional[Union[float, str]] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Recommend the best plans for a desired capacity goal with cost analysis.

    desired_capacity: target number of units to reach within one billing period.
    capacity_unit: unit for desired_capacity (e.g. "requests", "emails").
    max_budget: optional — plans exceeding this total cost are marked affordable=False.
    no_overage: if True, only plans whose included quota covers desired_capacity.
    provider_mode: if True (default), provider-centric semantics.

    Returns per-plan: base_cost, overage_cost, total_cost, affordable, time_to_capacity.
    """
    logger.info(TOOL_INVOKED, tool="budget_recommendation", desired_capacity=desired_capacity,
                capacity_unit=capacity_unit, plan_name=plan_name)
    result = await container.prime4api_client.budget_recommendation(
        datasheet_source=datasheet_source, desired_capacity=desired_capacity,
        capacity_unit=capacity_unit, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, max_budget=max_budget, no_overage=no_overage,
        capacity_request_factor=capacity_request_factor, provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="budget_recommendation")
    return result


@mcp.tool()
async def budget_recommendation_chart(
    datasheet_source: str,
    desired_capacity: float,
    capacity_unit: str,
    plan_name: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    alias: Optional[str] = None,
    max_budget: Optional[float] = None,
    no_overage: bool = False,
    capacity_request_factor: Optional[Union[float, str]] = None,
    time_horizon: Optional[str] = None,
    provider_mode: bool = True,
) -> Dict[str, Any]:
    """Generate an interactive budget recommendation chart (cost vs capacity + capacity vs time).

    Same parameters as budget_recommendation, plus:
    time_horizon: optional override for the time axis (e.g. "2h", "1day"). Auto-zooms if omitted.
    provider_mode: if True (default), provider-centric semantics.

    Returns an HTML document (Plotly) wrapped in {"html": "<html...>"}.
    """
    logger.info(TOOL_INVOKED, tool="budget_recommendation_chart", desired_capacity=desired_capacity,
                capacity_unit=capacity_unit, plan_name=plan_name)
    html = await container.prime4api_client.budget_recommendation_chart(
        datasheet_source=datasheet_source, desired_capacity=desired_capacity,
        capacity_unit=capacity_unit, plan_name=plan_name, endpoint_path=endpoint_path,
        alias=alias, max_budget=max_budget, no_overage=no_overage,
        capacity_request_factor=capacity_request_factor, time_horizon=time_horizon,
        provider_mode=provider_mode,
    )
    logger.info(TOOL_COMPLETED, tool="budget_recommendation_chart")
    return {"html": html}


def main() -> None:
    mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
