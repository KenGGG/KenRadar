from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


class _FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class AppSection(_FlexibleModel):
    data_dir: str = "./data"
    database_url: str = ""
    web_base_url: str = "http://172.30.10.150:8765"

    @field_validator("web_base_url")
    @classmethod
    def validate_web_base_url(cls, value: str) -> str:
        _validate_url_or_placeholder(value, "app.web_base_url")
        return value


class ScheduleSection(_FlexibleModel):
    times: list[str] = Field(default_factory=list)

    @field_validator("times")
    @classmethod
    def validate_times(cls, value: list[str]) -> list[str]:
        if not all(isinstance(item, str) and re.fullmatch(r"\d{2}:\d{2}", item) for item in value):
            raise ValueError("schedule.times 必须是 HH:MM 字符串列表")
        for item in value:
            hour, minute = [int(part) for part in item.split(":", 1)]
            if hour > 23 or minute > 59:
                raise ValueError(f"schedule.times 时间超出范围: {item}")
        return value


class WhisperSection(_FlexibleModel):
    device: str = "cuda"

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        if value not in {"cuda", "cpu"}:
            raise ValueError("ai.whisper.device 只能是 cuda 或 cpu")
        return value


class OrganizerProviderSection(_FlexibleModel):
    endpoint: str = ""
    max_tokens: int | None = None
    rpm_limit: int | None = None
    top_p: float | None = None
    top_k: int | None = None

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        _validate_url_or_placeholder(value, "ai.organizer.providers[].endpoint")
        return value

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("ai.organizer.providers[].max_tokens 必须是正整数")
        return value

    @field_validator("rpm_limit")
    @classmethod
    def validate_rpm_limit(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("ai.organizer.providers[].rpm_limit 必须是非负整数")
        return value

    @field_validator("top_p")
    @classmethod
    def validate_top_p(cls, value: float | None) -> float | None:
        if value is not None and (float(value) < 0 or float(value) > 1):
            raise ValueError("ai.organizer.providers[].top_p 必须是 0 到 1 之间的数字")
        return value

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("ai.organizer.providers[].top_k 必须是非负整数")
        return value


class OrganizerSection(_FlexibleModel):
    endpoint: str = ""
    max_tokens: int = 2048
    rpm_limit: int = 0
    top_p: float | None = 0.95
    top_k: int | None = 40
    providers: list[OrganizerProviderSection] = Field(default_factory=list)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        _validate_url_or_placeholder(value, "ai.organizer.endpoint")
        return value

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int) -> int:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("ai.organizer.max_tokens 必须是正整数")
        return value

    @field_validator("rpm_limit")
    @classmethod
    def validate_rpm_limit(cls, value: int) -> int:
        if not isinstance(value, int) or value < 0:
            raise ValueError("ai.organizer.rpm_limit 必须是非负整数")
        return value

    @field_validator("top_p")
    @classmethod
    def validate_top_p(cls, value: float | None) -> float | None:
        if value is not None and (float(value) < 0 or float(value) > 1):
            raise ValueError("ai.organizer.top_p 必须是 0 到 1 之间的数字")
        return value

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("ai.organizer.top_k 必须是非负整数")
        return value


class AISection(_FlexibleModel):
    whisper: WhisperSection = Field(default_factory=WhisperSection)
    organizer: OrganizerSection = Field(default_factory=OrganizerSection)


class FeishuSection(_FlexibleModel):
    webhook_url: str = ""

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook(cls, value: str) -> str:
        _validate_url_or_placeholder(value, "notification.channels.feishu.webhook_url")
        return value


class NotificationChannelsSection(_FlexibleModel):
    feishu: FeishuSection = Field(default_factory=FeishuSection)


class NotificationSection(_FlexibleModel):
    channels: NotificationChannelsSection = Field(default_factory=NotificationChannelsSection)


class GithubPagesSection(_FlexibleModel):
    enabled: bool = False
    output_dir: str = "./data/github_pages"
    public_base_url: str = ""

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        _validate_url_or_placeholder(value, "publishing.github_pages.public_base_url")
        return value


class GithubSyncSection(_FlexibleModel):
    enabled: bool = False
    repo_dir: str = "."
    branch: str = "main"
    auto_commit: bool = False
    auto_push: bool = False
    include_html_docs: bool = True
    include_markdown_notes: bool = True
    include_briefs: bool = True
    include_transcripts: bool = True
    commit_message_template: str = "chore: publish KenRadar notes {timestamp}"


class PublishingSection(_FlexibleModel):
    github_pages: GithubPagesSection = Field(default_factory=GithubPagesSection)
    github_sync: GithubSyncSection = Field(default_factory=GithubSyncSection)


