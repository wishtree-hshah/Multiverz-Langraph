"""Lane <-> queue mapping and worker concurrency.

Queues (procrastinate queue names):
    sn_short   fresh short-lane runs
    sn_long    fresh long-lane runs
    sn_retry   resumed/failed runs of ANY lane — dedicated pool, high priority

A worker deployment picks exactly one lane:
    worker --lane short   -> subscribes ["sn_short"], concurrency 4
    worker --lane long    -> subscribes ["sn_long"],  concurrency 6
    worker --lane retry   -> subscribes ["sn_retry"], concurrency 4

Because retries have their own pool they never wait behind fresh jobs; the
priority value only orders them if that pool is momentarily saturated.
"""

from __future__ import annotations

from strategy_navigator.config import settings
from strategy_navigator.constants import WORKFLOW_LANE, Lane, Workflow

QUEUE_SHORT = "sn_short"
QUEUE_LONG = "sn_long"
QUEUE_RETRY = "sn_retry"

_LANE_QUEUE: dict[Lane, str] = {
    Lane.SHORT: QUEUE_SHORT,
    Lane.LONG: QUEUE_LONG,
    Lane.RETRY: QUEUE_RETRY,
}


def lane_for(workflow: Workflow) -> Lane:
    return WORKFLOW_LANE.get(workflow, Lane.SHORT)


def queue_for_workflow(workflow: Workflow) -> str:
    return _LANE_QUEUE[lane_for(workflow)]


def queues_for_lane(lane: Lane) -> list[str]:
    return [_LANE_QUEUE[lane]]


def concurrency_for_lane(lane: Lane) -> int:
    return {
        Lane.SHORT: settings.lane_short_concurrency,
        Lane.LONG: settings.lane_long_concurrency,
        Lane.RETRY: settings.lane_retry_concurrency,
    }[lane]
