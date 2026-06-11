#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移模型配置从 JSON 文件到加密数据库
"""
from pathlib import Path
import sys
import os

# 设置 UTF-8 编码
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi_app.secure_config_store import get_secure_config_store
from fastapi_app.model_config_store import config_store_path
import json


def migrate():
    root = Path.cwd()
    json_path = config_store_path(root)

    if not json_path.exists():
        print("未找到 model-providers.json 文件")
        return

    print(f"读取 JSON 文件: {json_path}")

    # 读取 JSON 数据
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        providers = data.get("providers", [])
        print(f"找到 {len(providers)} 个供应商配置")
    except Exception as e:
        print(f"读取 JSON 失败: {e}")
        return

    # 获取安全存储实例
    secure_store = get_secure_config_store(root)

    # 检查是否已经迁移过
    existing = secure_store.load_providers()
    if existing:
        print(f"数据库中已有 {len(existing)} 个供应商配置")
        response = input("是否覆盖？(y/N): ")
        if response.lower() != 'y':
            print("取消迁移")
            return

    # 执行迁移
    print("开始迁移到加密数据库...")
    try:
        migrated = secure_store.migrate_from_json_file(json_path)
        if not migrated:
            print("没有可迁移的供应商配置")
            return
        print("迁移成功！")

        # 验证
        loaded = secure_store.load_providers()
        print(f"验证成功，数据库中有 {len(loaded)} 个供应商")

        for provider in loaded:
            print(f"  - {provider['name']}: {len(provider['models'])} 个模型")
            # 检查 API key 是否成功加密/解密
            if provider.get('apiKey'):
                print(f"    API Key: {provider['apiKey'][:8]}... (已加密存储)")

        print("原 model-providers.json 已删除")

    except Exception as e:
        print(f"迁移失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    migrate()