class KenRadarConfigModel(_FlexibleModel):
    app: AppSection = Field(default_factory=AppSection)
    schedule: ScheduleSection = Field(default_factory=ScheduleSection)
    ai: AISection = Field(default_factory=AISection)
    notification: NotificationSection = Field(default_factory=NotificationSection)
    publishing: PublishingSection = Field(default_factory=PublishingSection)


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    path: Path

    @property
    def root_dir(self) -> Path:
        return self.path.parent.parent.resolve()

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.raw
        for key in dotted_key.split("."):
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()

    @property
    def database_path(self) -> Path:
        return self.resolve_path(self.get("app.database_path", "./data/kenradar.db"))

    @property
    def database_url(self) -> str:
        env_value = os.getenv("DATABASE_URL", "").strip()
        return env_value or str(self.get("app.database_url", "") or "").strip()

    @property
    def database_type(self) -> str:
        url = self.database_url
        if not url:
            return "sqlite"
        scheme = urlparse(url).scheme.lower()
        if scheme in {"postgres", "postgresql"}:
            return "postgresql"
        if scheme in {"sqlite", "sqlite3"}:
            return "sqlite"
        return str(self.get("app.database_type", "") or "sqlite").strip().lower() or "sqlite"

    @property
    def data_dir(self) -> Path:
        return self.resolve_path(self.get("app.data_dir", "./data"))

    @property
    def download_dir(self) -> Path:
        return self.resolve_path(self.get("download.path", "./data/Downloaded"))

    @property
    def cookies(self) -> dict[str, str]:
        cookie_file = os.getenv("DOUYIN_COOKIE_FILE", "").strip() or str(
            self.get("app.douyin_cookie_file", "") or ""
        ).strip()
        if cookie_file:
            path = self.resolve_path(cookie_file)
            if path.exists():
                _warn_insecure_secret_permissions(path)
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    return {str(key): str(value) for key, value in loaded.items() if str(value).strip()}
        cookies = self.get("cookies", {}) or {}
        if not isinstance(cookies, dict):
            return {}
        return {str(key): str(value) for key, value in cookies.items() if str(value).strip()}

    @property
    def feishu_webhook_url(self) -> str:
        env_value = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
        return env_value or str(
            self.get("notification.channels.feishu.webhook_url", "") or ""
        ).strip()

    @property
    def web_password(self) -> str:
        return os.getenv("KENRADAR_WEB_PASSWORD", "").strip() or str(
            self.get("app.web_password", "") or ""
        ).strip()


def load_config(config_path: str | Path = "config/config.yaml") -> AppConfig:
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    _load_dotenv(path.parent.parent / ".env")
    _warn_insecure_secret_permissions(path.parent.parent / ".env")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件必须是 YAML 字典: {path}")
    raw = _expand_env_vars(raw)
    _validate_config(raw, path)
    _warn_duplicate_bloggers(raw, path)
    return AppConfig(raw=raw, path=path)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _restore_secret_placeholders(data: dict[str, Any], path: Path) -> dict[str, Any]:
    try:
        persisted = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return data
    for dotted_key in (
        "app.database_url",
        "app.web_password",
        "app.douyin_cookie_file",
        "notification.channels.feishu.webhook_url",
    ):
        original = _dotted_get(persisted, dotted_key)
        if isinstance(original, str) and _ENV_VAR_PATTERN.fullmatch(original.strip()):
            _dotted_set(data, dotted_key, original)
    if "cookies" not in persisted:
        data.pop("cookies", None)
    return data


