"""Source management route registrations.

Legacy implementations remain bound methods for behavior compatibility; this
module owns the URL registry so do_POST does not need to enumerate source paths.
"""

from __future__ import annotations

from typing import Any

from kenradar.web.router import register_handler


def _call_method(name: str):
    def handler(self: Any, config_path: str, form: dict | None = None, data: dict | None = None) -> None:
        getattr(self, name)(config_path, data if data else (form or {}))
    return handler


def register(handler_class: type) -> None:
    routes = {
        "/sources/add": ("_add_source", ["config_path", "form"]),
        "/sources/promote": ("_promote_source", ["config_path", "form"]),
        "/sources/update": ("_update_source", ["config_path", "form"]),
        "/sources/delete": ("_delete_source", ["config_path", "form"]),
        "/api/source/toggle": ("_toggle_source", ["config_path", "data"]),
        "/api/source/delete": ("_delete_source_json", ["config_path", "data"]),
        "/api/source/add": ("_add_source_json", ["config_path", "data"]),
        "/api/source/preview": ("_preview_source_json", ["config_path", "data"]),
        "/api/source/check": ("_check_source_json", ["config_path", "data"]),
        "/api/source/category": ("_update_source_category", ["config_path", "data"]),
        "/api/source/categories": ("_update_source_categories", ["config_path", "data"]),
    }
    for path, (method_name, keys) in routes.items():
        register_handler(path, _call_method(method_name), keys)
