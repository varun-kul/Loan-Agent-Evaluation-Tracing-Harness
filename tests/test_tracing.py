"""Tests for Langfuse tracing instrumentation.

Tests mock the langfuse client and verify that spans are created
with correct names, input data, and metadata for each tool call.
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Create a mock langfuse module before importing the agent
mock_langfuse = types.ModuleType("langfuse")
mock_langfuse.model = types.ModuleType("langfuse.model")
mock_langfuse.model.CreateTrace = MagicMock
mock_langfuse.model.CreateSpan = MagicMock
sys.modules["langfuse"] = mock_langfuse
sys.modules["langfuse.model"] = mock_langfuse.model


class MockLangfuse:
    """Mock Langfuse client for testing."""

    def __init__(self, public_key=None, secret_key=None, host=None):
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host
        self.traces = {}
        self.spans = {}

    def trace(self, name=None, user_id=None, session_id=None, metadata=None):
        trace = MagicMock()
        trace.id = f"trace-{len(self.traces)}"
        trace.span = MagicMock(return_value=MagicMock())
        self.traces[trace.id] = {"name": name, "user_id": user_id, "session_id": session_id, "metadata": metadata}
        return trace

    def flush(self):
        pass


class TestTracing(unittest.TestCase):
    """Test Langfuse tracing instrumentation."""

    def setUp(self):
        # Reset the tracer's context var
        from src.loan_agent.tracing import _current_trace_var
        _current_trace_var.set(None)

    def test_tracer_is_available_when_enabled(self):
        """Tracer reports available when LANGFUSE_ENABLED=true and langfuse installed."""
        with patch.dict(os.environ, {"LANGFUSE_ENABLED": "true", "LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}):
            with patch("src.loan_agent.tracing.Langfuse", MockLangfuse):
                from src.loan_agent.tracing import LangfuseTracer
                tracer = LangfuseTracer(enabled=True)
                self.assertTrue(tracer.is_available())

    def test_tracer_not_available_when_disabled(self):
        """Tracer reports not available when LANGFUSE_ENABLED=false."""
        from src.loan_agent.tracing import LangfuseTracer
        tracer = LangfuseTracer(enabled=False)
        self.assertFalse(tracer.is_available())

    def test_tracer_not_available_when_langfuse_missing(self):
        """Tracer reports not available when langfuse is not installed."""
        with patch("src.loan_agent.tracing.Langfuse", None):
            from src.loan_agent.tracing import LangfuseTracer
            tracer = LangfuseTracer(enabled=True)
            self.assertFalse(tracer.is_available())

    def test_start_and_end_trace(self):
        """start_trace creates a trace and end_trace closes it."""
        with patch("src.loan_agent.tracing.Langfuse", MockLangfuse):
            from src.loan_agent.tracing import LangfuseTracer
            tracer = LangfuseTracer(enabled=True)
            trace_id = tracer.start_trace("test_trace", user_id="user1", session_id="session1", metadata={"key": "val"})
            self.assertIsNotNone(trace_id)
            tracer.end_trace(output={"result": "ok"})
            # After end_trace, current trace should be None
            from src.loan_agent.tracing import _current_trace_var
            self.assertIsNone(_current_trace_var.get())

    def test_span_without_trace_returns_noop(self):
        """span() yields a _NoopSpan when no trace is active (disabled mode)."""
        from src.loan_agent.tracing import LangfuseTracer, _NoopSpan
        tracer = LangfuseTracer(enabled=False)
        with tracer.span("test_span", input_data={"a": 1}, metadata={"b": 2}) as span:
            self.assertIsInstance(span, _NoopSpan)

    def test_span_records_input_and_output(self):
        """span() records input_data and calls update with output."""
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_trace.span.return_value = mock_span

        with patch("src.loan_agent.tracing.Langfuse", MockLangfuse):
            from src.loan_agent.tracing import LangfuseTracer, _current_trace_var
            tracer = LangfuseTracer(enabled=True)
            _current_trace_var.set(mock_trace)

            with tracer.span("tool.test_tool", input_data={"x": 1}, metadata={"y": 2}) as span:
                span.update(output={"result": "success"})

            mock_trace.span.assert_called_once_with(
                name="tool.test_tool",
                input={"x": 1},
                metadata={"y": 2},
            )
            # update called twice: once by test code, once by context manager (latency)
            update_calls = mock_span.update.call_args_list
            self.assertTrue(any(
                call.kwargs.get("output") == {"result": "success"}
                for call in update_calls
            ), f"Expected update(output={{'result': 'success'}}) in {update_calls}")
            mock_span.end.assert_called_once()

    def test_agent_instrumentation_creates_spans(self):
        """Agent handlers create tracer.spans for tool calls."""
        mock_trace = MagicMock()
        mock_trace.span.return_value = MagicMock()

        with patch("src.loan_agent.tracing.Langfuse", MockLangfuse):
            from src.loan_agent.tracing import LangfuseTracer, _current_trace_var
            # Create a fresh tracer after patching so _client uses MockLangfuse
            test_tracer = LangfuseTracer(enabled=True)
            self.assertTrue(test_tracer.is_available())
            _current_trace_var.set(mock_trace)

            # Monkeypatch the global tracer's span context to use our mock trace
            import src.loan_agent.agent as agent_module
            original_span = agent_module.tracer.span

            def mock_span_cm(name, input_data=None, metadata=None):
                _current_trace_var.set(mock_trace)
                cm = test_tracer.span(name, input_data=input_data, metadata=metadata)
                return cm

            agent_module.tracer.span = mock_span_cm

            try:
                from src.loan_agent.agent import LoanServicingAgent
                from src.loan_agent.backend import reset_db
                reset_db()

                agent = LoanServicingAgent()
                agent.process_message("What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001")

                # Verify that span was called for tool calls
                self.assertTrue(mock_trace.span.called, "span should be called for tool calls")

                # Check span names used
                span_calls = [call.kwargs.get("name") or (call.args[0] if call.args else None) for call in mock_trace.span.call_args_list]
                self.assertIn("tool.lookup_account", span_calls)
            finally:
                agent_module.tracer.span = original_span


if __name__ == "__main__":
    unittest.main()