def _dotted_get(data: dict[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for key in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _dotted_set(data: dict[str, Any], dotted_key: str, value: Any) -> None:
    target = data
    parts = dotted_key.split(".")
    for key in parts[:-1]:
        target = target.setdefault(key, {})
    target[parts[-1]] = value


def _warn_insecure_secret_permissions(path: Path) -> None:
    if not path.exists() or os.name == "nt":
        return
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        logger.warning("敏感配置文件权限过宽: path=%s mode=%s，建议 chmod 600", path, oct(mode))


def save_config(config: AppConfig, raw: dict[str, Any] | None = None) -> None:
    data = deepcopy(raw if raw is not None else config.raw)
    data = _restore_secret_placeholders(data, config.path)
    _validate_config(_expand_env_vars(data), config.path, reject_duplicate_bloggers=True)
    config.path.parent.mkdir(parents=True, exist_ok=True)
    with _config_lock(config.path):
        _atomic_dump_yaml(config.path, data)


def _validate_config(raw: dict[str, Any], path: Path, reject_duplicate_bloggers: bool = False) -> None:
    try:
        KenRadarConfigModel.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"配置校验失败: {path}\n{exc}") from exc

    schedule = raw.get("schedule", {}) or {}
    times = schedule.get("times", []) or []
    if not isinstance(times, list) or not all(isinstance(item, str) and re.fullmatch(r"\d{2}:\d{2}", item) for item in times):
        raise ValueError(f"schedule.times 必须是 HH:MM 字符串列表: {path}")
    for item in times:
        hour, minute = [int(part) for part in item.split(":", 1)]
        if hour > 23 or minute > 59:
            raise ValueError(f"schedule.times 时间超出范围: {item}")

    whisper = ((raw.get("ai", {}) or {}).get("whisper", {}) or {})
    device = whisper.get("device", "cuda")
    if device not in {"cuda", "cpu"}:
        raise ValueError("ai.whisper.device 只能是 cuda 或 cpu")

    notification = raw.get("notification", {}) or {}
    feishu = ((notification.get("channels", {}) or {}).get("feishu", {}) or {})
    webhook = str(feishu.get("webhook_url", "") or "").strip()
    if webhook and "${" not in webhook:
        parsed = urlparse(webhook)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("notification.channels.feishu.webhook_url 必须是有效 URL")

    organizer = ((raw.get("ai", {}) or {}).get("organizer", {}) or {})
    max_tokens = organizer.get("max_tokens", 2048)
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("ai.organizer.max_tokens 必须是正整数")
    top_p = organizer.get("top_p", 0.95)
    if top_p is not None and (not isinstance(top_p, (int, float)) or float(top_p) < 0 or float(top_p) > 1):
        raise ValueError("ai.organizer.top_p 必须是 0 到 1 之间的数字")
    top_k = organizer.get("top_k", 40)
    if top_k is not None and (not isinstance(top_k, int) or top_k < 0):
        raise ValueError("ai.organizer.top_k 必须是非负整数")
    rpm_limit = organizer.get("rpm_limit", 0)
    if not isinstance(rpm_limit, int) or rpm_limit < 0:
        raise ValueError("ai.organizer.rpm_limit 必须是非负整数")
    providers = organizer.get("providers", [])
    if providers:
        if not isinstance(providers, list):
            raise ValueError("ai.organizer.providers 必须是列表")
        for index, provider in enumerate(providers, start=1):
            if not isinstance(provider, dict):
                raise ValueError(f"ai.organizer.providers[{index}] 必须是字典")
            provider_max_tokens = provider.get("max_tokens", max_tokens)
            if not isinstance(provider_max_tokens, int) or provider_max_tokens <= 0:
                raise ValueError(f"ai.organizer.providers[{index}].max_tokens 必须是正整数")
            provider_top_p = provider.get("top_p", top_p)
            if provider_top_p is not None and (not isinstance(provider_top_p, (int, float)) or float(provider_top_p) < 0 or float(provider_top_p) > 1):
                raise ValueError(f"ai.organizer.providers[{index}].top_p 必须是 0 到 1 之间的数字")
            provider_top_k = provider.get("top_k", top_k)
            if provider_top_k is not None and (not isinstance(provider_top_k, int) or provider_top_k < 0):
                raise ValueError(f"ai.organizer.providers[{index}].top_k 必须是非负整数")
            provider_rpm_limit = provider.get("rpm_limit", rpm_limit)
            if provider_rpm_limit is not None and (not isinstance(provider_rpm_limit, int) or provider_rpm_limit < 0):
                raise ValueError(f"ai.organizer.providers[{index}].rpm_limit 必须是非负整数")
            endpoint = str(provider.get("endpoint", "") or "").strip()
            if endpoint and "${" not in endpoint:
                parsed = urlparse(endpoint)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError(f"ai.organizer.providers[{index}].endpoint 必须是有效 URL")

    duplicates = _find_duplicate_bloggers(raw)
    if duplicates and reject_duplicate_bloggers:
        summary = ", ".join(f"{sec_uid} ({count} 次)" for sec_uid, count in duplicates.items())
        raise ConfigError(f"配置包含重复来源 sec_uid，已拒绝保存: {summary}")


def _expand_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda match: os.environ.get(match.group(1), match.group(0)), value)
    if isinstance(value, dict):
        return {key: _expand_env_vars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_expand_env_vars(item) for item in value)
    return value


def _validate_url_or_placeholder(value: str, field_name: str) -> None:
    text = str(value or "").strip()
    if not text or "${" in text:
        return
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} 必须是有效 URL")


def _warn_duplicate_bloggers(raw: dict[str, Any], path: Path) -> None:
    duplicates = _find_duplicate_bloggers(raw)
    if not duplicates:
        return
    summary = ", ".join(f"{sec_uid} ({count} 次)" for sec_uid, count in duplicates.items())
    logger.warning("配置中存在重复来源，运行时将自动去重: path=%s duplicates=%s", path, summary)


def _find_duplicate_bloggers(raw: dict[str, Any]) -> dict[str, int]:
    bloggers = raw.get("bloggers", []) or []
    if not isinstance(bloggers, list):
        return {}
    seen: dict[str, int] = {}
    for item in bloggers:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        sec_uid = str(item.get("sec_uid") or _extract_sec_uid_from_url(url)).strip()
        if not sec_uid:
            continue
        seen[sec_uid] = seen.get(sec_uid, 0) + 1
    return {sec_uid: count for sec_uid, count in seen.items() if count > 1}


def _extract_sec_uid_from_url(url: str) -> str:
    match = re.search(r"/user/([^/?#]+)", str(url or ""))
    return match.group(1) if match else ""


@contextmanager
def _config_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            logger.warning("配置文件锁不可用，继续执行非原子锁写入: %s", lock_path)
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _atomic_dump_yaml(path: Path, data: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)
