# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from pymongo import MongoClient

from src.config.loader import get_bool_env, get_str_env

logger = logging.getLogger(__name__)

# Disable pymongo debug logs
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("pymongo.topology").setLevel(logging.WARNING)
logging.getLogger("pymongo.serverSelection").setLevel(logging.WARNING)
logging.getLogger("pymongo.connection").setLevel(logging.WARNING)


class DataExtractionRecordManager:
    """Manages data extraction task records with persistent storage."""

    def __init__(self, db_uri: Optional[str] = None) -> None:
        """
        Initialize the DataExtractionRecordManager with database connections.

        Args:
            db_uri: Database connection URI. Supports MongoDB (mongodb://) and PostgreSQL (postgresql://)
        """
        self.db_uri = db_uri or get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
        self.mongo_client = None
        self.mongo_db = None
        self.postgres_conn = None

        if self.db_uri.startswith("mongodb://"):
            self._init_mongodb()
        elif self.db_uri.startswith("postgresql://") or self.db_uri.startswith("postgres://"):
            self._init_postgresql()
        else:
            logger.warning(
                f"Unsupported database URI scheme: {self.db_uri}. "
                "Supported schemes: mongodb://, postgresql://, postgres://"
            )

    def _init_mongodb(self) -> None:
        """Initialize MongoDB connection."""
        try:
            self.mongo_client = MongoClient(self.db_uri)
            self.mongo_db = self.mongo_client.checkpointing_db
            self.mongo_client.admin.command("ping")
            logger.info("Successfully connected to MongoDB for data extraction records")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    def _init_postgresql(self) -> None:
        """Initialize PostgreSQL connection and create table if needed."""
        try:
            self.postgres_conn = psycopg.connect(self.db_uri, row_factory=dict_row)
            logger.info("Successfully connected to PostgreSQL for data extraction records")
            self._create_table()
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")

    def _create_table(self) -> None:
        """Create the three data extraction tables if they don't exist."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Step 1: Files table
                create_files_table_sql = """
                CREATE TABLE IF NOT EXISTS data_extraction_files (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    task_id UUID NOT NULL UNIQUE,
                    task_name VARCHAR(255),
                    extraction_type VARCHAR(50) NOT NULL,
                    file_name VARCHAR(255),
                    file_size BIGINT,
                    file_base64 TEXT,
                    pdf_url TEXT,
                    model_name VARCHAR(100),
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_data_extraction_files_task_id 
                    ON data_extraction_files(task_id);
                CREATE INDEX IF NOT EXISTS idx_data_extraction_files_created_at 
                    ON data_extraction_files(created_at DESC);
                """
                cursor.execute(create_files_table_sql)
                
                # Step 2: Categories table
                create_categories_table_sql = """
                CREATE TABLE IF NOT EXISTS data_extraction_categories (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    task_id UUID NOT NULL UNIQUE,
                    categories JSONB NOT NULL,
                    result_json TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (task_id) REFERENCES data_extraction_files(task_id) ON DELETE CASCADE
                );
                
                CREATE INDEX IF NOT EXISTS idx_data_extraction_categories_task_id 
                    ON data_extraction_categories(task_id);
                """
                cursor.execute(create_categories_table_sql)
                
                # Step 3: Data table
                create_data_table_sql = """
                CREATE TABLE IF NOT EXISTS data_extraction_data (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    task_id UUID NOT NULL UNIQUE,
                    selected_categories JSONB NOT NULL,
                    table_data JSONB NOT NULL,
                    result_json TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (task_id) REFERENCES data_extraction_files(task_id) ON DELETE CASCADE
                );
                
                CREATE INDEX IF NOT EXISTS idx_data_extraction_data_task_id 
                    ON data_extraction_data(task_id);
                """
                cursor.execute(create_data_table_sql)
                
                self.postgres_conn.commit()
                logger.info("Data extraction tables (files, categories, data) created/verified successfully")
        except Exception as e:
            logger.error(f"Failed to create/update data extraction tables: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()

    def save_extraction_record(
        self,
        task_name: Optional[str] = None,
        extraction_type: str = "material_extraction",
        extraction_step: int = 1,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_base64: Optional[str] = None,
        pdf_url: Optional[str] = None,
        model_name: Optional[str] = None,
        categories: Optional[Dict] = None,
        selected_categories: Optional[Dict] = None,
        table_data: Optional[List] = None,
        result_json: Optional[str] = None,
        metadata: Optional[Dict] = None,
        record_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Save or update a data extraction record to the appropriate table based on step.

        Args:
            task_name: Name of the task
            extraction_type: Type of extraction (material_extraction or prompt_extraction)
            extraction_step: Current step (1, 2, or 3)
            file_name: Name of the uploaded file
            file_size: Size of the file in bytes
            file_base64: Base64 encoded file content (optional)
            pdf_url: PDF URL if used
            model_name: Model name used
            categories: Categories from step 2
            selected_categories: Selected categories for step 3
            table_data: Table data from step 3
            result_json: Complete result JSON
            metadata: Additional metadata
            record_id: Existing record ID to update (deprecated, use task_id)
            task_id: Task ID to link records across steps (if None, generates new for step 1)

        Returns:
            Task ID if successful, None otherwise
        """
        try:
            if self.postgres_conn:
                return self._save_to_postgresql(
                    task_name=task_name,
                    extraction_type=extraction_type,
                    extraction_step=extraction_step,
                    file_name=file_name,
                    file_size=file_size,
                    file_base64=file_base64,
                    pdf_url=pdf_url,
                    model_name=model_name,
                    categories=categories,
                    selected_categories=selected_categories,
                    table_data=table_data,
                    result_json=result_json,
                    metadata=metadata,
                    record_id=record_id,
                    task_id=task_id,
                )
            elif self.mongo_db:
                return self._save_to_mongodb(
                    task_name=task_name,
                    extraction_type=extraction_type,
                    extraction_step=extraction_step,
                    file_name=file_name,
                    file_size=file_size,
                    file_base64=file_base64,
                    pdf_url=pdf_url,
                    model_name=model_name,
                    categories=categories,
                    selected_categories=selected_categories,
                    table_data=table_data,
                    result_json=result_json,
                    metadata=metadata,
                    record_id=record_id,
                    task_id=task_id,
                )
            else:
                logger.error("No database connection available")
                return None
        except Exception as e:
            logger.error(f"Failed to save extraction record: {e}", exc_info=True)
            return None

    def _save_to_postgresql(
        self,
        task_name: Optional[str] = None,
        extraction_type: str = "material_extraction",
        extraction_step: int = 1,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_base64: Optional[str] = None,
        pdf_url: Optional[str] = None,
        model_name: Optional[str] = None,
        categories: Optional[Dict] = None,
        selected_categories: Optional[Dict] = None,
        table_data: Optional[List] = None,
        result_json: Optional[str] = None,
        metadata: Optional[Dict] = None,
        record_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[str]:
        """Save record to PostgreSQL based on extraction step."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Determine task_id
                current_task_id: Optional[UUID] = None
                if task_id:
                    current_task_id = UUID(task_id)
                elif record_id:
                    # Legacy support: try to get task_id from files table using record_id
                    cursor.execute(
                        "SELECT task_id FROM data_extraction_files WHERE id = %s",
                        (UUID(record_id),)
                    )
                    result = cursor.fetchone()
                    if result:
                        current_task_id = result["task_id"]
                
                # Step 1: Save to files table
                if extraction_step == 1:
                    if current_task_id:
                        # Update existing file record
                        update_sql = """
                        UPDATE data_extraction_files
                        SET task_name = COALESCE(%s, task_name),
                            extraction_type = %s,
                            file_name = COALESCE(%s, file_name),
                            file_size = COALESCE(%s, file_size),
                            file_base64 = COALESCE(%s, file_base64),
                            pdf_url = COALESCE(%s, pdf_url),
                            model_name = COALESCE(%s, model_name),
                            metadata = COALESCE(%s::jsonb, metadata),
                            updated_at = NOW()
                        WHERE task_id = %s
                        RETURNING task_id
                        """
                        cursor.execute(
                            update_sql,
                            (
                                task_name,
                                extraction_type,
                                file_name,
                                file_size,
                                file_base64,
                                pdf_url,
                                model_name,
                                json.dumps(metadata) if metadata else None,
                                current_task_id,
                            ),
                        )
                    else:
                        # Insert new file record
                        current_task_id = uuid4()
                        insert_sql = """
                        INSERT INTO data_extraction_files (
                            task_id, task_name, extraction_type,
                            file_name, file_size, file_base64, pdf_url, model_name, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        RETURNING task_id
                        """
                        cursor.execute(
                            insert_sql,
                            (
                                current_task_id,
                                task_name,
                                extraction_type,
                                file_name,
                                file_size,
                                file_base64,
                                pdf_url,
                                model_name,
                                json.dumps(metadata) if metadata else None,
                            ),
                        )
                    result = cursor.fetchone()
                    self.postgres_conn.commit()
                    task_id_str = str(result["task_id"]) if result else None
                    logger.info(f"Saved extraction file record (step 1): task_id={task_id_str}")
                    return task_id_str
                
                # Step 2: Save to categories table
                elif extraction_step == 2:
                    if not current_task_id:
                        logger.error("Cannot save categories: task_id is required for step 2")
                        return None
                    
                    # Verify that the file record exists (required for foreign key constraint)
                    cursor.execute(
                        "SELECT task_id FROM data_extraction_files WHERE task_id = %s",
                        (current_task_id,)
                    )
                    file_record = cursor.fetchone()
                    if not file_record:
                        logger.error(f"Cannot save categories: file record with task_id={current_task_id} does not exist")
                        return None
                    
                    if not categories:
                        logger.warning("Saving categories with empty data - this may be an update operation")
                        # Allow empty categories for update operations, but log a warning
                    
                    # Upsert categories record
                    upsert_sql = """
                    INSERT INTO data_extraction_categories (task_id, categories, result_json)
                    VALUES (%s, %s::jsonb, %s)
                    ON CONFLICT (task_id) 
                    DO UPDATE SET
                        categories = EXCLUDED.categories,
                        result_json = EXCLUDED.result_json,
                        updated_at = NOW()
                    RETURNING task_id
                    """
                    cursor.execute(
                        upsert_sql,
                        (
                            current_task_id,
                            json.dumps(categories) if categories else json.dumps({}),
                            result_json,
                        ),
                    )
                    result = cursor.fetchone()
                    self.postgres_conn.commit()
                    task_id_str = str(result["task_id"]) if result else None
                    
                    # Log categories details
                    if categories:
                        logger.info(
                            f"[Step 2] Saved categories record - task_id={task_id_str}, "
                            f"materials={len(categories.get('materials', []))}, "
                            f"processes={len(categories.get('processes', []))}, "
                            f"properties={len(categories.get('properties', []))}"
                        )
                    else:
                        logger.info(f"[Step 2] Saved categories record (empty) - task_id={task_id_str}")
                    
                    return task_id_str
                
                # Step 3: Save to data table
                elif extraction_step == 3:
                    if not current_task_id:
                        logger.error("Cannot save data: task_id is required for step 3")
                        return None
                    
                    # Verify that the file record exists (required for foreign key constraint)
                    cursor.execute(
                        "SELECT task_id FROM data_extraction_files WHERE task_id = %s",
                        (current_task_id,)
                    )
                    file_record = cursor.fetchone()
                    if not file_record:
                        logger.error(f"Cannot save data: file record with task_id={current_task_id} does not exist")
                        return None
                    
                    if not selected_categories:
                        logger.warning("Saving data with empty selected_categories - this may be an update operation")
                    if not table_data:
                        logger.warning("Saving data with empty table_data - this may be an update operation")
                    
                    # Upsert data record (allow empty data for update operations)
                    upsert_sql = """
                    INSERT INTO data_extraction_data (task_id, selected_categories, table_data, result_json)
                    VALUES (%s, %s::jsonb, %s::jsonb, %s)
                    ON CONFLICT (task_id) 
                    DO UPDATE SET
                        selected_categories = EXCLUDED.selected_categories,
                        table_data = EXCLUDED.table_data,
                        result_json = EXCLUDED.result_json,
                        updated_at = NOW()
                    RETURNING task_id
                    """
                    cursor.execute(
                        upsert_sql,
                        (
                            current_task_id,
                            json.dumps(selected_categories) if selected_categories else json.dumps({}),
                            json.dumps(table_data) if table_data else json.dumps([]),
                            result_json,
                        ),
                    )
                    result = cursor.fetchone()
                    self.postgres_conn.commit()
                    task_id_str = str(result["task_id"]) if result else None
                    
                    # Log selected categories and table data details
                    selected_cats_info = ""
                    if selected_categories:
                        selected_cats_info = (
                            f"selected_categories: materials={len(selected_categories.get('materials', []))} "
                            f"({selected_categories.get('materials', [])[:3]}), "
                            f"processes={len(selected_categories.get('processes', []))} "
                            f"({selected_categories.get('processes', [])[:3]}), "
                            f"properties={len(selected_categories.get('properties', []))} "
                            f"({selected_categories.get('properties', [])[:3]})"
                        )
                    else:
                        selected_cats_info = "selected_categories: empty"
                    
                    table_data_info = ""
                    if table_data and isinstance(table_data, list):
                        table_data_info = f"table_data: {len(table_data)} rows"
                        if len(table_data) > 0:
                            # Log first 3 rows as sample
                            sample_rows = []
                            for i, row in enumerate(table_data[:3]):
                                if isinstance(row, dict):
                                    sample_rows.append({
                                        "material": row.get("material", "")[:30] if row.get("material") else "",
                                        "process": row.get("process", "")[:30] if row.get("process") else "",
                                        "property": (row.get("property", "")[:50] + "...") if row.get("property") and len(row.get("property", "")) > 50 else (row.get("property", "") or ""),
                                    })
                            table_data_info += f", sample: {sample_rows}"
                    else:
                        table_data_info = "table_data: empty"
                    
                    logger.info(
                        f"[Step 3] Saved data record - task_id={task_id_str}, "
                        f"{selected_cats_info}, {table_data_info}"
                    )
                    
                    return task_id_str
                
                else:
                    logger.error(f"Invalid extraction_step: {extraction_step}")
                    return None
                
        except Exception as e:
            logger.error(f"Failed to save to PostgreSQL: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return None

    def _save_to_mongodb(
        self,
        task_name: Optional[str] = None,
        extraction_type: str = "material_extraction",
        extraction_step: int = 1,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_base64: Optional[str] = None,
        pdf_url: Optional[str] = None,
        model_name: Optional[str] = None,
        categories: Optional[Dict] = None,
        selected_categories: Optional[Dict] = None,
        table_data: Optional[List] = None,
        result_json: Optional[str] = None,
        metadata: Optional[Dict] = None,
        record_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[str]:
        """Save record to MongoDB based on extraction step."""
        try:
            # Determine task_id
            current_task_id: Optional[str] = None
            if task_id:
                current_task_id = task_id
            elif record_id:
                # Legacy support: try to get task_id from files collection
                files_collection = self.mongo_db.data_extraction_files
                file_record = files_collection.find_one({"_id": record_id})
                if file_record:
                    current_task_id = file_record.get("task_id")
            
            # Step 1: Save to files collection
            if extraction_step == 1:
                files_collection = self.mongo_db.data_extraction_files
                if current_task_id:
                    # Update existing file record
                    files_collection.update_one(
                        {"task_id": current_task_id},
                        {
                            "$set": {
                                "task_name": task_name,
                                "extraction_type": extraction_type,
                                "file_name": file_name,
                                "file_size": file_size,
                                "file_base64": file_base64,
                                "pdf_url": pdf_url,
                                "model_name": model_name,
                                "metadata": metadata,
                                "updated_at": datetime.utcnow(),
                            }
                        },
                        upsert=True,
                    )
                else:
                    # Insert new file record
                    current_task_id = str(uuid4())
                    record = {
                        "task_id": current_task_id,
                        "task_name": task_name,
                        "extraction_type": extraction_type,
                        "file_name": file_name,
                        "file_size": file_size,
                        "file_base64": file_base64,
                        "pdf_url": pdf_url,
                        "model_name": model_name,
                        "metadata": metadata,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                    files_collection.insert_one(record)
                logger.info(f"Saved extraction file record (step 1) to MongoDB: task_id={current_task_id}")
                return current_task_id
            
            # Step 2: Save to categories collection
            elif extraction_step == 2:
                if not current_task_id:
                    logger.error("Cannot save categories: task_id is required for step 2")
                    return None
                
                if not categories:
                    logger.error("Cannot save categories: categories data is required for step 2")
                    return None
                
                categories_collection = self.mongo_db.data_extraction_categories
                categories_collection.update_one(
                    {"task_id": current_task_id},
                    {
                        "$set": {
                            "task_id": current_task_id,
                            "categories": categories,
                            "result_json": result_json,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                    upsert=True,
                )
                logger.info(f"Saved extraction categories record (step 2) to MongoDB: task_id={current_task_id}")
                return current_task_id
            
            # Step 3: Save to data collection
            elif extraction_step == 3:
                if not current_task_id:
                    logger.error("Cannot save data: task_id is required for step 3")
                    return None
                
                if not selected_categories or not table_data:
                    logger.error("Cannot save data: selected_categories and table_data are required for step 3")
                    return None
                
                data_collection = self.mongo_db.data_extraction_data
                data_collection.update_one(
                    {"task_id": current_task_id},
                    {
                        "$set": {
                            "task_id": current_task_id,
                            "selected_categories": selected_categories,
                            "table_data": table_data,
                            "result_json": result_json,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                    upsert=True,
                )
                logger.info(f"Saved extraction data record (step 3) to MongoDB: task_id={current_task_id}")
                return current_task_id
            
            else:
                logger.error(f"Invalid extraction_step: {extraction_step}")
                return None
        except Exception as e:
            logger.error(f"Failed to save to MongoDB: {e}", exc_info=True)
            return None

    def get_extraction_records(
        self, limit: int = 50, offset: int = 0, extraction_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get list of extraction records.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            extraction_type: Filter by extraction type (optional)

        Returns:
            List of record dictionaries
        """
        try:
            if self.postgres_conn:
                return self._get_from_postgresql(limit, offset, extraction_type)
            elif self.mongo_db:
                return self._get_from_mongodb(limit, offset, extraction_type)
            else:
                logger.error("No database connection available")
                return []
        except Exception as e:
            logger.error(f"Failed to get extraction records: {e}", exc_info=True)
            return []

    def _get_from_postgresql(
        self, limit: int = 50, offset: int = 0, extraction_type: Optional[str] = None
    ) -> List[Dict]:
        """Get records from PostgreSQL, joining all three tables."""
        try:
            with self.postgres_conn.cursor() as cursor:
                if extraction_type:
                    sql = """
                    SELECT 
                        f.id,
                        f.task_id,
                        f.task_name,
                        f.extraction_type,
                        f.file_name,
                        f.file_size,
                        f.pdf_url,
                        f.model_name,
                        f.created_at,
                        f.updated_at,
                        c.categories,
                        c.result_json as categories_result_json,
                        d.selected_categories,
                        d.table_data,
                        d.result_json as data_result_json,
                        CASE 
                            WHEN d.task_id IS NOT NULL THEN 3
                            WHEN c.task_id IS NOT NULL THEN 2
                            ELSE 1
                        END as extraction_step
                    FROM data_extraction_files f
                    LEFT JOIN data_extraction_categories c ON f.task_id = c.task_id
                    LEFT JOIN data_extraction_data d ON f.task_id = d.task_id
                    WHERE f.extraction_type = %s
                    ORDER BY f.created_at DESC
                    LIMIT %s OFFSET %s
                    """
                    cursor.execute(sql, (extraction_type, limit, offset))
                else:
                    sql = """
                    SELECT 
                        f.id,
                        f.task_id,
                        f.task_name,
                        f.extraction_type,
                        f.file_name,
                        f.file_size,
                        f.pdf_url,
                        f.model_name,
                        f.created_at,
                        f.updated_at,
                        c.categories,
                        c.result_json as categories_result_json,
                        d.selected_categories,
                        d.table_data,
                        d.result_json as data_result_json,
                        CASE 
                            WHEN d.task_id IS NOT NULL THEN 3
                            WHEN c.task_id IS NOT NULL THEN 2
                            ELSE 1
                        END as extraction_step
                    FROM data_extraction_files f
                    LEFT JOIN data_extraction_categories c ON f.task_id = c.task_id
                    LEFT JOIN data_extraction_data d ON f.task_id = d.task_id
                    ORDER BY f.created_at DESC
                    LIMIT %s OFFSET %s
                    """
                    cursor.execute(sql, (limit, offset))

                records = cursor.fetchall()
                # Convert UUID to string and datetime to ISO format
                result = []
                for record in records:
                    rec_dict = dict(record)
                    rec_dict["id"] = str(rec_dict["id"])
                    rec_dict["task_id"] = str(rec_dict["task_id"])
                    if rec_dict.get("created_at"):
                        rec_dict["created_at"] = rec_dict["created_at"].isoformat()
                    if rec_dict.get("updated_at"):
                        rec_dict["updated_at"] = rec_dict["updated_at"].isoformat()
                    # Merge result_json from categories and data
                    result_json = rec_dict.get("data_result_json") or rec_dict.get("categories_result_json")
                    if result_json:
                        rec_dict["result_json"] = result_json
                    result.append(rec_dict)
                return result
        except Exception as e:
            logger.error(f"Failed to get from PostgreSQL: {e}", exc_info=True)
            return []

    def _get_from_mongodb(
        self, limit: int = 50, offset: int = 0, extraction_type: Optional[str] = None
    ) -> List[Dict]:
        """Get records from MongoDB, joining all three collections."""
        try:
            files_collection = self.mongo_db.data_extraction_files
            query = {}
            if extraction_type:
                query["extraction_type"] = extraction_type

            file_records = list(
                files_collection.find(query, {"file_base64": 0})  # Exclude large file content
                .sort("created_at", -1)
                .limit(limit)
                .skip(offset)
            )

            # Get task_ids
            task_ids = [record["task_id"] for record in file_records]
            
            # Get categories records
            categories_collection = self.mongo_db.data_extraction_categories
            categories_records = {
                rec["task_id"]: rec 
                for rec in categories_collection.find({"task_id": {"$in": task_ids}})
            }
            
            # Get data records
            data_collection = self.mongo_db.data_extraction_data
            data_records = {
                rec["task_id"]: rec 
                for rec in data_collection.find({"task_id": {"$in": task_ids}})
            }

            # Merge records
            result = []
            for file_record in file_records:
                task_id = file_record["task_id"]
                categories_record = categories_records.get(task_id)
                data_record = data_records.get(task_id)
                
                rec_dict = {
                    "id": str(file_record.get("_id", "")),
                    "task_id": task_id,
                    "task_name": file_record.get("task_name"),
                    "extraction_type": file_record.get("extraction_type"),
                    "file_name": file_record.get("file_name"),
                    "file_size": file_record.get("file_size"),
                    "pdf_url": file_record.get("pdf_url"),
                    "model_name": file_record.get("model_name"),
                    "categories": categories_record.get("categories") if categories_record else None,
                    "selected_categories": data_record.get("selected_categories") if data_record else None,
                    "table_data": data_record.get("table_data") if data_record else None,
                    "result_json": (data_record.get("result_json") if data_record 
                                   else categories_record.get("result_json") if categories_record else None),
                }
                
                # Determine extraction_step
                if data_record:
                    rec_dict["extraction_step"] = 3
                elif categories_record:
                    rec_dict["extraction_step"] = 2
                else:
                    rec_dict["extraction_step"] = 1
                
                # Convert datetime to ISO format
                if file_record.get("created_at"):
                    rec_dict["created_at"] = file_record["created_at"].isoformat()
                if file_record.get("updated_at"):
                    rec_dict["updated_at"] = file_record["updated_at"].isoformat()
                
                result.append(rec_dict)
            return result
        except Exception as e:
            logger.error(f"Failed to get from MongoDB: {e}", exc_info=True)
            return []

    def get_extraction_record_by_id(self, record_id: str, task_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get a single extraction record by ID or task_id.

        Args:
            record_id: Record ID (file table id) or task_id
            task_id: Task ID (if provided, used instead of record_id)

        Returns:
            Record dictionary or None if not found
        """
        try:
            if self.postgres_conn:
                return self._get_by_id_from_postgresql(record_id, task_id)
            elif self.mongo_db:
                return self._get_by_id_from_mongodb(record_id, task_id)
            else:
                logger.error("No database connection available")
                return None
        except Exception as e:
            logger.error(f"Failed to get extraction record by ID: {e}", exc_info=True)
            return None

    def _get_by_id_from_postgresql(self, record_id: str, task_id: Optional[str] = None) -> Optional[Dict]:
        """Get record by ID or task_id from PostgreSQL, joining all three tables."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # If task_id is provided, use it directly; otherwise try to get task_id from record_id
                current_task_id: Optional[UUID] = None
                if task_id:
                    current_task_id = UUID(task_id)
                else:
                    # Try to get task_id from files table using record_id
                    cursor.execute(
                        "SELECT task_id FROM data_extraction_files WHERE id = %s OR task_id = %s",
                        (UUID(record_id), UUID(record_id))
                    )
                    result = cursor.fetchone()
                    if result:
                        current_task_id = result["task_id"]
                    else:
                        # If not found, assume record_id is task_id
                        try:
                            current_task_id = UUID(record_id)
                        except ValueError:
                            return None
                
                # Query all three tables joined by task_id
                sql = """
                SELECT 
                    f.id,
                    f.task_id,
                    f.task_name,
                    f.extraction_type,
                    f.file_name,
                    f.file_size,
                    f.file_base64,
                    f.pdf_url,
                    f.model_name,
                    f.metadata,
                    f.created_at,
                    f.updated_at,
                    c.categories,
                    c.result_json as categories_result_json,
                    d.selected_categories,
                    d.table_data,
                    d.result_json as data_result_json,
                    CASE 
                        WHEN d.task_id IS NOT NULL THEN 3
                        WHEN c.task_id IS NOT NULL THEN 2
                        ELSE 1
                    END as extraction_step
                FROM data_extraction_files f
                LEFT JOIN data_extraction_categories c ON f.task_id = c.task_id
                LEFT JOIN data_extraction_data d ON f.task_id = d.task_id
                WHERE f.task_id = %s
                """
                cursor.execute(sql, (current_task_id,))
                record = cursor.fetchone()
                if record:
                    rec_dict = dict(record)
                    rec_dict["id"] = str(rec_dict["id"])
                    rec_dict["task_id"] = str(rec_dict["task_id"])
                    if rec_dict.get("created_at"):
                        rec_dict["created_at"] = rec_dict["created_at"].isoformat()
                    if rec_dict.get("updated_at"):
                        rec_dict["updated_at"] = rec_dict["updated_at"].isoformat()
                    # Merge result_json from categories and data
                    result_json = rec_dict.get("data_result_json") or rec_dict.get("categories_result_json")
                    if result_json:
                        rec_dict["result_json"] = result_json
                    return rec_dict
                return None
        except Exception as e:
            logger.error(f"Failed to get by ID from PostgreSQL: {e}", exc_info=True)
            return None

    def _get_by_id_from_mongodb(self, record_id: str, task_id: Optional[str] = None) -> Optional[Dict]:
        """Get record by ID or task_id from MongoDB, joining all three collections."""
        try:
            # Determine task_id
            current_task_id: Optional[str] = None
            if task_id:
                current_task_id = task_id
            else:
                # Try to get task_id from files collection
                files_collection = self.mongo_db.data_extraction_files
                file_record = files_collection.find_one(
                    {"$or": [{"_id": record_id}, {"task_id": record_id}]}
                )
                if file_record:
                    current_task_id = file_record.get("task_id")
                else:
                    # Assume record_id is task_id
                    current_task_id = record_id
            
            if not current_task_id:
                return None
            
            # Get file record
            files_collection = self.mongo_db.data_extraction_files
            file_record = files_collection.find_one({"task_id": current_task_id})
            if not file_record:
                return None
            
            # Get categories record
            categories_collection = self.mongo_db.data_extraction_categories
            categories_record = categories_collection.find_one({"task_id": current_task_id})
            
            # Get data record
            data_collection = self.mongo_db.data_extraction_data
            data_record = data_collection.find_one({"task_id": current_task_id})
            
            # Merge records
            result = {
                "id": str(file_record.get("_id", "")),
                "task_id": current_task_id,
                "task_name": file_record.get("task_name"),
                "extraction_type": file_record.get("extraction_type"),
                "file_name": file_record.get("file_name"),
                "file_size": file_record.get("file_size"),
                "file_base64": file_record.get("file_base64"),
                "pdf_url": file_record.get("pdf_url"),
                "model_name": file_record.get("model_name"),
                "metadata": file_record.get("metadata"),
                "categories": categories_record.get("categories") if categories_record else None,
                "selected_categories": data_record.get("selected_categories") if data_record else None,
                "table_data": data_record.get("table_data") if data_record else None,
                "result_json": (data_record.get("result_json") if data_record 
                               else categories_record.get("result_json") if categories_record else None),
            }
            
            # Determine extraction_step
            if data_record:
                result["extraction_step"] = 3
            elif categories_record:
                result["extraction_step"] = 2
            else:
                result["extraction_step"] = 1
            
            # Convert datetime to ISO format
            if file_record.get("created_at"):
                result["created_at"] = file_record["created_at"].isoformat()
            if file_record.get("updated_at"):
                result["updated_at"] = file_record["updated_at"].isoformat()
            
            return result
        except Exception as e:
            logger.error(f"Failed to get by ID from MongoDB: {e}", exc_info=True)
            return None

    def delete_extraction_record(self, record_id: str, task_id: Optional[str] = None) -> bool:
        """
        Delete an extraction record by task_id (deletes from all three tables).

        Args:
            record_id: Record ID (file table id) or task_id
            task_id: Task ID (if provided, used instead of record_id)

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            if self.postgres_conn:
                return self._delete_from_postgresql(record_id, task_id)
            elif self.mongo_db:
                return self._delete_from_mongodb(record_id, task_id)
            else:
                logger.error("No database connection available")
                return False
        except Exception as e:
            logger.error(f"Failed to delete extraction record: {e}", exc_info=True)
            return False

    def _delete_from_postgresql(self, record_id: str, task_id: Optional[str] = None) -> bool:
        """Delete record from PostgreSQL by task_id (CASCADE will delete related records)."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Determine task_id
                current_task_id: Optional[UUID] = None
                if task_id:
                    current_task_id = UUID(task_id)
                else:
                    # Try to get task_id from files table using record_id
                    cursor.execute(
                        "SELECT task_id FROM data_extraction_files WHERE id = %s OR task_id = %s",
                        (UUID(record_id), UUID(record_id))
                    )
                    result = cursor.fetchone()
                    if result:
                        current_task_id = result["task_id"]
                    else:
                        # If not found, assume record_id is task_id
                        try:
                            current_task_id = UUID(record_id)
                        except ValueError:
                            return False
                
                if not current_task_id:
                    return False
                
                # Delete from files table (CASCADE will delete related records)
                sql = "DELETE FROM data_extraction_files WHERE task_id = %s"
                cursor.execute(sql, (current_task_id,))
                self.postgres_conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted extraction record (all tables): task_id={current_task_id}")
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete from PostgreSQL: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False

    def _delete_from_mongodb(self, record_id: str, task_id: Optional[str] = None) -> bool:
        """Delete record from MongoDB by task_id (deletes from all three collections)."""
        try:
            # Determine task_id
            current_task_id: Optional[str] = None
            if task_id:
                current_task_id = task_id
            else:
                # Try to get task_id from files collection
                files_collection = self.mongo_db.data_extraction_files
                file_record = files_collection.find_one(
                    {"$or": [{"_id": record_id}, {"task_id": record_id}]}
                )
                if file_record:
                    current_task_id = file_record.get("task_id")
                else:
                    # Assume record_id is task_id
                    current_task_id = record_id
            
            if not current_task_id:
                return False
            
            # Delete from all three collections
            files_collection = self.mongo_db.data_extraction_files
            categories_collection = self.mongo_db.data_extraction_categories
            data_collection = self.mongo_db.data_extraction_data
            
            files_result = files_collection.delete_one({"task_id": current_task_id})
            categories_result = categories_collection.delete_one({"task_id": current_task_id})
            data_result = data_collection.delete_one({"task_id": current_task_id})
            
            deleted = files_result.deleted_count > 0
            if deleted:
                logger.info(f"Deleted extraction record (all collections) from MongoDB: task_id={current_task_id}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete from MongoDB: {e}", exc_info=True)
            return False


# Global instance
_record_manager: Optional[DataExtractionRecordManager] = None


def get_record_manager() -> DataExtractionRecordManager:
    """Get or create the global record manager instance."""
    global _record_manager
    if _record_manager is None:
        _record_manager = DataExtractionRecordManager()
    return _record_manager

