"""Exception hierarchy.

The split that matters for the queue: :class:`TransientError` subclasses are
retried (LLM 5xx, gateway timeout, Jina hiccup); :class:`PermanentError`
subclasses go straight to the dead-letter table (bad payload, schema that never
validates, unknown workflow).
"""

from __future__ import annotations


class StrategyNavigatorError(Exception):
    """Base class for everything this service raises deliberately."""


class TransientError(StrategyNavigatorError):
    """Worth retrying — the same input may succeed later."""


class PermanentError(StrategyNavigatorError):
    """Not worth retrying — the input or configuration is wrong."""


# --- transient ---
class LLMError(TransientError):
    """Upstream LLM / gateway failure after LiteLLM exhausted its own retries."""


class LLMTimeoutError(LLMError):
    pass


class StructuredOutputError(TransientError):
    """Model output failed schema validation after all repair attempts."""

    def __init__(self, message: str, *, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


class SearchToolError(TransientError):
    pass


class BackendCallbackError(TransientError):
    """Could not deliver the result to challenges-backend."""


# --- permanent ---
class InvalidPayloadError(PermanentError):
    pass


class UnknownWorkflowError(PermanentError):
    pass


class StageNotImplementedError(PermanentError):
    """A workflow graph exists as a stub only — do not retry, alert instead."""
