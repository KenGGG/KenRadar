"""
Route registration center for KenRadar web API.

Registers all route handlers with the main HTTP handler.
"""

from __future__ import annotations

from typing import Any, Callable

# Route mapping: path_pattern -> (handler_func, handler_kwargs)
ROUTE_HANDLERS: dict[str, tuple[Callable, list[str]]] = {}


def register_handler(path: str, handler: Callable, kwargs_keys: list[str] | None = None) -> None:
    """Register a handler for an exact path match.

    Args:
        path: The URL path (e.g. "/api/bootstrap").
        handler: The handler method bound to the request handler class.
        kwargs_keys: Which kwarg names to pass: self, config_path, query_params, form, data.
    """
    ROUTE_HANDLERS[path] = (handler, kwargs_keys or [])


def init_routes(handler_class: type) -> None:
    """Initialize all route registrations by binding methods to the handler class."""
    from kenradar.web.routes import (
        content,
        dashboard,
        dashboard_overview,
        health,
        insights,
        research,
        sources,
        stream,
        tasks,
    )

    dashboard.register(handler_class)
    dashboard_overview.register(handler_class)
    research.register(handler_class)
    sources.register(handler_class)
    content.register(handler_class)
    health.register(handler_class)
    insights.register(handler_class)
    stream.register(handler_class)
    tasks.register(handler_class)

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
        entry = handlers.get(path)
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
