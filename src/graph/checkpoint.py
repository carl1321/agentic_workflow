# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

import psycopg
from langgraph.store.memory import InMemoryStore
from psycopg.rows import dict_row
from pymongo import MongoClient

from src.config.loader import get_bool_env, get_str_env

# Disable pymongo debug logs to avoid connection errors when using PostgreSQL
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("pymongo.topology").setLevel(logging.WARNING)
logging.getLogger("pymongo.serverSelection").setLevel(logging.WARNING)
logging.getLogger("pymongo.connection").setLevel(logging.WARNING)


class ChatStreamManager:
    """
    Manages chat stream messages with persistent storage and in-memory caching.

    This class handles the storage and retrieval of chat messages using both
    an in-memory store for temporary data and MongoDB or PostgreSQL for persistent storage.
    It tracks message chunks and consolidates them when a conversation finishes.

    Attributes:
        store (InMemoryStore): In-memory storage for temporary message chunks
        mongo_client (MongoClient): MongoDB client connection
        mongo_db (Database): MongoDB database instance
        postgres_conn (psycopg.Connection): PostgreSQL connection
        logger (logging.Logger): Logger instance for this class
    """

    def __init__(
        self, checkpoint_saver: bool = False, db_uri: Optional[str] = None
    ) -> None:
        """
        Initialize the ChatStreamManager with database connections.

        Args:
            db_uri: Database connection URI. Supports MongoDB (mongodb://) and PostgreSQL (postgresql://)
                   If None, uses LANGGRAPH_CHECKPOINT_DB_URL env var or defaults to localhost
        """
        self.logger = logging.getLogger(__name__)
        self.store = InMemoryStore()
        self.checkpoint_saver = checkpoint_saver
        # Use provided URI or fall back to environment variable or default
        self.db_uri = db_uri or get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")

        # Initialize database connections
        self.mongo_client = None
        self.mongo_db = None
        self.postgres_conn = None

        if self.checkpoint_saver:
            if self.db_uri.startswith("mongodb://"):
                self._init_mongodb()
            elif self.db_uri.startswith("postgresql://") or self.db_uri.startswith(
                "postgres://"
            ):
                self._init_postgresql()
            else:
                self.logger.warning(
                    f"Unsupported database URI scheme: {self.db_uri}. "
                    "Supported schemes: mongodb://, postgresql://, postgres://"
                )
        else:
            self.logger.warning("Checkpoint saver is disabled")

    def _init_mongodb(self) -> None:
        """Initialize MongoDB connection."""

        try:
            self.mongo_client = MongoClient(self.db_uri)
            self.mongo_db = self.mongo_client.checkpointing_db
            # Test connection
            self.mongo_client.admin.command("ping")
            self.logger.info("Successfully connected to MongoDB")
        except Exception as e:
            self.logger.error(f"Failed to connect to MongoDB: {e}")

    def _init_postgresql(self) -> None:
        """Initialize PostgreSQL connection and create table if needed."""

        try:
            self.postgres_conn = psycopg.connect(self.db_uri, row_factory=dict_row)
            self.logger.info("Successfully connected to PostgreSQL")
            self._create_chat_streams_table()
        except Exception as e:
            self.logger.error(f"Failed to connect to PostgreSQL: {e}")

    def _create_chat_streams_table(self) -> None:
        """Create the chat_streams table if it doesn't exist with extended schema."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Create table with extended schema
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS chat_streams (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    thread_id VARCHAR(255) NOT NULL UNIQUE,
                    title VARCHAR(255) NOT NULL DEFAULT '新对话',
                    messages JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_chat_streams_thread_id ON chat_streams(thread_id);
                CREATE INDEX IF NOT EXISTS idx_chat_streams_created_at ON chat_streams(created_at);
                CREATE INDEX IF NOT EXISTS idx_chat_streams_updated_at ON chat_streams(updated_at);
                """
                cursor.execute(create_table_sql)
                
                # Add new columns if table already exists (migration)
                alter_table_sql = """
                DO $$ 
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                    WHERE table_name='chat_streams' AND column_name='title') THEN
                        ALTER TABLE chat_streams ADD COLUMN title VARCHAR(255) NOT NULL DEFAULT '新对话';
                    END IF;
                    
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                    WHERE table_name='chat_streams' AND column_name='created_at') THEN
                        ALTER TABLE chat_streams 
                        ADD COLUMN created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW();
                    END IF;
                    
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                    WHERE table_name='chat_streams' AND column_name='updated_at') THEN
                        ALTER TABLE chat_streams 
                        ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW();
                    END IF;
                    
                    -- Migrate old ts column to updated_at if exists
                    IF EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='chat_streams' AND column_name='ts') THEN
                        UPDATE chat_streams 
                        SET updated_at = ts, created_at = COALESCE(created_at, ts)
                        WHERE updated_at IS NULL OR created_at IS NULL;
                    END IF;
                    
                    -- Add user_id column if it doesn't exist
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                    WHERE table_name='chat_streams' AND column_name='user_id') THEN
                        ALTER TABLE chat_streams ADD COLUMN user_id VARCHAR(255);
                        CREATE INDEX IF NOT EXISTS idx_chat_streams_user_id ON chat_streams(user_id);
                    END IF;
                END $$;
                """
                cursor.execute(alter_table_sql)
                
                self.postgres_conn.commit()
                self.logger.info("Chat streams table created/verified successfully")
        except Exception as e:
            self.logger.error(f"Failed to create/update chat_streams table: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()

    def process_stream_message(
        self, thread_id: str, message: str, finish_reason: str, title: Optional[str] = None
    ) -> bool:
        """
        Process and store a chat stream message chunk.

        This method handles individual message chunks during streaming and consolidates
        them into a complete message when the stream finishes. Messages are stored
        temporarily in memory and permanently in MongoDB when complete.

        Args:
            thread_id: Unique identifier for the conversation thread
            message: The message content or chunk to store
            finish_reason: Reason for message completion ("stop", "interrupt", or partial)

        Returns:
            bool: True if message was processed successfully, False otherwise
        """
        if not thread_id or not isinstance(thread_id, str):
            self.logger.warning("Invalid thread_id provided")
            return False

        if not message:
            self.logger.warning("Empty message provided")
            return False

        try:
            # Create namespace for this thread's messages
            store_namespace: Tuple[str, str] = ("messages", thread_id)

            # Get or initialize message cursor for tracking chunks
            cursor = self.store.get(store_namespace, "cursor")
            current_index = 0

            if cursor is None:
                # Initialize cursor for new conversation
                self.store.put(store_namespace, "cursor", {"index": 0})
                # Store title for new conversation
                if title:
                    self.store.put(store_namespace, "title", title)
            else:
                # Increment index for next chunk
                current_index = int(cursor.value.get("index", 0)) + 1
                self.store.put(store_namespace, "cursor", {"index": current_index})

            # Store the current message chunk
            self.store.put(store_namespace, f"chunk_{current_index}", message)

            # Check if conversation is complete and should be persisted
            if finish_reason in ("stop", "interrupt"):
                # Retrieve stored title if available
                stored_title = self.store.get(store_namespace, "title")
                conversation_title = title or (
                    stored_title.value if stored_title else None
                )
                return self._persist_complete_conversation(
                    thread_id, store_namespace, current_index, conversation_title
                )

            return True

        except Exception as e:
            self.logger.error(
                f"Error processing stream message for thread {thread_id}: {e}"
            )
            return False

    def _persist_complete_conversation(
        self, 
        thread_id: str, 
        store_namespace: Tuple[str, str], 
        final_index: int,
        title: Optional[str] = None
    ) -> bool:
        """
        Persist completed conversation to database (MongoDB or PostgreSQL).

        Retrieves all message chunks from memory store and saves the complete
        conversation to the configured database for permanent storage.

        Args:
            thread_id: Unique identifier for the conversation thread
            store_namespace: Namespace tuple for accessing stored messages
            final_index: The final chunk index for this conversation

        Returns:
            bool: True if persistence was successful, False otherwise
        """
        try:
            # Retrieve all message chunks from memory store
            # Get all messages up to the final index including cursor metadata
            memories = self.store.search(store_namespace, limit=final_index + 2)

            # Extract message content, filtering out cursor metadata
            # Strategy: prefer any JSON array present among memories; otherwise collect plain strings (excluding title/cursor)
            messages: List = []
            array_candidate: Optional[List] = None
            plain_chunks: List[str] = []
            stored_title_val = None
            try:
                stored_title = self.store.get(store_namespace, "title")
                stored_title_val = stored_title.value if stored_title else None
            except Exception:
                stored_title_val = None

            for item in memories:
                data = item.dict()
                value = data.get("value", "")
                if not value or isinstance(value, dict):
                    continue
                text = str(value)
                stripped = text.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    try:
                        arr = json.loads(text)
                        if isinstance(arr, list):
                            array_candidate = arr
                    except Exception:
                        # ignore parse error and fallback to plain accumulation
                        pass
                    continue
                # Exclude title value and cursor markers from plain accumulation
                if stored_title_val is not None and text == stored_title_val:
                    continue
                if text.startswith("{\"index\"") or text == "cursor":
                    continue
                plain_chunks.append(text)

            if array_candidate is not None:
                messages = array_candidate
            else:
                messages = plain_chunks

            if not messages:
                self.logger.warning(f"No messages found for thread {thread_id}")
                return False

            if not self.checkpoint_saver:
                self.logger.warning("Checkpoint saver is disabled")
                return False

            # Extract title from stored metadata if not provided
            if not title:
                stored_title = self.store.get(store_namespace, "title")
                title = stored_title.value if stored_title else "新对话"

            # Choose persistence method based on available connection
            if self.mongo_db is not None:
                return self._persist_to_mongodb(thread_id, messages, title)
            elif self.postgres_conn is not None:
                return self._persist_to_postgresql(thread_id, messages, title)
            else:
                self.logger.warning("No database connection available")
                return False

        except Exception as e:
            self.logger.error(
                f"Error persisting conversation for thread {thread_id}: {e}"
            )
            return False

    def _persist_to_mongodb(self, thread_id: str, messages: List[str], title: Optional[str] = None) -> bool:
        """Persist conversation to MongoDB."""
        try:
            # Get MongoDB collection for chat streams
            collection = self.mongo_db.chat_streams

            # Check if conversation already exists in database
            existing_document = collection.find_one({"thread_id": thread_id})

            current_timestamp = datetime.now()

            if existing_document:
                # Update existing conversation with new messages
                update_result = collection.update_one(
                    {"thread_id": thread_id},
                    {
                        "$set": {
                            "messages": messages,
                            "updated_at": current_timestamp,
                            "title": title or existing_document.get("title", "新对话"),
                        }
                    },
                )
                self.logger.info(
                    f"Updated conversation for thread {thread_id}: "
                    f"{update_result.modified_count} documents modified"
                )
                return update_result.modified_count > 0
            else:
                # Create new conversation document
                new_document = {
                    "thread_id": thread_id,
                    "title": title or "新对话",
                    "messages": messages,
                    "created_at": current_timestamp,
                    "updated_at": current_timestamp,
                    "id": uuid.uuid4().hex,
                }
                insert_result = collection.insert_one(new_document)
                self.logger.info(
                    f"Created new conversation: {insert_result.inserted_id}"
                )
                return insert_result.inserted_id is not None

        except Exception as e:
            self.logger.error(f"Error persisting to MongoDB: {e}")
            return False

    def _persist_to_postgresql(
        self, thread_id: str, messages: List[str], title: Optional[str] = None
    ) -> bool:
        """Persist conversation to PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Check if conversation already exists
                cursor.execute(
                    "SELECT id, title FROM chat_streams WHERE thread_id = %s", (thread_id,)
                )
                existing_record = cursor.fetchone()

                current_timestamp = datetime.now()
                messages_json = json.dumps(messages, ensure_ascii=False)
                conversation_title = title or "新对话"

                if existing_record:
                    # Update existing conversation with new messages
                    # Keep existing title unless a new one is provided
                    update_title = title or existing_record.get("title", "新对话")
                    cursor.execute(
                        """
                        UPDATE chat_streams 
                        SET messages = %s, updated_at = %s, title = %s
                        WHERE thread_id = %s
                        """,
                        (messages_json, current_timestamp, update_title, thread_id),
                    )
                    affected_rows = cursor.rowcount
                    self.postgres_conn.commit()

                    self.logger.info(
                        f"Updated conversation for thread {thread_id}: "
                        f"{affected_rows} rows modified"
                    )
                    return affected_rows > 0
                else:
                    # Create new conversation record
                    conversation_id = uuid.uuid4()
                    cursor.execute(
                        """
                        INSERT INTO chat_streams (id, thread_id, title, messages, created_at, updated_at) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            thread_id,
                            conversation_title,
                            messages_json,
                            current_timestamp,
                            current_timestamp,
                        ),
                    )
                    affected_rows = cursor.rowcount
                    self.postgres_conn.commit()

                    self.logger.info(
                        f"Created new conversation with ID: {conversation_id}, title: {conversation_title}"
                    )
                    return affected_rows > 0

        except Exception as e:
            self.logger.error(f"Error persisting to PostgreSQL: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False

    def close(self) -> None:
        """Close database connections."""
        try:
            if self.mongo_client is not None:
                self.mongo_client.close()
                self.logger.info("MongoDB connection closed")
        except Exception as e:
            self.logger.error(f"Error closing MongoDB connection: {e}")

        try:
            if self.postgres_conn is not None:
                self.postgres_conn.close()
                self.logger.info("PostgreSQL connection closed")
        except Exception as e:
            self.logger.error(f"Error closing PostgreSQL connection: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connections."""
        self.close()

    def get_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
        can_read_all: bool = False,
    ) -> List[dict]:
        """
        Get list of conversations ordered by updated_at descending.

        Args:
            limit: Maximum number of conversations to return
            offset: Number of conversations to skip

        Returns:
            List of conversation dictionaries with id, thread_id, title, created_at, updated_at
        """
        if not self.checkpoint_saver:
            self.logger.warning("Checkpoint saver is disabled")
            return []

        try:
            if self.postgres_conn is not None:
                return self._get_conversations_from_postgresql(
                    limit, offset, user_id=user_id, can_read_all=can_read_all
                )
            elif self.mongo_db is not None:
                return self._get_conversations_from_mongodb(limit, offset)
            else:
                self.logger.warning("No database connection available")
                return []
        except Exception as e:
            self.logger.error(f"Error getting conversations: {e}")
            return []

    def _get_conversations_from_postgresql(
        self,
        limit: int,
        offset: int,
        user_id: Optional[str] = None,
        can_read_all: bool = False,
    ) -> List[dict]:
        """Get conversations from PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                base_sql = """
                    SELECT id, thread_id, title, created_at, updated_at
                    FROM chat_streams
                """
                conditions = []
                params: list = []

                # 非管理员：仅查看自己 user_id 绑定的会话；管理员或拥有特权时可看全部
                if user_id and not can_read_all:
                    conditions.append("user_id = %s")
                    params.append(user_id)

                order_limit = " ORDER BY updated_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                if conditions:
                    sql = base_sql + " WHERE " + " AND ".join(conditions) + order_limit
                else:
                    sql = base_sql + order_limit

                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
                return [
                    {
                        "id": str(row["id"]),
                        "thread_id": row["thread_id"],
                        "title": row["title"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                    }
                    for row in rows
                ]
        except Exception as e:
            self.logger.error(f"Error getting conversations from PostgreSQL: {e}")
            return []

    def _get_conversations_from_mongodb(
        self, limit: int, offset: int
    ) -> List[dict]:
        """Get conversations from MongoDB."""
        try:
            collection = self.mongo_db.chat_streams
            cursor = collection.find({}).sort("updated_at", -1).skip(offset).limit(limit)
            return [
                {
                    "id": doc.get("id", ""),
                    "thread_id": doc.get("thread_id", ""),
                    "title": doc.get("title", "新对话"),
                    "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                    "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
                }
                for doc in cursor
            ]
        except Exception as e:
            self.logger.error(f"Error getting conversations from MongoDB: {e}")
            return []

    def get_conversation_by_thread_id(self, thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> Optional[dict]:
        """
        Get a single conversation by thread_id.

        Args:
            thread_id: Unique identifier for the conversation thread
            user_id: Optional user ID to filter by (for non-admin users)
            can_read_all: If True, ignore user_id filter (for admins)

        Returns:
            Conversation dictionary with id, thread_id, title, messages, created_at, updated_at
            or None if not found
        """
        if not self.checkpoint_saver:
            self.logger.warning("Checkpoint saver is disabled")
            return None

        try:
            if self.postgres_conn is not None:
                return self._get_conversation_from_postgresql(thread_id, user_id, can_read_all)
            elif self.mongo_db is not None:
                return self._get_conversation_from_mongodb(thread_id, user_id, can_read_all)
            else:
                self.logger.warning("No database connection available")
                return None
        except Exception as e:
            self.logger.error(f"Error getting conversation {thread_id}: {e}")
            return None

    def _get_conversation_from_postgresql(self, thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> Optional[dict]:
        """Get conversation from PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Build query with user_id filter if needed
                if user_id and not can_read_all:
                    cursor.execute(
                        """
                        SELECT id, thread_id, title, messages, created_at, updated_at, user_id
                        FROM chat_streams
                        WHERE thread_id = %s AND user_id = %s
                        """,
                        (thread_id, user_id),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, thread_id, title, messages, created_at, updated_at, user_id
                    FROM chat_streams
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                # Parse messages JSONB
                messages = row["messages"]
                if isinstance(messages, str):
                    messages = json.loads(messages)

                # Validate and log message structure
                if messages and isinstance(messages, list):
                    for idx, msg in enumerate(messages):
                        if not isinstance(msg, dict):
                            self.logger.warning(f"Invalid message type at index {idx} for thread_id={thread_id}: {type(msg)}")
                            continue
                        # Log message structure for debugging
                        has_tool_calls = "tool_calls" in msg and msg.get("tool_calls")
                        has_tool_call_id = "tool_call_id" in msg and msg.get("tool_call_id")
                        has_reasoning = "reasoning_content" in msg and msg.get("reasoning_content")
                        if has_tool_calls or has_tool_call_id or has_reasoning:
                            self.logger.debug(
                                f"Loaded message {idx} for thread_id={thread_id}: id={msg.get('id')}, "
                                f"agent={msg.get('agent')}, tool_calls={has_tool_calls}, "
                                f"tool_call_id={has_tool_call_id}, reasoning_content={has_reasoning}"
                            )

                return {
                    "id": str(row["id"]),
                    "thread_id": row["thread_id"],
                    "title": row["title"],
                    "messages": messages,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
        except Exception as e:
            self.logger.error(f"Error getting conversation from PostgreSQL: {e}")
            return None

    def _get_conversation_from_mongodb(self, thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> Optional[dict]:
        """Get conversation from MongoDB."""
        try:
            collection = self.mongo_db.chat_streams
            # Build query with user_id filter if needed
            query = {"thread_id": thread_id}
            if user_id and not can_read_all:
                query["user_id"] = user_id
            
            doc = collection.find_one(query)
            if not doc:
                return None

            return {
                "id": doc.get("id", ""),
                "thread_id": doc.get("thread_id", ""),
                "title": doc.get("title", "新对话"),
                "messages": doc.get("messages", []),
                "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
            }
        except Exception as e:
            self.logger.error(f"Error getting conversation from MongoDB: {e}")
            return None

    def delete_conversation(self, thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> bool:
        """
        Delete a conversation by thread_id.

        Args:
            thread_id: Unique identifier for the conversation thread
            user_id: Optional user ID to verify ownership (for non-admin users)
            can_read_all: If True, ignore user_id filter (for admins)

        Returns:
            bool: True if conversation was deleted successfully, False otherwise
        """
        if not thread_id:
            self.logger.warning("Invalid thread_id provided for deletion")
            return False

        try:
            if self.mongo_db is not None:
                return self._delete_conversation_from_mongodb(thread_id, user_id, can_read_all)
            elif self.postgres_conn is not None:
                return self._delete_conversation_from_postgresql(thread_id, user_id, can_read_all)
            else:
                self.logger.warning("No database connection available for deletion")
                return False
        except Exception as e:
            self.logger.error(f"Error deleting conversation {thread_id}: {e}")
            return False

    def _delete_conversation_from_postgresql(self, thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> bool:
        """Delete conversation from PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Build query with user_id filter if needed
                if user_id and not can_read_all:
                    cursor.execute(
                        "DELETE FROM chat_streams WHERE thread_id = %s AND user_id = %s",
                        (thread_id, user_id),
                    )
                else:
                    cursor.execute(
                        "DELETE FROM chat_streams WHERE thread_id = %s",
                        (thread_id,),
                    )
                deleted_count = cursor.rowcount
                self.postgres_conn.commit()
                self.logger.info(f"Deleted {deleted_count} conversation(s) with thread_id={thread_id}, user_id={user_id or 'all'}")
                return deleted_count > 0
        except Exception as e:
            self.logger.error(f"Error deleting conversation from PostgreSQL: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False

    def _delete_conversation_from_mongodb(self, thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> bool:
        """Delete conversation from MongoDB."""
        try:
            collection = self.mongo_db.chat_streams
            # Build query with user_id filter if needed
            query = {"thread_id": thread_id}
            if user_id and not can_read_all:
                query["user_id"] = user_id
            
            result = collection.delete_one(query)
            deleted_count = result.deleted_count
            self.logger.info(f"Deleted {deleted_count} conversation(s) with thread_id={thread_id}, user_id={user_id or 'all'}")
            return deleted_count > 0
        except Exception as e:
            self.logger.error(f"Error deleting conversation from MongoDB: {e}")
            return False

    def create_conversation(
        self, thread_id: str, title: str, initial_messages: Optional[List] = None, user_id: Optional[str] = None
    ) -> bool:
        """
        Create a new conversation record in the database.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            title: Initial conversation title
            initial_messages: Optional initial messages to include (default: empty array)
            user_id: Optional user ID to associate with the conversation
            
        Returns:
            bool: True if conversation was created successfully, False otherwise
        """
        if not thread_id or not title:
            self.logger.warning("Invalid thread_id or title provided for conversation creation")
            return False

        if not self.checkpoint_saver:
            self.logger.warning("Checkpoint saver is disabled")
            return False

        messages = initial_messages if initial_messages is not None else []
        
        try:
            if self.mongo_db is not None:
                return self._create_conversation_in_mongodb(thread_id, title, messages, user_id)
            elif self.postgres_conn is not None:
                return self._create_conversation_in_postgresql(thread_id, title, messages, user_id)
            else:
                self.logger.warning("No database connection available for conversation creation")
                return False
        except Exception as e:
            self.logger.error(f"Error creating conversation {thread_id}: {e}")
            return False

    def _create_conversation_in_postgresql(
        self, thread_id: str, title: str, messages: List, user_id: Optional[str] = None
    ) -> bool:
        """Create conversation in PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Check if conversation already exists
                cursor.execute(
                    "SELECT id FROM chat_streams WHERE thread_id = %s", (thread_id,)
                )
                if cursor.fetchone():
                    self.logger.warning(f"Conversation {thread_id} already exists, skipping creation")
                    return False

                conversation_id = uuid.uuid4()
                current_timestamp = datetime.now()
                messages_json = json.dumps(messages, ensure_ascii=False)
                
                # Insert with user_id if provided
                if user_id:
                    cursor.execute(
                        """
                        INSERT INTO chat_streams (id, thread_id, title, messages, user_id, created_at, updated_at) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            thread_id,
                            title,
                            messages_json,
                            user_id,
                            current_timestamp,
                            current_timestamp,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO chat_streams (id, thread_id, title, messages, created_at, updated_at) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            thread_id,
                            title,
                            messages_json,
                            current_timestamp,
                            current_timestamp,
                        ),
                    )
                affected_rows = cursor.rowcount
                self.postgres_conn.commit()

                self.logger.info(
                    f"Created new conversation with ID: {conversation_id}, thread_id: {thread_id}, title: {title}, user_id: {user_id or 'None'}"
                )
                return affected_rows > 0
        except Exception as e:
            self.logger.error(f"Error creating conversation in PostgreSQL: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False

    def _create_conversation_in_mongodb(
        self, thread_id: str, title: str, messages: List, user_id: Optional[str] = None
    ) -> bool:
        """Create conversation in MongoDB."""
        try:
            collection = self.mongo_db.chat_streams
            
            # Check if conversation already exists
            if collection.find_one({"thread_id": thread_id}):
                self.logger.warning(f"Conversation {thread_id} already exists, skipping creation")
                return False

            current_timestamp = datetime.now()
            new_document = {
                "id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "title": title,
                "messages": messages,
                "created_at": current_timestamp,
                "updated_at": current_timestamp,
            }
            if user_id:
                new_document["user_id"] = user_id
            
            insert_result = collection.insert_one(new_document)
            self.logger.info(
                f"Created new conversation with ID: {insert_result.inserted_id}, thread_id: {thread_id}, title: {title}, user_id: {user_id or 'None'}"
            )
            return insert_result.inserted_id is not None
        except Exception as e:
            self.logger.error(f"Error creating conversation in MongoDB: {e}")
            return False

    def update_conversation(
        self,
        thread_id: str,
        title: Optional[str] = None,
        messages: Optional[List] = None,
        append: bool = False,
    ) -> bool:
        """
        Update an existing conversation record.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            title: Optional new title (only updates if provided)
            messages: Optional messages (only updates if provided)
            append: If True, append messages to existing ones; if False, replace them
            
        Returns:
            bool: True if conversation was updated successfully, False otherwise
        """
        if not thread_id:
            self.logger.warning("Invalid thread_id provided for conversation update")
            return False

        if not self.checkpoint_saver:
            self.logger.warning("Checkpoint saver is disabled")
            return False

        if title is None and messages is None:
            self.logger.warning("No update data provided (title or messages required)")
            return False

        try:
            if self.mongo_db is not None:
                return self._update_conversation_in_mongodb(thread_id, title, messages, append)
            elif self.postgres_conn is not None:
                return self._update_conversation_in_postgresql(thread_id, title, messages, append)
            else:
                self.logger.warning("No database connection available for conversation update")
                return False
        except Exception as e:
            self.logger.error(f"Error updating conversation {thread_id}: {e}")
            return False

    def _update_conversation_in_postgresql(
        self,
        thread_id: str,
        title: Optional[str],
        messages: Optional[List],
        append: bool,
    ) -> bool:
        """Update conversation in PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Get existing conversation
                cursor.execute(
                    "SELECT messages FROM chat_streams WHERE thread_id = %s", (thread_id,)
                )
                existing_record = cursor.fetchone()
                
                if not existing_record:
                    # If conversation doesn't exist, create it first
                    self.logger.info(f"Conversation {thread_id} not found for update, creating it first")
                    conversation_id = uuid.uuid4()
                    current_timestamp = datetime.now()
                    messages_json = json.dumps(messages if messages is not None else [], ensure_ascii=False)
                    conversation_title = title or "新对话"
                    
                    cursor.execute(
                        """
                        INSERT INTO chat_streams (id, thread_id, title, messages, created_at, updated_at) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            thread_id,
                            conversation_title,
                            messages_json,
                            current_timestamp,
                            current_timestamp,
                        ),
                    )
                    self.postgres_conn.commit()
                    self.logger.info(f"Created conversation {thread_id} via update: title={conversation_title}")
                    return True

                current_timestamp = datetime.now()
                update_fields = []
                update_values = []

                # Handle title update
                if title is not None:
                    update_fields.append("title = %s")
                    update_values.append(title)

                # Handle messages update
                if messages is not None:
                    if append:
                        # Append to existing messages, ensuring all existing messages are preserved
                        # NOTE: PostgreSQL with dict_row automatically converts JSONB to Python objects (list/dict)
                        # So we need to check the type before parsing
                        try:
                            raw_messages = existing_record["messages"]
                            
                            # Check if it's already a Python object (list/dict) - PostgreSQL dict_row behavior
                            if isinstance(raw_messages, (list, dict)):
                                existing_messages = raw_messages if isinstance(raw_messages, list) else []
                            elif isinstance(raw_messages, str):
                                # It's a JSON string, parse it
                                existing_messages = json.loads(raw_messages)
                            else:
                                # Unexpected type, log warning and try to use as-is
                                self.logger.warning(f"Unexpected messages type for thread_id={thread_id}: {type(raw_messages)}, attempting to use as-is")
                                existing_messages = raw_messages if isinstance(raw_messages, list) else []
                            
                            if isinstance(existing_messages, list):
                                # CRITICAL: All existing messages must be preserved
                                # Smart deduplication: check both ID and content
                                # If a message with same ID exists but content is different (e.g., merged vs chunk),
                                # we should update it rather than skip
                                original_count = len(existing_messages)  # Count before modifications
                                existing_by_id = {msg.get("id"): msg for msg in existing_messages if isinstance(msg, dict) and msg.get("id")}
                                new_messages = []
                                messages_to_update = []
                                
                                for msg in messages:
                                    if not isinstance(msg, dict):
                                        continue
                                    msg_id = msg.get("id")
                                    if not msg_id:
                                        # Message without ID, always append
                                        new_messages.append(msg)
                                    elif msg_id not in existing_by_id:
                                        # New message ID, append it
                                        new_messages.append(msg)
                                    else:
                                        # ID exists, check if content is different (merged message vs chunk)
                                        existing_msg = existing_by_id[msg_id]
                                        existing_content = existing_msg.get("content", "")
                                        new_content = msg.get("content", "")
                                        
                                        # If new content is longer or different, it's likely a merged version
                                        # Replace the existing chunk with the merged message
                                        if len(new_content) > len(existing_content) or new_content != existing_content:
                                            messages_to_update.append((msg_id, msg))
                                            # Remove old message from existing_messages
                                            existing_messages = [m for m in existing_messages if m.get("id") != msg_id]
                                        # If content is same or new is shorter, skip (keep existing)
                                
                                # Update existing messages with merged versions
                                for msg_id, updated_msg in messages_to_update:
                                    # Already removed from existing_messages above, now add updated version
                                    existing_messages.append(updated_msg)
                                
                                # Ensure existing messages are preserved first, then append new messages
                                # This guarantees: combined = all existing messages (updated) + new messages only
                                combined_messages = existing_messages + new_messages
                                
                                # Validation: ensure no messages were lost
                                final_count = len(combined_messages)
                                if final_count < original_count:
                                    self.logger.warning(
                                        f"Message count decreased when appending! "
                                        f"thread_id={thread_id}, original={original_count}, final={final_count}. "
                                        f"This should not happen - existing messages should be preserved."
                                    )
                                elif final_count == original_count and len(new_messages) > 0:
                                    self.logger.warning(
                                        f"New messages not appended! "
                                        f"thread_id={thread_id}, existing={original_count}, new={len(new_messages)}. "
                                        f"All new messages were filtered out - possible ID collision."
                                    )
                                else:
                                    update_info = f", updated={len(messages_to_update)}" if messages_to_update else ""
                                    self.logger.debug(
                                        f"Appended messages: thread_id={thread_id}, "
                                        f"existing={original_count}, new={len(new_messages)}{update_info}, final={final_count}"
                                    )
                            else:
                                # If existing_messages is not a list, log error but try to preserve existing data
                                self.logger.error(
                                    f"Existing messages is not a list for thread_id={thread_id}, type={type(existing_messages)}. "
                                    f"This should not happen. Attempting to preserve existing data."
                                )
                                # Try to preserve existing data by wrapping it
                                if isinstance(existing_messages, dict):
                                    combined_messages = [existing_messages] + messages
                                else:
                                    # Last resort: use new messages only but log critical error
                                    self.logger.error(f"CRITICAL: Cannot preserve existing messages for thread_id={thread_id}, using new messages only")
                                    combined_messages = messages
                        except (json.JSONDecodeError, TypeError, KeyError) as e:
                            # Error occurred, but try to use raw value if it's already a list
                            self.logger.warning(
                                f"Error parsing existing messages for thread_id={thread_id}: {e}. "
                                f"Attempting to use raw value."
                            )
                            raw_messages = existing_record.get("messages")
                            if isinstance(raw_messages, list):
                                # It's already a list, use it directly
                                self.logger.info(f"Using raw messages (already a list) for thread_id={thread_id}")
                                existing_ids = {msg.get("id") for msg in raw_messages if isinstance(msg, dict) and msg.get("id")}
                                new_messages = [msg for msg in messages if isinstance(msg, dict) and msg.get("id") not in existing_ids]
                                combined_messages = raw_messages + new_messages
                            else:
                                # Cannot recover, use new messages only (but log critical error)
                                self.logger.error(
                                    f"CRITICAL: Cannot recover existing messages for thread_id={thread_id}, "
                                    f"raw type={type(raw_messages)}. Using new messages only. This may cause data loss!"
                                )
                                combined_messages = messages
                    else:
                        # Replace messages
                        combined_messages = messages
                    
                    messages_json = json.dumps(combined_messages, ensure_ascii=False)
                    update_fields.append("messages = %s")
                    update_values.append(messages_json)

                if not update_fields:
                    self.logger.warning("No fields to update")
                    return False

                # Always update updated_at
                update_fields.append("updated_at = %s")
                update_values.append(current_timestamp)
                update_values.append(thread_id)

                cursor.execute(
                    f"""
                    UPDATE chat_streams 
                    SET {', '.join(update_fields)}
                    WHERE thread_id = %s
                    """,
                    update_values,
                )
                affected_rows = cursor.rowcount
                self.postgres_conn.commit()

                self.logger.info(
                    f"Updated conversation {thread_id}: {affected_rows} rows modified"
                )
                return affected_rows > 0
        except Exception as e:
            self.logger.error(f"Error updating conversation in PostgreSQL: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False

    def _update_conversation_in_mongodb(
        self,
        thread_id: str,
        title: Optional[str],
        messages: Optional[List],
        append: bool,
    ) -> bool:
        """Update conversation in MongoDB."""
        try:
            collection = self.mongo_db.chat_streams
            doc = collection.find_one({"thread_id": thread_id})
            
            if not doc:
                # If conversation doesn't exist, create it first
                self.logger.info(f"Conversation {thread_id} not found for update, creating it first")
                current_timestamp = datetime.now()
                new_document = {
                    "id": str(uuid.uuid4()),
                    "thread_id": thread_id,
                    "title": title or "新对话",
                    "messages": messages if messages is not None else [],
                    "created_at": current_timestamp,
                    "updated_at": current_timestamp,
                }
                insert_result = collection.insert_one(new_document)
                self.logger.info(f"Created conversation {thread_id} via update: title={new_document['title']}")
                return insert_result.inserted_id is not None

            update_fields = {}
            
            # Handle title update
            if title is not None:
                update_fields["title"] = title

            # Handle messages update
            if messages is not None:
                if append:
                    # Append to existing messages, ensuring all existing messages are preserved
                    existing_messages = doc.get("messages", [])
                    if isinstance(existing_messages, list):
                        # CRITICAL: All existing messages must be preserved
                        # Smart deduplication: check both ID and content
                        # If a message with same ID exists but content is different (e.g., merged vs chunk),
                        # we should update it rather than skip
                        original_count = len(existing_messages)  # Count before modifications
                        existing_by_id = {msg.get("id"): msg for msg in existing_messages if isinstance(msg, dict) and msg.get("id")}
                        new_messages = []
                        messages_to_update = []
                        
                        for msg in messages:
                            if not isinstance(msg, dict):
                                continue
                            msg_id = msg.get("id")
                            if not msg_id:
                                # Message without ID, always append
                                new_messages.append(msg)
                            elif msg_id not in existing_by_id:
                                # New message ID, append it
                                new_messages.append(msg)
                            else:
                                # ID exists, check if content is different (merged message vs chunk)
                                existing_msg = existing_by_id[msg_id]
                                existing_content = existing_msg.get("content", "")
                                new_content = msg.get("content", "")
                                
                                # If new content is longer or different, it's likely a merged version
                                # Replace the existing chunk with the merged message
                                if len(new_content) > len(existing_content) or new_content != existing_content:
                                    messages_to_update.append((msg_id, msg))
                                    # Remove old message from existing_messages
                                    existing_messages = [m for m in existing_messages if m.get("id") != msg_id]
                                # If content is same or new is shorter, skip (keep existing)
                        
                        # Update existing messages with merged versions
                        for msg_id, updated_msg in messages_to_update:
                            # Already removed from existing_messages above, now add updated version
                            existing_messages.append(updated_msg)
                        
                        # Ensure existing messages are preserved first, then append new messages
                        # This guarantees: combined = all existing messages (updated) + new messages only
                        update_fields["messages"] = existing_messages + new_messages
                        
                        # Validation: ensure no messages were lost
                        # original_count was already calculated before modifications
                        final_count = len(update_fields["messages"])
                        if final_count < original_count:
                            self.logger.warning(
                                f"Message count decreased when appending! "
                                f"thread_id={thread_id}, original={original_count}, final={final_count}. "
                                f"This should not happen - existing messages should be preserved."
                            )
                        elif final_count == original_count and len(new_messages) > 0:
                            self.logger.warning(
                                f"New messages not appended! "
                                f"thread_id={thread_id}, existing={original_count}, new={len(new_messages)}. "
                                f"All new messages were filtered out - possible ID collision."
                            )
                        else:
                            update_info = f", updated={len(messages_to_update)}" if messages_to_update else ""
                            self.logger.debug(
                                f"Appended messages: thread_id={thread_id}, "
                                f"existing={original_count}, new={len(new_messages)}{update_info}, final={final_count}"
                            )
                    else:
                        # If existing_messages is not a list, treat it as empty and use new messages
                        self.logger.warning(f"Existing messages is not a list for thread_id={thread_id}, using new messages only")
                        update_fields["messages"] = messages
                else:
                    # Replace messages
                    update_fields["messages"] = messages

            if not update_fields:
                self.logger.warning("No fields to update")
                return False

            # Always update updated_at
            update_fields["updated_at"] = datetime.now()

            result = collection.update_one(
                {"thread_id": thread_id},
                {"$set": update_fields},
            )
            
            self.logger.info(
                f"Updated conversation {thread_id}: {result.modified_count} documents modified"
            )
            return result.modified_count > 0
        except Exception as e:
            self.logger.error(f"Error updating conversation in MongoDB: {e}")
            return False


# Global instance for backward compatibility
# TODO: Consider using dependency injection instead of global instance
_default_manager = ChatStreamManager(
    checkpoint_saver=get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False),
    db_uri=get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow"),
)


def chat_stream_message(
    thread_id: str, 
    message: str, 
    finish_reason: str,
    title: Optional[str] = None
) -> bool:
    """
    Legacy function wrapper for backward compatibility.

        Args:
        thread_id: Unique identifier for the conversation thread
        message: The message content to store
        finish_reason: Reason for message completion
        title: Optional conversation title

        Returns:
        bool: True if message was processed successfully
    """
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    if checkpoint_saver:
        return _default_manager.process_stream_message(
            thread_id, message, finish_reason, title
        )
    else:
        return False


def get_conversations(
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    can_read_all: bool = False,
) -> List[dict]:
    """
    Get list of conversations.

    Args:
        limit: Maximum number of conversations to return
        offset: Number of conversations to skip

    Returns:
        List of conversation dictionaries
    """
    return _default_manager.get_conversations(
        limit=limit,
        offset=offset,
        user_id=user_id,
        can_read_all=can_read_all,
    )


def get_conversation_by_thread_id(thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> Optional[dict]:
    """
    Get a single conversation by thread_id.

    Args:
        thread_id: Unique identifier for the conversation thread
        user_id: Optional user ID to filter by (for non-admin users)
        can_read_all: If True, ignore user_id filter (for admins)

    Returns:
        Conversation dictionary or None if not found
    """
    return _default_manager.get_conversation_by_thread_id(thread_id, user_id, can_read_all)


def delete_conversation(thread_id: str, user_id: Optional[str] = None, can_read_all: bool = False) -> bool:
    """
    Delete a conversation by thread_id.

    Args:
        thread_id: Unique identifier for the conversation thread
        user_id: Optional user ID to verify ownership (for non-admin users)
        can_read_all: If True, ignore user_id filter (for admins)

    Returns:
        bool: True if conversation was deleted successfully, False otherwise
    """
    return _default_manager.delete_conversation(thread_id, user_id, can_read_all)


def create_conversation(thread_id: str, title: str, initial_messages: Optional[List] = None, user_id: Optional[str] = None) -> bool:
    """
    Create a new conversation record in the database.

    Args:
        thread_id: Unique identifier for the conversation thread
        title: Initial conversation title
        initial_messages: Optional initial messages to include (default: empty array)
        user_id: Optional user ID to associate with the conversation

    Returns:
        bool: True if conversation was created successfully, False otherwise
    """
    return _default_manager.create_conversation(thread_id, title, initial_messages, user_id)


def update_conversation(
    thread_id: str,
    title: Optional[str] = None,
    messages: Optional[List] = None,
    append: bool = False,
) -> bool:
    """
    Update an existing conversation record.

    Args:
        thread_id: Unique identifier for the conversation thread
        title: Optional new title (only updates if provided)
        messages: Optional messages (only updates if provided)
        append: If True, append messages to existing ones; if False, replace them

    Returns:
        bool: True if conversation was updated successfully, False otherwise
    """
    return _default_manager.update_conversation(thread_id, title, messages, append)
