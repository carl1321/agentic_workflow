#!/usr/bin/env python3
"""
查看指定计划下所有任务的 depends_on / idempotency_key / status，用于验证「创建视频」等
为何未被推进为 ready（依赖是否被 get_succeeded_dep_task 正确解析）。

用法（在项目根目录执行）:
  python scripts/inspect_plan_tasks.py <plan_id>
  PLAN_ID=xxx python scripts/inspect_plan_tasks.py

示例:
  python scripts/inspect_plan_tasks.py c6e1038b-3eef-4479-8990-d89a353c6e69
"""

import json
import os
import sys
from uuid import UUID

# 项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.server.plan.db import get_db_connection, get_succeeded_dep_task, list_tasks


def _deps_list(row) -> list:
    v = row.get("depends_on")
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v]
    if isinstance(v, str):
        try:
            obj = json.loads(v)
            return [str(x).strip() for x in obj] if isinstance(obj, list) else []
        except Exception:
            return []
    return []


def main():
    plan_id_str = (sys.argv[1:] and sys.argv[1]) or os.getenv("PLAN_ID")
    if not plan_id_str:
        print("用法: python scripts/inspect_plan_tasks.py <plan_id>  或设置环境变量 PLAN_ID")
        sys.exit(1)
    try:
        plan_id = UUID(plan_id_str)
    except ValueError:
        print(f"无效的 plan_id: {plan_id_str}")
        sys.exit(1)

    conn = get_db_connection()
    try:
        tasks = list_tasks(conn, plan_id)
    finally:
        conn.close()

    if not tasks:
        print(f"计划 {plan_id} 下无任务")
        return

    print(f"计划 {plan_id} 共 {len(tasks)} 个任务\n")
    for t in tasks:
        name = t.get("name") or "(未命名)"
        key = t.get("idempotency_key") or ""
        status = t.get("status") or ""
        deps = _deps_list(t)
        print(f"  任务: {name}")
        print(f"    idempotency_key: {key!r}")
        print(f"    status:          {status}")
        print(f"    depends_on:       {deps}")

        if status == "pending" and deps:
            conn2 = get_db_connection()
            try:
                for k in deps:
                    dep_task = get_succeeded_dep_task(conn2, plan_id, k)
                    if dep_task:
                        print(f"      依赖 key {k!r} -> 已解析为 idempotency_key={dep_task.get('idempotency_key')!r} (status={dep_task.get('status')})")
                    else:
                        print(f"      依赖 key {k!r} -> 未找到 status=succeeded 的任务（精确或 key+后缀 均无匹配）")
            finally:
                conn2.close()
        print()
    print("若「创建视频」的 depends_on 为 [\"分镜可视化\"] 且「分镜可视化」的 idempotency_key 为 \"分镜可视化.pptx\"，")
    print("get_succeeded_dep_task 会通过 key+\".pptx\" 匹配；若上面显示「未找到」请检查该依赖任务的 status 是否为 succeeded。")


if __name__ == "__main__":
    main()
