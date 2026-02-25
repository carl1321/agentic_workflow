"""MongoDB search for similar structures"""

import os
from typing import Any, Optional

# MongoDB连接配置
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "vasp_structures")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "calculations")


def get_mongo_client():
    """获取MongoDB客户端"""
    from pymongo import MongoClient
    return MongoClient(MONGO_URI)


def search_similar_structures(
    formula: Optional[str] = None,
    space_group: Optional[str] = None,
    elements: Optional[list[str]] = None,
    limit: int = 5
) -> list[dict[str, Any]]:
    """
    在MongoDB中搜索相似结构

    Args:
        formula: 化学式
        space_group: 空间群
        elements: 元素列表
        limit: 返回数量上限

    Returns:
        相似结构列表及其POTCAR配置
    """
    try:
        client = get_mongo_client()
        db = client[MONGO_DB]
        collection = db[MONGO_COLLECTION]

        # 构建查询条件
        query = {}

        if formula:
            query["formula"] = formula

        if space_group:
            query["space_group"] = space_group

        if elements:
            query["elements"] = {"$all": elements}

        # 执行查询
        cursor = collection.find(query).limit(limit)

        results = []
        for doc in cursor:
            results.append({
                "id": str(doc.get("_id")),
                "formula": doc.get("formula"),
                "space_group": doc.get("space_group"),
                "elements": doc.get("elements"),
                "potcar_config": doc.get("potcar_config", {}),
                "functional": doc.get("functional"),
                "encut": doc.get("encut"),
                "source": doc.get("source", "user_database"),
                "notes": doc.get("notes", "")
            })

        client.close()

        return {
            "success": True,
            "count": len(results),
            "results": results,
            "query": {
                "formula": formula,
                "space_group": space_group,
                "elements": elements
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "count": 0,
            "results": []
        }
