"""
Route registration center for KenRadar web API.

Registers all route handlers with the main HTTP handler.
"""

from __future__ import annotations

from typing import Any, Callable

# Route mapping: (path, method) -> (handler_func, handler_kwargs)
# A GET-only registration stores the key (path, "GET").
ROUTE_HANDLERS: dict[tuple[str, str], tuple[Callable, list[str]]] = {}


def register_handler(
    path: str,
    handler: Callable,
    kwargs_keys: list[str] | None = None,
    method: str = "GET",
) -> None:
    """Register a handler for an exact path + method match.

    Args:
        path: The URL path (e.g. "/api/bootstrap").
        handler: The handler method bound to the request handler class.
        kwargs_keys: Which kwarg names to pass: self, config_path, query_params, form, data.
        method: HTTP method; defaults to GET.
    """
    ROUTE_HANDLERS[(path, method.upper())] = (handler, kwargs_keys or [])


def init_routes(handler_class: type) -> None:
    """Initialize all route registrations by binding methods to the handler class."""
    from kenradar.web.routes import (
        content,
        content_detail,
        dashboard,
        dashboard_overview,
        delivery,
        health,
        insights,
        process_url,
        research,
        sources,
        source_subscriptions,
        stream,
        tasks,
        settings,
    )

    dashboard.register(handler_class)
    dashboard_overview.register(handler_class)
    delivery.register(handler_class)
    research.register(handler_class)
    sources.register(handler_class)
    source_subscriptions.register(handler_class)
    content.register(handler_class)
    content_detail.register(handler_class)
    health.register(handler_class)
    insights.register(handler_class)
    stream.register(handler_class)
    tasks.register(handler_class)
    process_url.register(handler_class)
    settings.register(handler_class)

    # Attach dispatcher to handler class
    handler_class._route_handlers = ROUTE_HANDLERS
    handler_class._dispatch_route = _make_dispatcher(ROUTE_HANDLERS)


def _make_dispatcher(
    handlers: dict[str, tuple[Callable, list[str]]],
) -> Callable:
    """Create a dispatcher that calls the right handler based on path and request data."""

    def dispatcher(
        self: Any,
        path: str,
        method: str = "GET",
        query_params: dict | None = None,
        form: dict | None = None,
        data: dict | None = None,
        config_path: str | None = None,
    ) -> bool:
        """Dispatch to a registered handler. Returns True if a handler was found."""
        method = str(method or "GET").upper()
        if path.startswith('/api/integrations/hermes/v1/'):
            from kenradar.web.routes.hermes_v1 import dispatch
            return dispatch(self, path, method, config_path or 'config.yaml', data)
        entry = handlers.get((path, method))
        if entry is None and method in {"GET", "HEAD"}:
            entry = handlers.get((path, "GET"))
        if not entry:
            return False

        handler_func, kwarg_keys = entry
        if config_path is None:
            config_path = "config.yaml"

        query_params = query_params or {}
        form = form or {}
        data = data or {}

        kwargs: dict[str, Any] = {"self": self}
        if "config_path" in kwarg_keys:
            kwargs["config_path"] = config_path
        if "query_params" in kwarg_keys:
            kwargs["query_params"] = query_params
        if "form" in kwarg_keys:
            kwargs["form"] = form
        if "data" in kwarg_keys:
            kwargs["data"] = data

        handler_func(**kwargs)
        return True

    return dispatcher
