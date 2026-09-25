"""Strategy Navigator — production LangGraph orchestration.

Replaces the two n8n lanes (challenges-n8n) with a durable, testable, code-first
pipeline. Public entrypoints:

* ``strategy_navigator.api.app:create_app`` — the FastAPI application
* ``strategy_navigator.queue.app:app`` — the procrastinate worker app
* ``strategy_navigator.main:cli`` — the ``strategy-navigator`` CLI
"""

from strategy_navigator.__about__ import __version__

__all__ = ["__version__"]
