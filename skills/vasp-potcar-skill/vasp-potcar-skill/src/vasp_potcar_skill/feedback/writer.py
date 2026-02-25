"""
反馈数据回写器

目的：
    将用户确认的赝势配置回写到MongoDB，丰富历史数据库。
"""

import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class FeedbackWriter:
    """
    反馈回写器

    职责：
        1. 将用户采纳的配置写入MongoDB
        2. 更新已有记录的使用频次
        3. 标记数据来源（用户反馈 vs 文献导入）
    """

    COLLECTION_NAME = "user_potcar_feedback"

    def __init__(self, mongo_uri: Optional[str] = None, database: Optional[str] = None):
        """
        初始化反馈回写器

        Args:
            mongo_uri: MongoDB连接URI
            database: 数据库名称
        """
        self.mongo_uri = mongo_uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        self.database = database or os.environ.get("MONGO_DB", "vasp_structures")
        self._client = None
        self._db = None
        self._collection = None

    def _get_collection(self):
        """获取或创建MongoDB集合"""
        if self._collection is not None:
            return self._collection

        try:
            from pymongo import MongoClient

            self._client = MongoClient(self.mongo_uri)
            self._db = self._client[self.database]
            self._collection = self._db[self.COLLECTION_NAME]

            # 创建索引
            self._collection.create_index("formula")
            self._collection.create_index("elements")
            self._collection.create_index("space_group")
            self._collection.create_index([("formula", 1), ("space_group", 1)])

            logger.info(f"Connected to MongoDB collection: {self.COLLECTION_NAME}")
            return self._collection

        except ImportError:
            logger.error("pymongo not installed. Run: pip install pymongo")
            return None
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            return None

    def write_to_mongodb(
        self,
        formula: str,
        space_group: str,
        elements: list,
        potcar_config: dict,
        metadata: dict = None
    ) -> Optional[str]:
        """
        回写到MongoDB

        Args:
            formula: 化学式（如 "LiFePO4"）
            space_group: 空间群符号
            elements: 元素列表
            potcar_config: 赝势配置，如 {"Li": "Li_sv", "Fe": "Fe_pv", ...}
            metadata: 额外元数据

        Returns:
            插入的记录ID，失败返回None
        """
        collection = self._get_collection()
        if collection is None:
            logger.warning("MongoDB not available, skipping write")
            return None

        # 构建文档
        document = {
            "formula": formula,
            "space_group": space_group,
            "elements": elements,
            "potcar_config": potcar_config,
            "source": "user_feedback",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "usage_count": 1,
            "verified": True  # 用户反馈视为已验证
        }

        if metadata:
            document["metadata"] = metadata

        try:
            # 检查是否存在相同配置
            existing = collection.find_one({
                "formula": formula,
                "space_group": space_group,
                "potcar_config": potcar_config
            })

            if existing:
                # 更新使用次数
                self.update_usage_count(str(existing["_id"]))
                logger.info(f"Updated existing record for {formula}")
                return str(existing["_id"])

            # 插入新记录
            result = collection.insert_one(document)
            logger.info(f"Inserted new feedback record for {formula}: {result.inserted_id}")
            return str(result.inserted_id)

        except Exception as e:
            logger.error(f"Failed to write to MongoDB: {e}")
            return None

    def update_usage_count(self, record_id: str) -> bool:
        """
        更新记录的使用次数

        Args:
            record_id: 记录的MongoDB ObjectId字符串

        Returns:
            是否更新成功
        """
        collection = self._get_collection()
        if collection is None:
            return False

        try:
            from bson import ObjectId

            result = collection.update_one(
                {"_id": ObjectId(record_id)},
                {
                    "$inc": {"usage_count": 1},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )

            if result.modified_count > 0:
                logger.debug(f"Updated usage count for {record_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to update usage count: {e}")
            return False

    def batch_write(self, records: list[dict]) -> dict:
        """
        批量写入多条记录

        Args:
            records: 记录列表，每条记录包含 formula, space_group, elements, potcar_config

        Returns:
            写入结果统计
        """
        collection = self._get_collection()
        if collection is None:
            return {"success": False, "error": "MongoDB not available"}

        inserted = 0
        updated = 0
        failed = 0

        for record in records:
            try:
                result = self.write_to_mongodb(
                    formula=record.get("formula"),
                    space_group=record.get("space_group", ""),
                    elements=record.get("elements", []),
                    potcar_config=record.get("potcar_config", {}),
                    metadata=record.get("metadata")
                )

                if result:
                    # 简单判断是新插入还是更新
                    # 实际上write_to_mongodb内部已经处理了
                    inserted += 1
                else:
                    failed += 1

            except Exception as e:
                logger.error(f"Failed to write record: {e}")
                failed += 1

        return {
            "success": True,
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
            "total": len(records)
        }

    def query_user_feedback(
        self,
        formula: str = None,
        elements: list = None,
        limit: int = 10
    ) -> list[dict]:
        """
        查询用户反馈记录

        Args:
            formula: 化学式筛选
            elements: 元素列表筛选
            limit: 返回数量限制

        Returns:
            匹配的反馈记录列表
        """
        collection = self._get_collection()
        if collection is None:
            return []

        query = {"source": "user_feedback"}

        if formula:
            query["formula"] = formula

        if elements:
            query["elements"] = {"$all": elements}

        try:
            cursor = collection.find(query).sort("usage_count", -1).limit(limit)

            results = []
            for doc in cursor:
                doc["_id"] = str(doc["_id"])
                results.append(doc)

            return results

        except Exception as e:
            logger.error(f"Failed to query feedback: {e}")
            return []

    def get_popular_configs(self, element: str, limit: int = 5) -> list[dict]:
        """
        获取某元素最常用的赝势配置

        Args:
            element: 元素符号
            limit: 返回数量

        Returns:
            按使用频率排序的配置列表
        """
        collection = self._get_collection()
        if collection is None:
            return []

        try:
            # 聚合查询
            pipeline = [
                {"$match": {"elements": element}},
                {"$project": {
                    "potcar": f"$potcar_config.{element}",
                    "usage_count": 1,
                    "formula": 1
                }},
                {"$group": {
                    "_id": "$potcar",
                    "total_usage": {"$sum": "$usage_count"},
                    "formulas": {"$addToSet": "$formula"}
                }},
                {"$sort": {"total_usage": -1}},
                {"$limit": limit}
            ]

            results = list(collection.aggregate(pipeline))

            return [
                {
                    "potcar": r["_id"],
                    "usage_count": r["total_usage"],
                    "example_formulas": r["formulas"][:3]
                }
                for r in results if r["_id"]
            ]

        except Exception as e:
            logger.error(f"Failed to get popular configs: {e}")
            return []

    def close(self):
        """关闭MongoDB连接"""
        if self._client:
            self._client.close()
            self._client = None
            self._collection = None
            logger.info("MongoDB connection closed")
