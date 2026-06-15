"""
安全配置存储模块
使用 SQLite + 加密存储敏感的模型配置信息
复用 state.sqlite3 数据库，只新增表
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

ENCRYPTION_KEY_ENV = "SC_ENCRYPTION_KEY"


class SecureConfigStore:
    """安全配置存储，支持加密的 API keys"""

    def __init__(self, db_path: str | Path, encryption_key: bytes | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        # 初始化加密器
        if encryption_key is None:
            encryption_key = self._get_or_create_encryption_key()
        self._cipher = Fernet(encryption_key)

        self._ensure_schema()

    def _get_or_create_encryption_key(self) -> bytes:
        """获取或创建加密密钥"""
        import os

        # 尝试从环境变量获取
        env_key = os.environ.get(ENCRYPTION_KEY_ENV)
        if env_key:
            return env_key.encode('utf-8')

        # 从密钥文件获取或创建
        key_file = self.db_path.parent / ".encryption_key"
        if key_file.exists():
            return key_file.read_bytes()

        # 生成新密钥
        new_key = Fernet.generate_key()
        key_file.write_bytes(new_key)
        key_file.chmod(0o600)  # 仅所有者可读写
        return new_key

    def _encrypt(self, plain_text: str) -> str:
        """加密文本"""
        if not plain_text:
            return ""
        encrypted_bytes = self._cipher.encrypt(plain_text.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def _decrypt(self, encrypted_text: str) -> str:
        """解密文本"""
        if not encrypted_text:
            return ""
        decrypted_bytes = self._cipher.decrypt(encrypted_text.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        """初始化数据库表结构，只新增表不影响现有表"""
        with self._lock, self._connect() as conn:
            # 模型供应商表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    api_key_encrypted TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_mode TEXT NOT NULL DEFAULT 'chat_completions',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # 模型表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    context_window INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (provider_id) REFERENCES model_providers(id) ON DELETE CASCADE,
                    UNIQUE(provider_id, model_id)
                )
            """)

            # 应用设置表（存储 embedding 和 image generation 配置）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_encrypted TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # 创建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_models_provider
                ON models(provider_id)
            """)
            self._ensure_column(conn, "model_providers", "sort_order", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "models", "sort_order", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "models", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    # ==================== Provider 操作 ====================

    def save_providers(self, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """保存供应商列表（会加密 API keys）"""
        import time
        now = int(time.time() * 1000)

        normalized_providers = []

        with self._lock, self._connect() as conn:
            # 清空现有数据
            conn.execute("DELETE FROM models")
            conn.execute("DELETE FROM model_providers")

            for provider_index, provider_data in enumerate(providers):
                provider_id = str(provider_data.get("id") or uuid.uuid4().hex).strip()
                name = str(provider_data.get("name") or "未命名供应商").strip()
                base_url = str(provider_data.get("baseUrl") or "").strip()
                api_key = str(provider_data.get("apiKey") or "").strip()
                provider = str(provider_data.get("provider") or "openrouter").strip()
                api_mode = str(provider_data.get("apiMode") or "chat_completions").strip()

                # 加密 API key
                api_key_encrypted = self._encrypt(api_key)

                # 保存供应商
                conn.execute("""
                    INSERT INTO model_providers
                    (id, name, base_url, api_key_encrypted, provider, api_mode, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (provider_id, name, base_url, api_key_encrypted, provider, api_mode, provider_index, now, now))

                # 保存模型
                raw_models = provider_data.get("models", [])
                models = raw_models if isinstance(raw_models, list) else []
                stored_models: list[dict[str, Any]] = []
                for model_index, model_data in enumerate(models):
                    if not isinstance(model_data, dict):
                        continue
                    model_id = str(model_data.get("id") or "").strip()
                    if not model_id:
                        continue

                    context_window = model_data.get("contextWindow")
                    model_uuid = f"{provider_id}::{model_id}"
                    stored_model = {
                        "id": model_id,
                        "contextWindow": context_window,
                    }
                    for key in (
                        "name",
                        "maxOutputTokens",
                        "inputModalities",
                        "outputModalities",
                        "supportedParameters",
                        "capabilities",
                        "pricing",
                        "ownedBy",
                        "created",
                        "description",
                    ):
                        value = model_data.get(key)
                        if value not in (None, "", [], {}):
                            stored_model[key] = value
                    metadata_json = json.dumps(
                        {
                            key: value
                            for key, value in stored_model.items()
                            if key not in {"id", "contextWindow"}
                        },
                        ensure_ascii=False,
                    )

                    conn.execute("""
                        INSERT INTO models
                        (id, provider_id, model_id, context_window, metadata_json, sort_order, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (model_uuid, provider_id, model_id, context_window, metadata_json, model_index, now))
                    stored_models.append(stored_model)

                normalized_providers.append({
                    "id": provider_id,
                    "name": name,
                    "baseUrl": base_url,
                    "apiKey": api_key,  # 返回明文供前端显示
                    "provider": provider,
                    "apiMode": api_mode,
                    "models": stored_models,
                })

        return normalized_providers

    def load_providers(self) -> list[dict[str, Any]]:
        """加载供应商列表（会解密 API keys）"""
        with self._lock, self._connect() as conn:
            provider_rows = conn.execute("""
                SELECT id, name, base_url, api_key_encrypted, provider, api_mode
                FROM model_providers
                ORDER BY sort_order ASC, updated_at DESC
            """).fetchall()

            providers = []
            for row in provider_rows:
                provider_id = row["id"]

                # 解密 API key
                api_key = self._decrypt(row["api_key_encrypted"])

                # 加载该供应商的模型
                model_rows = conn.execute("""
                    SELECT model_id, context_window, metadata_json
                    FROM models
                    WHERE provider_id = ?
                    ORDER BY sort_order ASC, model_id ASC
                """, (provider_id,)).fetchall()

                models = []
                for model_row in model_rows:
                    metadata: dict[str, Any] = {}
                    try:
                        parsed_metadata = json.loads(model_row["metadata_json"] or "{}")
                        if isinstance(parsed_metadata, dict):
                            metadata = parsed_metadata
                    except json.JSONDecodeError:
                        metadata = {}
                    models.append(
                        {
                            **metadata,
                            "id": model_row["model_id"],
                            "contextWindow": model_row["context_window"],
                        }
                    )

                providers.append({
                    "id": provider_id,
                    "name": row["name"],
                    "baseUrl": row["base_url"],
                    "apiKey": api_key,
                    "provider": row["provider"],
                    "apiMode": row["api_mode"],
                    "models": models,
                })

            return providers

    # ==================== Settings 操作 ====================

    def save_setting(self, key: str, value: dict[str, Any]) -> None:
        """保存加密设置项（如 embedding, imageGeneration）"""
        import time
        now = int(time.time() * 1000)

        # 加密整个 JSON 对象
        value_json = json.dumps(value, ensure_ascii=False)
        value_encrypted = self._encrypt(value_json)

        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO app_settings (key, value_encrypted, updated_at)
                VALUES (?, ?, ?)
            """, (key, value_encrypted, now))

    def has_setting(self, key: str) -> bool:
        """检查设置项是否已迁移到加密表。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
            return row is not None

    def load_setting(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """加载并解密设置项"""
        with self._lock, self._connect() as conn:
            row = conn.execute("""
                SELECT value_encrypted FROM app_settings WHERE key = ?
            """, (key,)).fetchone()

            if row is None:
                return default or {}

            value_json = self._decrypt(row["value_encrypted"])
            try:
                return json.loads(value_json)
            except json.JSONDecodeError:
                return default or {}

    # ==================== 迁移工具 ====================

    def migrate_from_json_file(self, json_path: Path) -> bool:
        """从旧的 JSON 文件迁移数据"""
        if not json_path.exists():
            return False

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        providers = data.get("providers", [])
        if not isinstance(providers, list):
            return False
        if not providers:
            return False

        self.save_providers(providers)
        json_path.unlink()
        return True


def get_secure_config_store(_root: Path) -> SecureConfigStore:
    """获取安全配置存储实例，使用 state.sqlite3 数据库"""
    from fastapi_app.app_config import STATE_DB_PATH

    return SecureConfigStore(STATE_DB_PATH)
