# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Usage
-----
The OpenTelemetry ``jinja2`` integration traces templates loading, compilation
and rendering.
Usage
-----
.. code-block:: python
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.ext.pymemcache import PymemcacheInstrumentor
    trace.set_tracer_provider(TracerProvider())
    trace.set_tracer_provider(TracerProvider())
    from pymemcache.client.base import Client
    client = Client(('localhost', 11211))
    client.set('some_key', 'some_value')
API
---
"""
# pylint: disable=no-value-for-parameter

import logging

import pymemcache
from wrapt import ObjectProxy
from wrapt import wrap_function_wrapper as _wrap

from opentelemetry.auto_instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.ext.pymemcache.util import (
    _get_address_attributes,
    _get_query_string,
)
from opentelemetry.ext.pymemcache.version import __version__
from opentelemetry.trace import SpanKind, get_tracer
from opentelemetry.trace.status import Status, StatusCanonicalCode

logger = logging.getLogger(__name__)

_DEFAULT_SERVICE = "memcached"
_RAWCMD = "db.statement"
_CMD = "memcached.command"
COMMANDS = [
    "set",
    "set_many",
    "add",
    "replace",
    "append",
    "prepend",
    "cas",
    "get",
    "get_many",
    "gets",
    "gets_many",
    "delete",
    "delete_many",
    "incr",
    "decr",
    "touch",
    "stats",
    "version",
    "flush_all",
    "quit",
    "set_multi",
    "get_multi",
]


def _set_connection_attributes(span, instance):
    for key, value in _get_address_attributes(instance).items():
        span.set_attribute(key, value)


def _with_tracer_wrapper(func):
    """Helper for providing tracer for wrapper functions.
    """

    def _with_tracer(tracer, cmd):
        def wrapper(wrapped, instance, args, kwargs):
            # prevent double wrapping
            if hasattr(wrapped, "__wrapped__"):
                return wrapped(*args, **kwargs)
            else:
                return func(tracer, cmd, wrapped, instance, args, kwargs)

        return wrapper

    return _with_tracer


@_with_tracer_wrapper
def _wrap_cmd(tracer, cmd, wrapped, instance, args, kwargs):
    with tracer.start_as_current_span(
        _CMD, kind=SpanKind.INTERNAL, attributes={}
    ) as span:
        try:
            span.set_attribute("service", tracer.instrumentation_info.name)

            vals = _get_query_string(args)
            query = "{}{}{}".format(cmd, " " if vals else "", vals)
            span.set_attribute(_RAWCMD, query)

            _set_connection_attributes(span, instance)
        except Exception:
            pass

        return wrapped(*args, **kwargs)


def _unwrap(obj, attr):
    func = getattr(obj, attr, None)
    if func and isinstance(func, ObjectProxy) and hasattr(func, "__wrapped__"):
        setattr(obj, attr, func.__wrapped__)


class PymemcacheInstrumentor(BaseInstrumentor):
    """An instrumentor for pymemcache
    See `BaseInstrumentor`
    """

    def _instrument(self, **kwargs):
        tracer_provider = kwargs.get("tracer_provider")
        tracer = get_tracer(__name__, __version__, tracer_provider)

        for cmd in COMMANDS:
            _wrap(
                "pymemcache.client.base",
                "Client.{}".format(cmd),
                _wrap_cmd(tracer, cmd),
            )

    def _uninstrument(self, **kwargs):
        for command in COMMANDS:
            _unwrap(pymemcache.client.base.Client, "{}".format(command))
