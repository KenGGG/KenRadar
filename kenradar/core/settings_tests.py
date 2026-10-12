"""Explicit draft probes. Validation and saving never call these probes."""
from pathlib import Path
import os
import subprocess
from typing import Literal
import requests
from pydantic import BaseModel, ConfigDict, Field
from .settings import SettingsDraft, RevisionConflict, _candidate, revision
from .config import AppConfig, _config_lock, _expand_env_vars


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    draft: SettingsDraft
    kind: Literal["ai_readonly", "github_dry_run", "feishu_send"]
    confirmed_external: bool = False
    provider_index: int = Field(default=0, ge=0)


def probe(path, payload):
    path = Path(path)
    request = ProbeRequest.model_validate(payload)
    with _config_lock(path):
        if revision(path) != request.draft.expected_revision:
            raise RevisionConflict("configuration changed")
        candidate = _expand_env_vars(_candidate(path, request.draft))
    if request.kind == "github_dry_run":
        if request.draft.group != "delivery":
            raise ValueError("GitHub probe belongs to delivery")
        # Local read-only Git check. Never commits, pushes, or modifies credentials.
        result = subprocess.run(["git", "-C", str(path.parent.parent), "rev-parse", "--is-inside-work-tree"], capture_output=True, timeout=10)
        return {"ok": result.returncode == 0, "saved": False, "network": False, "sent_message": False, "scope": "local_git_only", "github_remote_verified": False}
    if not request.confirmed_external:
        return {"ok": False, "saved": False, "network": False, "sent_message": False, "confirmation_required": True}
    with requests.Session() as session:
        session.trust_env = False
        if request.kind == "ai_readonly":
            if request.draft.group != "transcription_ai":
                raise ValueError("AI probe belongs to transcription_ai")
            providers = candidate.get("ai", {}).get("organizer", {}).get("providers", [])
            if request.provider_index >= len(providers):
                raise ValueError("provider does not exist")
            provider = providers[request.provider_index]
            from .organizer import ContentOrganizer
            resolver = ContentOrganizer.__new__(ContentOrganizer)
            resolver.config = AppConfig(raw=candidate, path=path)
            key = resolver._provider_api_key(provider)
            endpoint = str(provider.get("endpoint") or "").rstrip("/")
            if not endpoint.startswith(("http://", "https://")):
                raise ValueError("invalid endpoint")
            response = session.get(endpoint + "/models", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=(5, 15), allow_redirects=False)
            return {"ok": response.ok, "saved": False, "network": True, "sent_message": False, "http_status": response.status_code, "scope": "models_endpoint_only", "organizer_verified": False}
        if request.draft.group != "delivery":
            raise ValueError("Feishu probe belongs to delivery")
        webhook = candidate.get("notification", {}).get("channels", {}).get("feishu", {}).get("webhook_url")
        if not webhook:
            raise ValueError("webhook not configured")
        response = session.post(webhook, json={"msg_type": "text", "content": {"text": "KenRadar 连接测试：这是一条手动确认发送的测试消息。"}}, timeout=(5, 15), allow_redirects=False)
        value = response.json() if response.ok else {}
        delivered = response.ok and value.get("code", value.get("StatusCode", -1)) == 0
        return {"ok": delivered, "saved": False, "network": True, "sent_message": delivered, "http_status": response.status_code, "delivery_status": "confirmed" if delivered else "unknown"}
