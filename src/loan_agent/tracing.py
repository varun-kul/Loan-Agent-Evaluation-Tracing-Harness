"""Langfuse tracing client for the loan agent eval harness.

Wraps tool calls and agent message processing in Langfuse traces/spans
so every run shows: tool calls, latency, cost, input/output data.
"""
import os
import time
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional, Dict, Any
from datetime import datetime

try:
    from langfuse import Langfuse
    from langfuse.model import CreateTrace, CreateSpan
except ImportError:
    Langfuse = None

# ContextVar for thread-safe trace context
_current_trace_var: ContextVar[Optional[Any]] = ContextVar("_current_trace_var", default=None)


class _NoopSpan:
    """No-op span that safely absorbs update/end calls when tracing is disabled."""

    def update(self, output=None, level=None):
        pass

    def end(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class LangfuseTracer:
    """Wrapper around Langfuse SDK for tracing agent runs."""

    def __init__(self, enabled: bool = None):
        self.enabled = enabled if enabled is not None else os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
        self._client = None

        if self.enabled and Langfuse is not None:
            self._client = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )

    def is_available(self) -> bool:
        return self.enabled and self._client is not None

    def _get_current_trace(self):
        """Get the current trace from context var."""
        return _current_trace_var.get()

    def _set_current_trace(self, trace):
        """Set the current trace in context var."""
        _current_trace_var.set(trace)

    def start_trace(self, trace_name: str, user_id: str = None, session_id: str = None, metadata: dict = None) -> str:
        """Start a new trace. Returns trace ID."""
        if not self.is_available():
            return None

        trace = self._client.trace(
            name=trace_name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
        )
        self._set_current_trace(trace)
        return trace.id

    def end_trace(self, output: dict = None):
        """End the current trace."""
        trace = self._get_current_trace()
        if self.is_available() and trace is not None:
            if output:
                trace.update(output=output)
            trace.end()
            self._set_current_trace(None)

    @contextmanager
    def span(self, name: str, input_data: dict = None, metadata: dict = None):
        """Context manager for a span within the current trace.
        Records start/end time, input, output, and any exception.
        """
        start_time = time.time()

        trace = self._get_current_trace()
        if self.is_available() and trace is not None:
            span = trace.span(
                name=name,
                input=input_data or {},
                metadata=metadata or {},
            )
        else:
            span = _NoopSpan()

        try:
            yield span
        except Exception as e:
            span.update(
                output={"error": str(e)},
                level="ERROR",
            )
            span.end()
            raise
        else:
            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000
            span.update(
                output={"latency_ms": latency_ms},
            )
            span.end()

    def flush(self):
        """Flush any pending events to Langfuse."""
        if self.is_available():
            try:
                self._client.flush()
            except Exception:
                pass


# Global tracer instance
tracer = LangfuseTracer()