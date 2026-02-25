#!/usr/bin/env python3
"""
测试 conf.yaml 中的 ZOTERO 配置能否正确访问 Zotero 个人库。
用法: uv run python scripts/test_zotero.py
"""
import json
import os
import sys

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from src.config.loader import load_yaml_config

    config = load_yaml_config("conf.yaml") or {}
    zotero = config.get("ZOTERO") or {}
    if not isinstance(zotero, dict):
        print("❌ ZOTERO 配置格式错误")
        return 1

    library_id = (zotero.get("library_id") or "").strip()
    library_type = (zotero.get("library_type") or "user").strip().lower()
    api_key = (zotero.get("api_key") or "").strip()
    enabled = zotero.get("enabled", False)

    # 环境变量覆盖
    library_id = os.getenv("ZOTERO_LIBRARY_ID") or library_id
    library_type = os.getenv("ZOTERO_LIBRARY_TYPE") or library_type
    api_key = os.getenv("ZOTERO_API_KEY") or api_key

    print("=== Zotero 配置检查 ===")
    print(f"  enabled: {enabled}")
    print(f"  library_id: {library_id or '(空)'}")
    print(f"  library_type: {library_type}")
    print(f"  api_key: {'*' * 8 if api_key else '(空)'}")

    if not library_id or not api_key:
        print("\n❌ library_id 或 api_key 未配置")
        return 1

    try:
        from pyzotero import Zotero

        zot = Zotero(library_id, library_type, api_key)
        print("\n=== 1. 测试 top(limit=50) 顶层文献 ===")
        items = zot.top(limit=50)
        print(f"  返回 {len(items)} 条")

        print("\n=== 2. 测试 collections() 集合列表 ===")
        colls = zot.collections()
        print(f"  返回 {len(colls)} 个集合")
        for c in colls[:5]:
            d = c.get("data") or c
            print(f"    - {d.get('name', '?')} (key={d.get('key', '')})")

        print("\n=== 3. 测试 search(q='a', limit=20) 搜索 ===")
        try:
            search_items = zot.top(q="a", limit=20)
            print(f"  搜索 'a' 返回 {len(search_items)} 条")
        except Exception as se:
            print(f"  搜索异常: {se}")

        if items:
            print("\n  顶层文献示例:")
            for i, it in enumerate(items[:5], 1):
                data = it.get("data") or it
                title = (data.get("title") or "(无标题)")[:50]
                creators = data.get("creators", [])
                names = [
                    c.get("name") or f"{c.get('firstName','')} {c.get('lastName','')}".strip()
                    for c in creators[:2]
                ]
                print(f"    {i}. {title} | {', '.join(filter(None, names))}")
        else:
            print("\n  ⚠️ top() 返回 0 条，可能原因:")
            print("     - 文献尚未同步到 zotero.org（请在 Zotero 桌面版中点击同步）")
            print("     - library_id 不正确（个人库 ID 在 zotero.org/settings 查看）")
            print("     - API Key 权限不足（需勾选 library read）")

        print("\n✅ Zotero API 调用完成")
        return 0

    except Exception as e:
        print(f"\n❌ 访问失败: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
