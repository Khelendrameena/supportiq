"""OpenTelemetry bootstrap.

Called once from AppConfig.ready(). When OTEL_EXPORTER_OTLP_ENDPOINT is unset
(local dev), everything below is a safe no-op: the SDK is configured but no
exporter is attached, so spans are created and dropped cheaply.
"""
import logging

logger = logging.getLogger("supportiq.otel")

_configured = False


def configure_tracing() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        resource = Resource.create({"service.name": "supportiq-api"})
        provider = TracerProvider(resource=resource)
        endpoint = __import__("django.conf", fromlist=["settings"]).settings.OTEL_EXPORTER_OTLP_ENDPOINT
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            logger.info("otel exporter enabled", extra={"endpoint": endpoint})
        else:
            # Console exporter is too noisy for dev; attach nothing -> no-op.
            logger.info("otel tracing configured without exporter (no-op)")
        trace.set_tracer_provider(provider)

        # Auto-instrument Django requests and Celery tasks.
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.django import DjangoInstrumentor

        DjangoInstrumentor().instrument()
        CeleryInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001 - tracing must never break the app
        logger.warning("otel configuration skipped: %s", exc)
