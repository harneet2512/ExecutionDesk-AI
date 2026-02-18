"""OpenTelemetry instrumentation setup."""
import os
from typing import Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


def is_pytest() -> bool:
    """Check if running under pytest."""
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def setup_otel() -> trace.Tracer:
    """Setup OpenTelemetry and return a tracer."""
    resource = Resource.create({
        "service.name": settings.service_name,
        "service.version": settings.service_version,
    })
    
    provider = TracerProvider(resource=resource)
    
    # Export to OTLP if configured, otherwise console (skip console under pytest)
    if settings.otlp_endpoint:
        try:
            exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
            logger.info(f"OTLP exporter configured: {settings.otlp_endpoint}")
        except Exception as e:
            logger.warning(f"Failed to setup OTLP exporter: {e}, using console")
            if not is_pytest():
                exporter = ConsoleSpanExporter()
            else:
                # Under pytest, use a no-op exporter to avoid closed file errors
                from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
                class NoOpExporter(SpanExporter):
                    def export(self, spans):
                        return SpanExportResult.SUCCESS
                    def shutdown(self):
                        pass
                exporter = NoOpExporter()
    else:
        if not is_pytest():
            exporter = ConsoleSpanExporter()
            logger.info("Using console span exporter (OTLP_ENDPOINT not set)")
        else:
            # Under pytest, use a no-op exporter to avoid closed file errors
            from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
            class NoOpExporter(SpanExporter):
                def export(self, spans):
                    return SpanExportResult.SUCCESS
                def shutdown(self):
                    pass
            exporter = NoOpExporter()
    
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    
    trace.set_tracer_provider(provider)
    
    return trace.get_tracer(__name__)


# Global tracer instance
_tracer: Optional[trace.Tracer] = None


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = setup_otel()
    return _tracer
