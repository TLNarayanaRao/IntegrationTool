"""Optional OpenTelemetry bootstrap for the local and packaged runtime."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Iterator

_tracer = None
_trace_api = None
_propagator = None
_duration = None
_status: dict[str, Any] = {'registered': False, 'configured': False, 'exporter': 'none', 'error': None}


def initialize_telemetry() -> dict[str, Any]:
    global _tracer, _status, _trace_api, _propagator, _duration
    endpoint = str(os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT') or '').strip()
    traces_url = os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')
    requested = str(os.getenv('OTEL_TRACES_EXPORTER') or '').strip().lower()
    _status = {'registered': False, 'configured': bool(endpoint or traces_url or requested in ('console', 'logging')), 'exporter': 'none', 'serviceName': os.getenv('OTEL_SERVICE_NAME', 'mina') or 'mina', 'error': None}
    try:
        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create({'service.name': _status['serviceName']}))
        if endpoint or traces_url:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            trace_endpoint = traces_url or (endpoint if endpoint.endswith('/v1/traces') else endpoint.rstrip('/') + '/v1/traces')
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=trace_endpoint)))
            _status['exporter'] = 'otlp-http'
        elif requested in ('console', 'logging'):
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
            _status['exporter'] = 'console'
        _tracer = provider.get_tracer('mina')
        _trace_api = trace
        _propagator = TraceContextTextMapPropagator()
        if endpoint and os.getenv('OTEL_METRICS_EXPORTER', '').lower() != 'none':
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            metric_endpoint = os.getenv('OTEL_EXPORTER_OTLP_METRICS_ENDPOINT') or endpoint.removesuffix('/v1/traces').rstrip('/') + '/v1/metrics'
            reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=metric_endpoint))
            meter_provider = MeterProvider(resource=provider.resource, metric_readers=[reader])
            _duration = meter_provider.get_meter('mina').create_histogram('mina.execution.duration', unit='ms')
        _status['registered'] = True
    except Exception as exc:
        _status['error'] = f'{exc.__class__.__name__}: {exc}'
    return dict(_status)


def telemetry_status() -> dict[str, Any]:
    return dict(_status)


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None, *, parent=None) -> Iterator[Any]:
    if _tracer is None or not _status['configured']:
        yield None
        return
    with _tracer.start_as_current_span(name, context=parent,
            attributes={str(k): str(v) for k, v in (attributes or {}).items()},
            record_exception=False, set_status_on_exception=False) as current:
        yield current


def trace_fields():
    if _trace_api is None or not _status['configured']:
        return {}
    context = _trace_api.get_current_span().get_span_context()
    return {'traceId': f'{context.trace_id:032x}', 'spanId': f'{context.span_id:016x}'} if context.is_valid else {}


def messaging_carrier(output):
    if not isinstance(output, dict):
        return {}
    messages = output.get('messages')
    if not isinstance(messages, list):
        messages = []
    if len(messages) > 1:
        return {}  # A batch may have unrelated parents.
    for container in (output, *messages[:1]):
        if not isinstance(container, dict):
            continue
        for name in ('attributes', 'Attributes', 'properties', 'headers', 'UserProperties'):
            headers = container.get(name)
            if not isinstance(headers, dict):
                continue
            carrier = {}
            for key, value in headers.items():
                if isinstance(key, bytes):
                    key = key.decode('ascii', errors='ignore')
                if str(key).lower() not in {'traceparent', 'tracestate'}:
                    continue
                if isinstance(value, bytes):
                    value = value.decode('ascii', errors='ignore')
                if isinstance(value, str) and len(value) <= 512:
                    carrier[str(key).lower()] = value
            if carrier.get('traceparent'):
                return carrier
    return {}


def inject_messaging(headers):
    if _propagator and _status['configured'] and not any(str(k).lower() == 'traceparent' for k in headers):
        _propagator.inject(headers)
    return headers


def instrument(name, describe, carrier=None):
    """Time an async boundary without recording payloads or exception text."""
    def decorate(function):
        @wraps(function)
        async def run(*args, **kwargs):
            if not _status['configured'] or _tracer is None:
                return await function(*args, **kwargs)
            parent_headers = carrier(*args, **kwargs) if carrier else {}
            parent = _propagator.extract(parent_headers) if parent_headers else None
            started = time.perf_counter()
            status = 'completed'
            attributes = describe(*args, **kwargs)
            if attributes is None:
                return await function(*args, **kwargs)
            with span(name, attributes, parent=parent) as current:
                try:
                    result = await function(*args, **kwargs)
                    status = 'failed' if getattr(result, 'status', None) == 'failed' else 'completed'
                    return result
                except Exception:
                    status = 'failed'
                    raise
                except asyncio.CancelledError:
                    status = 'cancelled'
                    raise
                finally:
                    if current is not None:
                        current.set_attribute('mina.status', status)
                        if status == 'failed':
                            current.set_status(_trace_api.StatusCode.ERROR)
                    if _duration is not None:
                        _duration.record((time.perf_counter() - started) * 1000,
                                         {'kind': name, 'status': status, 'activity.type': attributes.get('mina.activity.type', '')})
        return run
    return decorate


initialize_telemetry()
