from strategy_navigator.constants import Lane, Workflow
from strategy_navigator.queue.lanes import (
    QUEUE_LONG,
    QUEUE_RETRY,
    QUEUE_SHORT,
    concurrency_for_lane,
    lane_for,
    queue_for_workflow,
    queues_for_lane,
)


def test_short_lane_workflows():
    for wf in (
        Workflow.DOMAIN_AGENT,
        Workflow.IDEA_EXTRACTION,
        Workflow.RAPID_CONSOLIDATION,
        Workflow.FORESIGHT_CONSOLIDATION,
        Workflow.VOTING,
    ):
        assert lane_for(wf) is Lane.SHORT
        assert queue_for_workflow(wf) == QUEUE_SHORT


def test_long_lane_workflows():
    for wf in (
        Workflow.FORM_FILLING_10STEP,
        Workflow.CAPSTONE_SUBSTRATE,
        Workflow.REPORT_RENDER,
        Workflow.CUSTOM_ARCHETYPE,
    ):
        assert lane_for(wf) is Lane.LONG
        assert queue_for_workflow(wf) == QUEUE_LONG


def test_retry_lane_is_isolated():
    assert queues_for_lane(Lane.RETRY) == [QUEUE_RETRY]
    assert QUEUE_RETRY not in queues_for_lane(Lane.SHORT)
    assert QUEUE_RETRY not in queues_for_lane(Lane.LONG)


def test_lane_concurrency_defaults():
    assert concurrency_for_lane(Lane.SHORT) == 4
    assert concurrency_for_lane(Lane.LONG) == 6
    assert concurrency_for_lane(Lane.RETRY) == 4
