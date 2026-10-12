"""Settings draft validation and revisioned writes; never sends external requests."""
from pydantic import ValidationError
from zoneinfo import ZoneInfoNotFoundError
from kenradar.core.settings import RevisionConflict, edit_settings, read_settings
from kenradar.web.router import register_handler


def read(self, config_path):
    self._send_json(read_settings(config_path))


def edit(self, config_path, data, *, save=False):
    try:
        self._send_json(edit_settings(config_path, data, save=save))
    except RevisionConflict:
        self._send_json({"ok": False, "code": "revision_conflict", "message": "配置已被修改，请刷新后合并草稿"}, status=409)
    except (ValueError, ValidationError, ZoneInfoNotFoundError):
        # ValidationError can include secret input values. Do not serialize it.
        self._send_json({"ok": False, "code": "invalid_settings", "message": "配置校验失败，请检查字段、类型和设置分组"}, status=422)


def save(self, config_path, data):
    return edit(self, config_path, data, save=True)


def test_draft(self, config_path, data):
    from kenradar.core.settings_tests import probe
    import requests
    try:
        self._send_json(probe(config_path, data))
    except RevisionConflict:
        self._send_json({"ok": False, "message": "配置版本冲突，草稿仍保留"}, status=409)
    except (ValueError, ZoneInfoNotFoundError):
        self._send_json({"ok": False, "message": "测试草稿无效，尚未保存"}, status=422)
    except (requests.RequestException, OSError):
        self._send_json({"ok": False, "message": "测试连接失败或结果未知；尚未保存，不自动重发"}, status=502)


def register(handler_class):
    register_handler("/api/settings", read, ["config_path"])
    register_handler("/api/settings", save, ["config_path", "data"], method="PATCH")
    register_handler("/api/settings/validate", edit, ["config_path", "data"], method="POST")
    register_handler("/api/settings/test", test_draft, ["config_path", "data"], method="POST")
