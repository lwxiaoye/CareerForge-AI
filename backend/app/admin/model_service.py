"""模型广场 + 系统设置 — 业务逻辑层"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from typing import Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.admin.models import ModelConfig, ModelTestLog, SystemConfig
from app.admin.schemas import ModelCreate, ModelUpdate, ModelListQuery, ModelResponse, ModelTestResponse
from app.core.security import encrypt_api_key, decrypt_api_key  # Fernet-backed; re-exported for legacy callers
from app.infra.db import SessionLocal


# ── 模型 CRUD ────────────────────────────────────

def list_models(db: Session, query: ModelListQuery) -> dict:
    stmt = select(ModelConfig).where(ModelConfig.is_deleted == False)
    if query.capability:
        stmt = stmt.where(ModelConfig.capability == query.capability)
    if query.status:
        stmt = stmt.where(ModelConfig.status == query.status)
    if query.open_to_student is not None:
        stmt = stmt.where(ModelConfig.open_to_student == query.open_to_student)
    if query.keyword:
        kw = f"%{query.keyword}%"
        stmt = stmt.where(
            (ModelConfig.display_name.ilike(kw))
            | (ModelConfig.model_identifier.ilike(kw))
            | (ModelConfig.provider.ilike(kw))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ModelConfig.created_at.desc()).offset((query.page - 1) * query.size).limit(query.size)).all()
    return {"list": [ModelResponse.model_validate(r) for r in rows], "total": total or 0, "page": query.page, "size": query.size}


def create_model(db: Session, payload: ModelCreate) -> ModelResponse:
    model = ModelConfig(
        display_name=payload.display_name, provider=payload.provider, deploy_type=payload.deploy_type,
        capability=payload.capability, protocols=payload.protocols, base_url=payload.base_url,
        api_key_cipher=encrypt_api_key(payload.api_key) if payload.api_key else None,
        model_identifier=payload.model_identifier, dify_model_ref=payload.dify_model_ref,
        context_length=payload.context_length, default_temp=payload.default_temp,
        max_output=payload.max_output, timeout_sec=payload.timeout_sec,
        open_to_student=payload.open_to_student,
    )
    db.add(model); db.commit(); db.refresh(model)
    return ModelResponse.model_validate(model)


def _get_model(db: Session, model_id: int) -> ModelConfig:
    model = db.scalar(select(ModelConfig).where(ModelConfig.id == model_id, ModelConfig.is_deleted == False))
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    return model


def get_model_detail(db: Session, model_id: int) -> ModelResponse:
    return ModelResponse.model_validate(_get_model(db, model_id))


def update_model(db: Session, model_id: int, payload: ModelUpdate) -> ModelResponse:
    model = _get_model(db, model_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "api_key" in update_data:
        key = update_data.pop("api_key")
        update_data["api_key_cipher"] = encrypt_api_key(key) if key else None
    for field, value in update_data.items():
        setattr(model, field, value)
    db.commit(); db.refresh(model)
    return ModelResponse.model_validate(model)


def delete_model(db: Session, model_id: int) -> None:
    _get_model(db, model_id).is_deleted = True
    db.commit()


def toggle_open(db: Session, model_id: int, open_flag: bool) -> ModelResponse:
    model = _get_model(db, model_id)
    model.open_to_student = open_flag
    db.commit(); db.refresh(model)
    return ModelResponse.model_validate(model)


# ── 测试连接 ────────────────────────────────────

def _api_protocol(model: ModelConfig) -> str:
    raw = (model.protocols or "").lower()
    base_url = (model.base_url or "").lower()
    provider = (model.provider or "").lower()
    if "baidu_ocr" in raw or (model.capability == "ocr" and "baidu" in provider):
        return "baidu_ocr"
    if "responses" in raw or base_url.endswith("/responses"):
        return "responses"
    if "anthropic" in raw or "messages" in raw or "/anthropic" in base_url or "api.anthropic.com" in base_url:
        return "anthropic"
    return "openai"


def _endpoint_url(base_url: str, suffix: str) -> str:
    base = (base_url or "").rstrip("/")
    clean_suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    if base.endswith(clean_suffix):
        return base
    return f"{base}{clean_suffix}"


def _split_baidu_ocr_credentials(raw: str | None) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value:
        raise ValueError("百度 OCR 缺少 API Key / Secret Key")
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("百度 OCR 密钥格式错误，请按 API Key|Secret Key 填写") from exc
        api_key = str(parsed.get("api_key") or parsed.get("client_id") or "").strip()
        secret_key = str(parsed.get("secret_key") or parsed.get("client_secret") or "").strip()
    else:
        api_key, sep, secret_key = value.partition("|")
        api_key = api_key.strip()
        secret_key = secret_key.strip() if sep else ""
    if not api_key or not secret_key:
        raise ValueError("百度 OCR 需要同时提供 API Key 和 Secret Key，请按 API Key|Secret Key 填写")
    return api_key, secret_key


def _baidu_ocr_endpoint(base_url: str, model_identifier: str) -> str:
    base = (base_url or "https://aip.baidubce.com").rstrip("/")
    endpoint = (model_identifier or "general_basic").strip().strip("/")
    if "/rest/2.0/ocr/v1/" in base:
        return base
    return f"{base}/rest/2.0/ocr/v1/{endpoint}"


def _tiny_test_png_base64() -> str:
    try:
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (480, 160), "white")
        draw = ImageDraw.Draw(image)
        draw.text((24, 36), "CareerForge OCR Test", fill="black")
        draw.text((24, 84), "Resume 123456", fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        # Fallback to the old tiny PNG if Pillow is unavailable.
        return (
            "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAQAAAC1+jfqAAAAK0lEQVR4nGNkYGBg+A8EGJgY/v//"
            "PwMDA8NQh0EwCkbBqGg0GoaDQaEBAI9lB8fV64DFAAAAAElFTkSuQmCC"
        )


async def test_model_connection(db: Session, model_id: int) -> ModelTestResponse:
    model = _get_model(db, model_id)
    api_key = decrypt_api_key(model.api_key_cipher) if model.api_key_cipher else None
    success, latency_ms, error_message = False, None, None
    http_status, response_body, request_url, error_summary = None, None, None, None

    try:
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=httpx.Timeout(model.timeout_sec or 30)) as client:
            base_url = (model.base_url or "").rstrip("/")
            protocol = _api_protocol(model)
            if protocol == "anthropic":
                request_url = _endpoint_url(base_url, "/v1/messages")
                resp = await client.post(
                    request_url,
                    headers={
                        "x-api-key": api_key or "",
                        "api-key": api_key or "",
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model.model_identifier,
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": min(model.max_output or 4096, 64),
                        "stream": False,
                    },
                )
            elif protocol == "responses":
                request_url = _endpoint_url(base_url, "/responses")
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = await client.post(
                    request_url,
                    headers=headers,
                    json={
                        "model": model.model_identifier,
                        "input": "Reply OK.",
                        "max_output_tokens": min(model.max_output or 4096, 64),
                        "stream": False,
                    },
                )
            elif protocol == "baidu_ocr":
                baidu_api_key, baidu_secret_key = _split_baidu_ocr_credentials(api_key)
                token_resp = await client.get(
                    _endpoint_url(base_url, "/oauth/2.0/token"),
                    params={
                        "grant_type": "client_credentials",
                        "client_id": baidu_api_key,
                        "client_secret": baidu_secret_key,
                    },
                )
                token_resp.raise_for_status()
                token_payload = token_resp.json()
                access_token = str(token_payload.get("access_token") or "").strip()
                if not access_token:
                    raise ValueError(f"百度 OCR 未返回 access_token: {token_resp.text[:180]}")
                request_url = f"{_baidu_ocr_endpoint(base_url, model.model_identifier)}?access_token={access_token}"
                resp = await client.post(
                    request_url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={"image": _tiny_test_png_base64()},
                )
            else:
                request_url = _endpoint_url(base_url, "/chat/completions")
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = await client.post(
                    request_url,
                    headers=headers,
                    json={
                        "model": model.model_identifier,
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": min(model.max_output or 4096, 64),
                        "stream": False,
                    },
                )
        latency_ms = int((time.perf_counter() - start) * 1000)
        http_status = resp.status_code
        response_body = resp.text[:500]
        success = 200 <= resp.status_code < 300
        if success and protocol == "baidu_ocr":
            try:
                payload = resp.json()
            except Exception:
                payload = {}
            if payload.get("error_code"):
                success = False
                error_message = f"百度 OCR 错误: {payload.get('error_msg') or payload.get('error_code')}"
                error_summary = error_message
        if not success and not error_message:
            error_message = f"HTTP {resp.status_code}: {resp.text[:180]}"
            error_summary = error_message
    except httpx.TimeoutException:
        error_message = f"连接超时 ({model.timeout_sec or 30}s)"
        error_summary = "连接超时"
    except httpx.ConnectError:
        error_message = "无法连接到目标地址"
        error_summary = "无法连接"
    except Exception as e:
        error_message = str(e)[:500]
        error_summary = error_message[:100]

    log_entry = ModelTestLog(model_id=model.id, success=success, latency_ms=latency_ms, error_message=error_message)
    db.add(log_entry); db.commit(); db.refresh(log_entry)
    return ModelTestResponse(
        success=log_entry.success,
        latency_ms=log_entry.latency_ms,
        error_message=log_entry.error_message,
        model_id=log_entry.model_id,
        tested_at=log_entry.tested_at,
        http_status=http_status,
        response_body=response_body,
        request_url=request_url,
        error_summary=error_summary,
    )


test_model_connection.__test__ = False


async def test_batch(db: Session) -> list[ModelTestResponse]:
    model_ids = list(db.scalars(
        select(ModelConfig.id).where(ModelConfig.is_deleted == False)
    ).all())

    async def _run(mid: int) -> ModelTestResponse:
        with SessionLocal() as local_db:
            return await test_model_connection(local_db, mid)

    return list(await asyncio.gather(*(_run(mid) for mid in model_ids)))


# ── 种子数据 ────────────────────────────────────

DEFAULT_MODELS = [
    {
        "display_name": "DeepSeek V4 Pro",
        "provider": "DeepSeek",
        "deploy_type": "cloud",
        "capability": "chat",
        "protocols": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model_identifier": "deepseek-v4-pro",
        "context_length": 131072,
        "default_temp": 0.7,
        "max_output": 32768,
        "timeout_sec": 120,
        "open_to_student": False,
    },
    {
        "display_name": "DeepSeek V4 Flash",
        "provider": "DeepSeek",
        "deploy_type": "cloud",
        "capability": "chat",
        "protocols": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model_identifier": "deepseek-v4-flash",
        "context_length": 131072,
        "default_temp": 0.7,
        "max_output": 32768,
        "timeout_sec": 120,
        "open_to_student": False,
    },
    {
        "display_name": "DeepSeek Chat (V3)",
        "provider": "DeepSeek",
        "deploy_type": "cloud",
        "capability": "chat",
        "protocols": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model_identifier": "deepseek-chat",
        "context_length": 65536,
        "default_temp": 0.7,
        "max_output": 8192,
        "timeout_sec": 120,
        "open_to_student": True,
    },
]


def seed_default_models(db: Session) -> None:
    """首次启动时预置模型广场默认模型（仅当 model_config 表为空时执行）"""
    existing = db.scalar(select(func.count()).select_from(ModelConfig).where(ModelConfig.is_deleted == False))
    if existing and existing > 0:
        return

    for item in DEFAULT_MODELS:
        model = ModelConfig(
            display_name=item["display_name"],
            provider=item["provider"],
            deploy_type=item["deploy_type"],
            capability=item["capability"],
            protocols=item["protocols"],
            base_url=item["base_url"],
            api_key_cipher=None,  # API Key 需管理员手动配置
            model_identifier=item["model_identifier"],
            context_length=item["context_length"],
            default_temp=item["default_temp"],
            max_output=item["max_output"],
            timeout_sec=item["timeout_sec"],
            open_to_student=item["open_to_student"],
            status="active",
        )
        db.add(model)
    db.commit()


# ── 系统配置 ────────────────────────────────────

DEFAULT_CONFIG: dict[str, str] = {
    "platform_name": "CareerForge",
    "maintenance_mode": "false",
    "maintenance_message": "系统维护中，请稍后再试",
    "announcement": "",
    "announcement_enabled": "false",
}



# ── 公告管理 ─────────────────────────────────────

from app.admin.models import Announcement
from app.admin.schemas import AnnouncementCreate, AnnouncementUpdate, AnnouncementResponse, AnnouncementListResponse


def list_announcements(db: Session, page: int = 1, size: int = 20, active_only: bool = False) -> AnnouncementListResponse:
    stmt = select(Announcement)
    if active_only:
        stmt = stmt.where(Announcement.is_active == True)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Announcement.priority.desc(), Announcement.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return AnnouncementListResponse(
        list=[AnnouncementResponse.model_validate(r) for r in rows],
        total=total or 0,
    )


def create_announcement(db: Session, payload: AnnouncementCreate, user_id: int | None = None) -> AnnouncementResponse:
    ann = Announcement(
        title=payload.title,
        content=payload.content,
        announcement_type=payload.announcement_type,
        priority=payload.priority,
        is_active=payload.is_active,
        start_time=payload.start_time,
        end_time=payload.end_time,
        created_by=user_id,
    )
    db.add(ann); db.commit(); db.refresh(ann)
    return AnnouncementResponse.model_validate(ann)


def get_announcement(db: Session, ann_id: int) -> AnnouncementResponse:
    ann = db.scalar(select(Announcement).where(Announcement.id == ann_id))
    if not ann:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    return AnnouncementResponse.model_validate(ann)


def update_announcement(db: Session, ann_id: int, payload: AnnouncementUpdate) -> AnnouncementResponse:
    ann = db.scalar(select(Announcement).where(Announcement.id == ann_id))
    if not ann:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ann, field, value)
    db.commit(); db.refresh(ann)
    return AnnouncementResponse.model_validate(ann)


def delete_announcement(db: Session, ann_id: int) -> None:
    ann = db.scalar(select(Announcement).where(Announcement.id == ann_id))
    if not ann:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    db.delete(ann)
    db.commit()

def get_all_config(db: Session) -> dict[str, str | None]:
    rows = db.scalars(select(SystemConfig)).all()
    config = {r.config_key: r.config_value for r in rows}
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
    return config


def update_config(db: Session, items: list[dict]) -> dict[str, str | None]:
    for item in items:
        key = item["config_key"]
        value = item.get("config_value")
        row = db.scalar(select(SystemConfig).where(SystemConfig.config_key == key))
        if row:
            row.config_value = value
        else:
            db.add(SystemConfig(config_key=key, config_value=value))
    db.commit()
    return get_all_config(db)
