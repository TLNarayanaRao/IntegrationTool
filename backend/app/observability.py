"""Optional OpenTelemetry bootstrap for the local and packaged runtime."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

_tracer = None
_status: dict[str, Any] = {'registered': False, 'configured': False, 'exporter': 'none', 'error': None}


def initialize_telemetry() -> dict[str, Any]:
    global _tracer, _status
    endpoint = str(os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT') or '').strip()
    requested = str(os.getenv('OTEL_TRACES_EXPORTER') or '').strip().lower()
    _status = {'registered': False, 'configured': bool(endpoint or requested), 'exporter': 'none', 'serviceName': os.getenv('OTEL_SERVICE_NAME', 'integration-fabric') or 'integration-fabric', 'error': None}
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create({'service.name': _status['serviceName']}))
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            _status['exporter'] = 'otlp-http'
        elif requested in ('console', 'logging'):
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            _status['exporter'] = 'console'
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer('integration-fabric')
        _status['registered'] = True
    except Exception as exc:
        _status['error'] = f'{exc.__class__.__name__}: {exc}'
    return dict(_status)


def telemetry_status() -> dict[str, Any]:
    return dict(_status)


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name, attributes={str(k): str(v) for k, v in (attributes or {}).items()}) as current:
        yield current


initialize_telemetry()
