# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import base64
import json
import logging
from datetime import datetime

# 设置日志级别为INFO，避免过多的DEBUG日志
logging.basicConfig(level=logging.INFO)
# Disable pymongo debug logs to avoid connection errors when using PostgreSQL
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("pymongo.topology").setLevel(logging.WARNING)
logging.getLogger("pymongo.serverSelection").setLevel(logging.WARNING)
logging.getLogger("pymongo.connection").setLevel(logging.WARNING)
# Disable langchain/openai request logs
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# Disable urllib3 debug logs
logging.getLogger("urllib3").setLevel(logging.WARNING)
import os
from pathlib import Path
from typing import Annotated, Any, List, Optional, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.wsgi import WSGIMiddleware
from pydantic import ValidationError
from langchain_core.messages import AIMessageChunk, BaseMessage, ToolMessage
from langgraph.checkpoint.mongodb import AsyncMongoDBSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool

from src.config.configuration import get_recursion_limit
from src.config.loader import get_bool_env, get_str_env, load_yaml_config
from src.config.report_style import ReportStyle
from src.config.tools import SELECTED_RAG_PROVIDER
from src.graph.builder import build_graph_with_memory
from src.graph.checkpoint import (
    chat_stream_message,
    get_conversations,
    get_conversation_by_thread_id,
    delete_conversation,
    create_conversation,
    update_conversation,
)
from src.llms.llm import get_configured_llm_models
from src.podcast.graph.builder import build_graph as build_podcast_graph
from src.ppt.graph.builder import build_graph as build_ppt_graph
from src.prompt_enhancer.graph.builder import build_graph as build_prompt_enhancer_graph
from src.prose.graph.builder import build_graph as build_prose_graph
from src.rag.builder import build_retriever
from src.rag.milvus import load_examples
from src.rag.retriever import Resource
from src.server.chat_request import (
    ChatRequest,
    EnhancePromptRequest,
    GeneratePodcastRequest,
    GeneratePPTRequest,
    GenerateProseRequest,
    TTSRequest,
)
from src.server.config_request import ConfigResponse
from src.server.mcp_request import MCPServerMetadataRequest, MCPServerMetadataResponse
from src.server.mcp_utils import load_mcp_tools
from src.server.rag_request import (
    RAGConfigResponse,
    RAGDocument,
    RAGDocumentsResponse,
    RAGResourceRequest,
    RAGResourcesResponse,
)
from src.server.tool_request import ToolExecuteRequest, ToolExecuteResponse
from src.server.auth.dependencies import CurrentUser, get_current_user, get_current_user_optional
from src.server.data_extraction_request import (
    DataExtractionRecordRequest,
    DataExtractionRecordResponse,
    DataExtractionRecordListResponse,
)
from src.server.data_extraction_records import get_record_manager
from src.server.workflow_request import (
    WorkflowConfigRequest,
    WorkflowConfigResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    NodeExecuteRequest,
    NodeExecuteResponse,
    WorkflowListResponse,
    ToolDefinition,
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    SaveDraftRequest,
    CreateReleaseRequest,
)
from src.server.workflow_storage import get_workflow_storage
from src.tools import (
    VolcengineTTS,
    crawl_tool,
    data_extraction_tool,
    generate_sam_molecules,
    molecular_analysis_tool,
    predict_molecular_properties,
    prompt_optimizer_tool,
    python_repl_tool,
    tts_tool,
    visualize_molecules,
    search_literature,
    fetch_pdf_text,
)
from src.utils.json_utils import sanitize_args

logger = logging.getLogger(__name__)

# Configure Windows event loop policy for PostgreSQL compatibility
# On Windows, psycopg requires a selector-based event loop, not the default ProactorEventLoop
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

INTERNAL_SERVER_ERROR_DETAIL = "Internal Server Error"

# Tool registry: map tool names to tool instances
# Note: Some tools have explicit names via @tool decorator, others use function name
# This registry supports both frontend toolName and actual tool.name for compatibility
TOOL_REGISTRY = {
    # Frontend toolName mappings
    "generate_sam_molecules": generate_sam_molecules,
    "property_predictor_tool": predict_molecular_properties,
    "visualize_molecules_tool": visualize_molecules,
    "literature_search_tool": search_literature,
    "pdf_crawler_tool": fetch_pdf_text,
    "python_repl_tool": python_repl_tool,
    "crawl_tool": crawl_tool,
    "prompt_optimizer_tool": prompt_optimizer_tool,
    "molecular_analysis_tool": molecular_analysis_tool,
    "tts_tool": tts_tool,
    "data_extraction_tool": data_extraction_tool,
    # Actual tool.name mappings (for compatibility)
    "predict_molecular_properties": predict_molecular_properties,
    "visualize_molecules": visualize_molecules,
    "search_literature": search_literature,
    "pdf_crawler": fetch_pdf_text,
    # Note: TTS can also be accessed via /api/tts endpoint for direct audio file download
}

# Parameter mapping: map frontend parameter names to backend tool parameter names
PARAMETER_MAPPING = {
    "visualize_molecules_tool": {
        "smiles": "smiles_text",
        # Remove width and height as they're not supported by the backend tool
    },
    "property_predictor_tool": {
        "smiles": "smiles_text",
        # Convert properties array to comma-separated string if needed
    },
    "literature_search_tool": {
        "limit": "top_k",  # Frontend uses "limit", backend uses "top_k"
    },
}

app = FastAPI(
    title="AgenticWorkflow API",
    description="API for AgenticWorkflow",
    version="0.1.0",
)

# Add CORS middleware
# It's recommended to load the allowed origins from an environment variable
# for better security and flexibility across different environments.
allowed_origins_str = get_str_env("ALLOWED_ORIGINS", "http://localhost:3002")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",")]

logger.info(f"Allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Restrict to specific origins
    allow_credentials=True,
    # 允许所有 HTTP 方法，确保 PUT/PATCH 等更新接口的跨域预检不会返回 400
    allow_methods=["*"],
    allow_headers=["*"],  # Now allow all headers, but can be restricted further
)

# Load examples into Milvus if configured
load_examples()

in_memory_store = InMemoryStore()
graph = build_graph_with_memory()

# Register authentication routes
try:
    from src.server.auth.routes import router as auth_router
    app.include_router(auth_router)
    logger.info("Authentication routes registered at /api/auth")
except Exception as e:
    logger.warning(f"Failed to register authentication routes: {e}. Authentication features may not be available.")

# Register admin routes
try:
    from src.server.auth.admin.user_routes import router as user_admin_router
    app.include_router(user_admin_router)
    logger.info("User management routes registered at /api/admin/users")
except Exception as e:
    logger.warning(f"Failed to register user management routes: {e}. User management features may not be available.")

try:
    from src.server.auth.admin.role_routes import router as role_admin_router
    app.include_router(role_admin_router)
    logger.info("Role management routes registered at /api/admin/roles")
except Exception as e:
    logger.warning(f"Failed to register role management routes: {e}. Role management features may not be available.")

try:
    from src.server.auth.admin.permission_routes import router as permission_admin_router
    app.include_router(permission_admin_router)
    logger.info("Permission management routes registered at /api/admin/permissions")
except Exception as e:
    logger.warning(f"Failed to register permission management routes: {e}. Permission management features may not be available.")

try:
    from src.server.auth.admin.menu_routes import router as menu_admin_router
    app.include_router(menu_admin_router)
    logger.info("Menu management routes registered at /api/admin/menus")
except Exception as e:
    logger.warning(f"Failed to register menu management routes: {e}. Menu management features may not be available.")

try:
    from src.server.auth.admin.organization_routes import router as org_admin_router
    app.include_router(org_admin_router)
    logger.info("Organization management routes registered at /api/admin/organizations")
except Exception as e:
    logger.warning(f"Failed to register organization management routes: {e}. Organization management features may not be available.")

try:
    from src.server.auth.admin.department_routes import router as dept_admin_router
    app.include_router(dept_admin_router)
    logger.info("Department management routes registered at /api/admin/departments")
except Exception as e:
    logger.warning(f"Failed to register department management routes: {e}. Department management features may not be available.")

# Mount workflow Flask application
# Dify workflow API已被移除，改用新的ReactFlow工作流系统
# try:
#     from src.server.workflow_app import get_workflow_app
#     workflow_flask_app = get_workflow_app()
#     app.mount("/workflow", WSGIMiddleware(workflow_flask_app))
#     logger.info("Workflow Flask application mounted at /workflow")
# except Exception as e:
#     logger.warning(f"Failed to mount workflow Flask application: {e}. Workflow features may not be available.")


@app.on_event("startup")
async def setup_checkpoint_tables():
    """Initialize checkpoint tables on application startup."""
    try:
        # Check if graph has PostgreSQL checkpointer
        if hasattr(graph, "checkpointer") and isinstance(graph.checkpointer, AsyncPostgresSaver):
            logger.info("Initializing PostgreSQL checkpoint tables...")
            await graph.checkpointer.setup()
            logger.info("PostgreSQL checkpoint tables initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to initialize checkpoint tables: {e}")
    
    # Start workflow worker
    try:
        from src.server.workflow.worker import get_workflow_worker
        from src.server.workflow.executor import get_workflow_executor
        worker = get_workflow_worker()
        executor = get_workflow_executor()
        worker.set_executor(executor)
        await worker.start()
        logger.info("Workflow worker started")
    except Exception as e:
        logger.warning(f"Failed to start workflow worker: {e}")


@app.on_event("shutdown")
async def shutdown_worker():
    """Stop workflow worker on application shutdown."""
    try:
        from src.server.workflow.worker import get_workflow_worker
        worker = get_workflow_worker()
        await worker.stop()
        logger.info("Workflow worker stopped")
    except Exception as e:
        logger.warning(f"Failed to stop workflow worker: {e}")


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    # Check if MCP server configuration is enabled
    mcp_enabled = get_bool_env("ENABLE_MCP_SERVER_CONFIGURATION", False)

    # Validate MCP settings if provided
    if request.mcp_settings and not mcp_enabled:
        raise HTTPException(
            status_code=403,
            detail="MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features.",
        )

    # Get user_id if user is authenticated
    user_id = str(current_user.id) if current_user else None

    thread_id = request.thread_id
    # Skip conversation creation for tool execution requests
    is_tool_execution = thread_id and thread_id.startswith("__tool_exec_")
    
    is_new_conversation = thread_id == "__default__"
    if is_new_conversation:
        thread_id = str(uuid4())
    else:
        # Check if conversation exists in database to determine if it's truly a new conversation
        try:
            existing_conv = get_conversation_by_thread_id(thread_id, None, True)
            if existing_conv:
                # Conversation exists, this is a continuation
                is_new_conversation = False
            else:
                # Conversation doesn't exist, this is a new conversation
                is_new_conversation = True
        except Exception as e:
            logger.warning(f"Failed to check if conversation exists: {e}, assuming new conversation")
            # If check fails, default to new conversation if thread_id is not "__default__"
            # (but we already set is_new_conversation above, so this is just for safety)
    
    # Extract title from first message if this is a new conversation
    title = None
    initial_messages = None
    if is_new_conversation and not is_tool_execution:
        title = _extract_title_from_messages(request.messages)
        # Create initial message list with first user message
        if request.messages:
            first_message = request.messages[0]
            if isinstance(first_message, dict) and "content" in first_message:
                initial_messages = [{
                    "id": str(uuid4()),
                    "thread_id": thread_id,
                    "role": first_message.get("role", "user"),
                    "content": first_message.get("content", ""),
                }]
        
        # Immediately create conversation record in database
        checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
        logger.debug(f"Checkpoint saver enabled: {checkpoint_saver}, thread_id: {thread_id}, user_id: {user_id}")
        if checkpoint_saver:
            try:
                initial_title = title or "新对话"
                logger.info(f"Attempting to create conversation: thread_id={thread_id}, title={initial_title}, user_id={user_id}, initial_messages_count={len(initial_messages) if initial_messages else 0}")
                success = create_conversation(thread_id, initial_title, initial_messages, user_id)
                if success:
                    logger.info(f"Created conversation immediately: thread_id={thread_id}, title={initial_title}, user_id={user_id}")
                else:
                    logger.warning(f"Failed to create conversation (returned False): thread_id={thread_id}")
            except Exception as e:
                logger.error(f"Failed to create conversation immediately: {e}", exc_info=True)
        else:
            logger.warning("Checkpoint saver is disabled, skipping conversation creation")

    return StreamingResponse(
        _astream_workflow_generator(
            request.model_dump()["messages"],
            thread_id,
            request.resources,
            request.max_plan_iterations,
            request.max_step_num,
            request.max_search_results,
            request.auto_accepted_plan,
            request.interrupt_feedback,
            request.mcp_settings if mcp_enabled else {},
            request.enable_background_investigation,
            request.report_style,
            request.enable_deep_thinking,
            request.enable_clarification,
            request.max_clarification_rounds,
            request.selected_model,
            title=title,
            is_new_conversation=is_new_conversation,
        ),
        media_type="text/event-stream",
    )


def _process_tool_call_chunks(tool_call_chunks):
    """Process tool call chunks and sanitize arguments."""
    chunks = []
    for chunk in tool_call_chunks:
        chunks.append(
            {
                "name": chunk.get("name", ""),
                "args": sanitize_args(chunk.get("args", "")),
                "id": chunk.get("id", ""),
                "index": chunk.get("index", 0),
                "type": chunk.get("type", ""),
            }
        )
    return chunks


def _get_agent_name(agent, message_metadata):
    """Extract agent name from agent tuple."""
    agent_name = "unknown"
    if agent and len(agent) > 0:
        agent_name = agent[0].split(":")[0] if ":" in agent[0] else agent[0]
    else:
        agent_name = message_metadata.get("langgraph_node", "unknown")
    return agent_name


def _create_event_stream_message(
    message_chunk, message_metadata, thread_id, agent_name
):
    """Create base event stream message."""
    content = message_chunk.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    
    event_stream_message = {
        "thread_id": thread_id,
        "agent": agent_name,
        "id": message_chunk.id,
        "role": "assistant",
        "checkpoint_ns": message_metadata.get("checkpoint_ns", ""),
        "langgraph_node": message_metadata.get("langgraph_node", ""),
        "langgraph_path": message_metadata.get("langgraph_path", ""),
        "langgraph_step": message_metadata.get("langgraph_step", ""),
        "content": content,
    }

    # Add optional fields
    if message_chunk.additional_kwargs.get("reasoning_content"):
        event_stream_message["reasoning_content"] = message_chunk.additional_kwargs[
            "reasoning_content"
        ]

    if message_chunk.response_metadata.get("finish_reason"):
        event_stream_message["finish_reason"] = message_chunk.response_metadata.get(
            "finish_reason"
        )
    
    # Add tool_calls if present (for AIMessageChunk)
    if hasattr(message_chunk, "tool_calls") and message_chunk.tool_calls:
        event_stream_message["tool_calls"] = message_chunk.tool_calls
    
    # Add tool_call_id if present (for ToolMessage)
    if hasattr(message_chunk, "tool_call_id") and message_chunk.tool_call_id:
        event_stream_message["tool_call_id"] = message_chunk.tool_call_id

    return event_stream_message


def _create_interrupt_event(thread_id, event_data):
    """Create interrupt event."""
    interrupt_info = event_data["__interrupt__"][0]
    
    # Handle different interrupt formats
    if hasattr(interrupt_info, 'ns') and hasattr(interrupt_info, 'value'):
        interrupt_id = interrupt_info.ns[0] if interrupt_info.ns else f"interrupt_{hash(str(interrupt_info)) % 1000000}"
        interrupt_content = interrupt_info.value
    else:
        interrupt_id = f"interrupt_{hash(str(interrupt_info)) % 1000000}"
        interrupt_content = str(interrupt_info)
    
    return _make_event(
        "interrupt",
        {
            "thread_id": thread_id,
            "id": interrupt_id,
            "role": "assistant",
            "content": interrupt_content,
            "finish_reason": "interrupt",
            "options": [
                {"text": "Edit plan", "value": "edit_plan"},
                {"text": "Start research", "value": "accepted"},
            ],
        },
    )


def _extract_title_from_messages(messages: List[dict]) -> str:
    """
    Extract conversation title from messages.
    
    Priority:
    1. Extract from plan title if available (from planner/molecular_planner agent messages)
    2. Extract from first user message content (first 50 characters)
    
    Args:
        messages: List of message dictionaries
        
    Returns:
        Extracted title string
    """
    # Try to find plan title from planner messages
    for message in messages:
        if isinstance(message, dict):
            content = message.get("content", "")
            agent = message.get("agent", "")
            
            # Check if this is a planner message with plan JSON
            if agent in ("planner", "molecular_planner", "literature_planner") and content:
                try:
                    # Try to parse plan JSON from content
                    if content.strip().startswith("```json"):
                        # Extract JSON from markdown code block
                        json_start = content.find("{")
                        json_end = content.rfind("}") + 1
                        if json_start >= 0 and json_end > json_start:
                            content = content[json_start:json_end]
                    elif content.strip().startswith("```"):
                        # Skip markdown code block markers
                        lines = content.strip().split("\n")
                        json_lines = [line for line in lines if not line.strip().startswith("```")]
                        content = "\n".join(json_lines)
                    
                    plan_data = json.loads(content)
                    if isinstance(plan_data, dict) and "title" in plan_data:
                        title = plan_data["title"]
                        if title and len(title) > 0:
                            return title[:100]  # Limit to 100 characters
                except (json.JSONDecodeError, KeyError, AttributeError):
                    pass
    
    # Fall back to first user message
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            if content:
                # Extract first 50 characters, clean up whitespace
                title = content.strip()[:50].replace("\n", " ").replace("\r", " ")
                if len(title) < 50 and len(content) > 50:
                    title += "..."
                return title if title else "新对话"
    
    return "新对话"


def _process_initial_messages(message, thread_id):
    """Process initial messages and yield formatted events."""
    json_data = json.dumps(
        {
            "thread_id": thread_id,
            "id": "run--" + message.get("id", uuid4().hex),
            "role": "user",
            "content": message.get("content", ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Removed chat_stream_message call to avoid checkpoint dependency


async def _process_message_chunk(message_chunk, message_metadata, thread_id, agent):
    """Process a single message chunk and yield appropriate events."""
    agent_name = _get_agent_name(agent, message_metadata)
    event_stream_message = _create_event_stream_message(
        message_chunk, message_metadata, thread_id, agent_name
    )

    if isinstance(message_chunk, ToolMessage):
        # Tool Message - Return the result of the tool call
        event_stream_message["tool_call_id"] = message_chunk.tool_call_id
        yield _make_event("tool_call_result", event_stream_message)
    elif isinstance(message_chunk, AIMessageChunk):
        # AI Message - Raw message tokens
        if message_chunk.tool_calls:
            # AI Message - Tool Call
            event_stream_message["tool_calls"] = message_chunk.tool_calls
            event_stream_message["tool_call_chunks"] = _process_tool_call_chunks(
                message_chunk.tool_call_chunks
            )
            yield _make_event("tool_calls", event_stream_message)
        elif message_chunk.tool_call_chunks:
            # AI Message - Tool Call Chunks
            event_stream_message["tool_call_chunks"] = _process_tool_call_chunks(
                message_chunk.tool_call_chunks
            )
            yield _make_event("tool_call_chunks", event_stream_message)
        else:
            # AI Message - Raw message tokens
            yield _make_event("message_chunk", event_stream_message)


async def _stream_graph_events(
    graph_instance, workflow_input, workflow_config, thread_id, title: Optional[str] = None,
    persisted_messages: Optional[list] = None,
):
    """Stream events from the graph and process them."""
    try:
        async for event_tuple in graph_instance.astream(
            workflow_input,
            config=workflow_config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            # Handle different event formats
            if isinstance(event_tuple, tuple) and len(event_tuple) >= 2:
                agent, _, event_data = event_tuple
            else:
                logger.warning(f"Unexpected event_tuple format: {event_tuple}")
                continue
            
            if isinstance(event_data, dict):
                # Handle interrupt events
                if "__interrupt__" in event_data:
                    interrupt_event = _create_interrupt_event(thread_id, event_data)
                    if persisted_messages is not None and "data: " in interrupt_event:
                        try:
                            persisted_messages.append(json.loads(interrupt_event.split("data: ", 1)[1]))
                        except Exception:
                            pass
                    yield interrupt_event
                    continue
                
                # Handle updates dict - extract messages from node updates
                for node_name, node_data in event_data.items():
                    if node_name == "__interrupt__":
                        yield _create_interrupt_event(thread_id, {"__interrupt__": node_data})
                        continue
                    
                    if isinstance(node_data, dict):
                        # Handle final_report from reporter nodes
                        final_report_handled = False
                        final_report_id = None
                        if "final_report" in node_data:
                            report_content = node_data["final_report"]
                            logger.info(f"Yielding final_report from {node_name}, content length: {len(report_content)}")
                            # #region debug log
                            try:
                                import time
                                with open("/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log", "a") as f:
                                    f.write(json.dumps({
                                        "location": "app.py:_stream_graph_events:604",
                                        "message": "Processing final_report",
                                        "data": {
                                            "node_name": node_name,
                                            "content_length": len(report_content),
                                            "has_img_tag": "<img" in report_content,
                                        },
                                        "timestamp": int(time.time() * 1000),
                                        "sessionId": "debug-session",
                                        "runId": "run1",
                                        "hypothesisId": "A"
                                    }) + "\n")
                            except: pass
                            # #endregion
                            # Generate a unique ID for the final report
                            report_id = f"report--{uuid4()}"
                            final_report_id = report_id
                            event_data = {
                                "id": report_id,
                                "thread_id": thread_id,
                                "role": "assistant",
                                "agent": node_name,  # Use actual node_name as string (common_reporter or reporter)
                                "content": report_content,
                                "finish_reason": "stop",
                            }
                            # #region debug log
                            try:
                                import time
                                with open("/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log", "a") as f:
                                    f.write(json.dumps({
                                        "location": "app.py:_stream_graph_events:616",
                                        "message": "Created final_report event_data",
                                        "data": {
                                            "id": report_id,
                                            "agent": event_data.get("agent"),
                                            "finish_reason": event_data.get("finish_reason"),
                                            "content_length": len(event_data.get("content", "")),
                                        },
                                        "timestamp": int(time.time() * 1000),
                                        "sessionId": "debug-session",
                                        "runId": "run1",
                                        "hypothesisId": "A"
                                    }) + "\n")
                            except: pass
                            # #endregion
                            # Ensure agent is a string, not a list
                            if isinstance(event_data.get("agent"), list):
                                event_data["agent"] = event_data["agent"][0] if event_data["agent"] else "unknown"
                            
                            out_evt = _make_event("message_chunk", event_data)
                            if persisted_messages is not None and "data: " in out_evt:
                                try:
                                    persisted_msg = json.loads(out_evt.split("data: ", 1)[1])
                                    # Ensure agent is string format in persisted message
                                    if isinstance(persisted_msg.get("agent"), list):
                                        persisted_msg["agent"] = persisted_msg["agent"][0] if persisted_msg["agent"] else "unknown"
                                    # Mark this as a final_report message to prevent merging with streaming chunks
                                    persisted_msg["_is_final_report"] = True
                                    persisted_messages.append(persisted_msg)
                                    final_report_handled = True
                                    logger.info(f"Added final_report to persisted_messages: agent={persisted_msg.get('agent')}, content_length={len(report_content)}, id={report_id}")
                                except Exception as e:
                                    logger.warning(f"Failed to add final_report to persisted_messages: {e}")
                            yield out_evt
                        
                        # Handle messages
                        # IMPORTANT: If final_report was already handled, skip streaming messages
                        # This prevents duplicate reporter messages (one from final_report, one from streamed messages)
                        if "messages" in node_data:
                            # Only process messages if there's no final_report (for nodes that don't return final_report)
                            # Reporter nodes return both final_report and messages, but we only want final_report
                            should_process_messages = True
                            if final_report_handled and node_name in ("reporter", "common_reporter"):
                                should_process_messages = False
                                logger.info(f"Skipping messages streaming for {node_name} since final_report was already handled (id: {final_report_id})")
                            
                            if should_process_messages:
                                for message in node_data["messages"]:
                                    # Extract agent name from node name if agent tuple is empty
                                    effective_agent = agent if agent else (node_name,)
                                    # Create metadata for this message
                                    message_metadata = {
                                        "checkpoint_ns": "",
                                        "langgraph_node": node_name,
                                        "langgraph_path": "",
                                        "langgraph_step": ""
                                    }
                                    async for event in _process_message_chunk(
                                        message, message_metadata, thread_id, effective_agent
                                    ):
                                        if persisted_messages is not None and "data: " in event:
                                            try:
                                                persisted_messages.append(json.loads(event.split("data: ", 1)[1]))
                                            except Exception:
                                                pass
                                        yield event
                continue

            message_chunk, message_metadata = cast(
                tuple[BaseMessage, dict[str, Any]], event_data
            )

            async for event in _process_message_chunk(
                message_chunk, message_metadata, thread_id, agent
            ):
                if persisted_messages is not None and "data: " in event:
                    try:
                        persisted_messages.append(json.loads(event.split("data: ", 1)[1]))
                    except Exception:
                        pass
                yield event
    except Exception as e:
        logger.exception("Error during graph execution")
        yield _make_event(
            "error",
            {
                "thread_id": thread_id,
                "error": "Error during graph execution",
            },
        )


async def _astream_workflow_generator(
    messages: List[dict],
    thread_id: str,
    resources: List[Resource],
    max_plan_iterations: int,
    max_step_num: int,
    max_search_results: int,
    auto_accepted_plan: bool,
    interrupt_feedback: str,
    mcp_settings: dict,
    enable_background_investigation: bool,
    report_style: ReportStyle,
    enable_deep_thinking: bool,
    enable_clarification: bool,
    max_clarification_rounds: int,
    selected_model: Optional[str] = None,
    title: Optional[str] = None,
    is_new_conversation: bool = False,
):
    # Skip conversation updates for tool execution requests
    is_tool_execution = thread_id and thread_id.startswith("__tool_exec_")
    
    # Process initial messages
    for message in messages:
        if isinstance(message, dict) and "content" in message:
            _process_initial_messages(message, thread_id)

    # Prepare workflow input
    workflow_input = {
        "messages": messages,
        "plan_iterations": 0,
        "final_report": "",
        "current_plan": None,
        "observations": [],
        "auto_accepted_plan": auto_accepted_plan,
        "enable_background_investigation": enable_background_investigation,
        "research_topic": messages[-1]["content"] if messages else "",
        "enable_clarification": enable_clarification,
        "max_clarification_rounds": max_clarification_rounds,
    }

    if not auto_accepted_plan and interrupt_feedback:
        resume_msg = f"[{interrupt_feedback}]"
        if messages:
            resume_msg += f" {messages[-1]['content']}"
        workflow_input = Command(resume=resume_msg)

    # Prepare workflow config
    workflow_config = {
        "thread_id": thread_id,
        "resources": resources,
        "max_plan_iterations": max_plan_iterations,
        "max_step_num": max_step_num,
        "max_search_results": max_search_results,
        "mcp_settings": mcp_settings,
        "report_style": report_style.value,
        "enable_deep_thinking": enable_deep_thinking,
        "recursion_limit": get_recursion_limit(),
        "selected_model": selected_model,
    }

    # Track conversation title and save when stream completes
    conversation_title = title
    persisted_messages: list = []
    
    # Add all user messages to persisted_messages at the start
    # This ensures user messages are saved even if the stream fails
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            user_msg = {
                "id": f"user--{uuid4().hex}",
                "thread_id": thread_id,
                "role": "user",
                "content": message.get("content", ""),
            }
            persisted_messages.append(user_msg)
    
    last_title_update = None
    last_message_update = 0
    message_update_interval = 10  # Update messages every 10 messages
    
    # Disable checkpoint functionality to avoid MongoDB connection issues
    # Use graph without checkpointer
    try:
        async for event in _stream_graph_events(
            graph, workflow_input, workflow_config, thread_id, conversation_title, persisted_messages
        ):
            # Try to extract title from planner messages if not already set
            if "data:" in event:
                try:
                    event_data = json.loads(event.split("data: ", 1)[1])
                    agent = event_data.get("agent", "")
                    content = event_data.get("content", "")
                    
                    # Try to extract plan title from planner messages
                    if agent in ("planner", "molecular_planner", "literature_planner") and content:
                        try:
                            # Parse plan JSON
                            plan_json = content
                            if "```json" in plan_json:
                                json_start = plan_json.find("{")
                                json_end = plan_json.rfind("}") + 1
                                if json_start >= 0 and json_end > json_start:
                                    plan_json = plan_json[json_start:json_end]
                            elif "```" in plan_json:
                                lines = plan_json.split("\n")
                                json_lines = [line for line in lines if not line.strip().startswith("```")]
                                plan_json = "\n".join(json_lines)
                            
                            plan_data = json.loads(plan_json)
                            if isinstance(plan_data, dict) and "title" in plan_data:
                                extracted_title = plan_data["title"]
                                if extracted_title and len(extracted_title) > 0:
                                    new_title = extracted_title[:100]
                                    # Real-time update title if changed
                                    if new_title != conversation_title and new_title != last_title_update:
                                        conversation_title = new_title
                                        last_title_update = new_title
                                        # Update title in database immediately
                                        if get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False) and not is_tool_execution:
                                            try:
                                                update_conversation(thread_id, title=new_title)
                                                logger.debug(f"Updated conversation title in real-time: thread_id={thread_id}, title={new_title}")
                                            except Exception as e:
                                                logger.warning(f"Failed to update conversation title: {e}")
                        except (json.JSONDecodeError, KeyError, AttributeError):
                            pass
                except (json.JSONDecodeError, AttributeError):
                    pass
            
            yield event
            
            # Periodically update messages in database (every N messages to avoid too frequent updates)
            # Determine if this is a continuation - use append mode to preserve existing messages
            is_continuation = not is_new_conversation or (interrupt_feedback and interrupt_feedback.strip())
            if persisted_messages and len(persisted_messages) - last_message_update >= message_update_interval:
                if get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False) and not is_tool_execution:
                    try:
                        # Validate message structure before saving
                        for idx, msg in enumerate(persisted_messages[-message_update_interval:]):
                            if not isinstance(msg, dict):
                                logger.warning(f"Invalid message type at index {idx}: {type(msg)}")
                                continue
                            # Log message structure for debugging
                            has_tool_calls = "tool_calls" in msg and msg.get("tool_calls")
                            has_tool_call_id = "tool_call_id" in msg and msg.get("tool_call_id")
                            has_reasoning = "reasoning_content" in msg and msg.get("reasoning_content")
                            if has_tool_calls or has_tool_call_id or has_reasoning:
                                logger.debug(
                                    f"Message {idx} structure: id={msg.get('id')}, agent={msg.get('agent')}, "
                                    f"tool_calls={has_tool_calls}, tool_call_id={has_tool_call_id}, "
                                    f"reasoning_content={has_reasoning}"
                                )
                        
                        # Real-time updates: append if continuation, replace if new conversation
                        # This ensures existing messages are preserved when continuing a conversation
                        update_conversation(thread_id, messages=persisted_messages, append=is_continuation)
                        last_message_update = len(persisted_messages)
                        logger.debug(f"Updated conversation messages in real-time: thread_id={thread_id}, count={len(persisted_messages)}, append={is_continuation}")
                    except Exception as e:
                        logger.warning(f"Failed to update conversation messages: {e}", exc_info=True)
        
        # Stream completed - save conversation with title
        if persisted_messages and get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False):
            # Always try to extract the best title from persisted messages
            # Priority: planner title > current title > user message > default
            extracted_title = None
            try:
                # Try to find plan title from planner messages (highest priority)
                # Collect all planner message chunks and merge them
                planner_messages = []
                for msg in persisted_messages:
                    agent = msg.get("agent", "")
                    if agent in ("planner", "molecular_planner", "literature_planner"):
                        content = msg.get("content", "")
                        if content:
                            planner_messages.append((msg, content))
                
                # Try to extract title from merged planner messages
                if planner_messages:
                    # Try each planner message individually first
                    for msg, content in planner_messages:
                        try:
                            plan_json = content
                            if "```json" in plan_json:
                                json_start = plan_json.find("{")
                                json_end = plan_json.rfind("}") + 1
                                if json_start >= 0 and json_end > json_start:
                                    plan_json = plan_json[json_start:json_end]
                            elif "```" in plan_json:
                                lines = plan_json.split("\n")
                                json_lines = [line for line in lines if not line.strip().startswith("```")]
                                plan_json = "\n".join(json_lines)
                            
                            plan_data = json.loads(plan_json)
                            if isinstance(plan_data, dict) and "title" in plan_data:
                                extracted_title = plan_data["title"]
                                if extracted_title and len(extracted_title) > 0:
                                    extracted_title = extracted_title[:100]
                                    break
                        except (json.JSONDecodeError, KeyError, AttributeError):
                            pass
                    
                    # If not found, try merging all planner content
                    if not extracted_title and len(planner_messages) > 1:
                        try:
                            merged_content = "".join([content for _, content in planner_messages])
                            # Try to extract JSON from merged content
                            json_start = merged_content.find("{")
                            json_end = merged_content.rfind("}") + 1
                            if json_start >= 0 and json_end > json_start:
                                plan_json = merged_content[json_start:json_end]
                                plan_data = json.loads(plan_json)
                                if isinstance(plan_data, dict) and "title" in plan_data:
                                    extracted_title = plan_data["title"]
                                    if extracted_title and len(extracted_title) > 0:
                                        extracted_title = extracted_title[:100]
                        except (json.JSONDecodeError, KeyError, AttributeError):
                            pass
            except Exception:
                pass
            
            # Use extracted title, or fall back to current conversation_title
            if extracted_title:
                logger.info(f"Extracted title from planner message: {extracted_title}")
                conversation_title = extracted_title
            elif not conversation_title:
                # Fall back to first user message if no title yet
                try:
                    for msg in persisted_messages:
                        if msg.get("role") == "user":
                            content = msg.get("content", "")
                            if content:
                                conversation_title = content[:50].replace("\n", " ").replace("\r", " ")
                                if len(content) > 50:
                                    conversation_title += "..."
                                logger.info(f"Using user message as title: {conversation_title}")
                                break
                except Exception:
                    pass
            
            # Use default title if still empty
            if not conversation_title:
                conversation_title = "新对话"
                logger.warning(f"No title extracted, using default: {conversation_title}")
            
            try:
                # Merge message chunks before saving (planner, researcher, reporter, common_reporter)
                # Improved strategy: merge chunks by message ID, even if non-consecutive
                chunkable_agents = ("planner", "molecular_planner", "literature_planner", "researcher", "reporter", "common_reporter")
                
                # Step 1: Group chunks by message ID for chunkable agents
                # This allows merging chunks even if they're separated by other messages (e.g., tool_call_result)
                chunks_by_id: dict[str, list[dict]] = {}
                non_chunkable_messages: list[dict] = []
                message_order: list[tuple[str, bool]] = []  # (message_id or index, is_chunkable)
                
                logger.debug(f"Starting message merge: total messages={len(persisted_messages)}")
                
                for idx, msg in enumerate(persisted_messages):
                    agent = msg.get("agent", "")
                    # Normalize agent field: if it's a list, extract the first element
                    if isinstance(agent, list):
                        agent = agent[0] if agent else ""
                    # Ensure agent is a string
                    if not isinstance(agent, str):
                        agent = str(agent) if agent else ""
                    
                    msg_id = msg.get("id", "")
                    is_final_report = msg.get("_is_final_report", False)
                    
                    # Handle chunkable agents (except final_report which should not be merged)
                    # For chunkable messages without ID, generate a unique ID to ensure they are not lost
                    if agent in chunkable_agents and not is_final_report:
                        # Generate ID if missing - use unique ID per message to avoid incorrect merging
                        # If chunks belong to the same message, they should have the same ID from the source
                        if not msg_id:
                            # Generate a unique ID based on agent and index
                            # This ensures each message gets a unique ID and won't be incorrectly merged
                            msg_id = f"{agent}_no_id_{idx}"
                            msg["id"] = msg_id  # Update the message with generated ID
                            logger.warning(f"Chunkable message without ID: agent={agent}, idx={idx}, generated unique ID={msg_id}. "
                                         f"This message will not be merged with others. Content preview: {str(msg.get('content', ''))[:100]}")
                        
                        if msg_id not in chunks_by_id:
                            chunks_by_id[msg_id] = []
                        chunks_by_id[msg_id].append((idx, msg))
                        message_order.append((msg_id, True))
                        logger.debug(f"Chunkable message: agent={agent}, id={msg_id}, idx={idx}, content_length={len(str(msg.get('content', '')))}")
                    else:
                        # Non-chunkable message or final_report
                        non_chunkable_messages.append((idx, msg))
                        message_order.append((f"non_chunkable_{idx}", False))
                        if is_final_report:
                            logger.debug(f"Final report message: agent={agent}, id={msg_id}, idx={idx}")
                        else:
                            logger.debug(f"Non-chunkable message: agent={agent}, id={msg_id}, idx={idx}")
                
                logger.debug(f"Grouped chunks: {len(chunks_by_id)} unique message IDs with chunks, {len(non_chunkable_messages)} non-chunkable messages")
                
                # Step 2: Merge chunks with same ID and build ordered result
                merged_by_id: dict[str, dict] = {}
                total_chunks_merged = 0
                for msg_id, chunks in chunks_by_id.items():
                    if len(chunks) == 1:
                        # Single chunk, no merging needed
                        _, msg = chunks[0]
                        merged_by_id[msg_id] = dict(msg)
                        logger.debug(f"Single chunk (no merge): agent={msg.get('agent')}, id={msg_id}, content_length={len(str(msg.get('content', '')))}")
                    else:
                        # Multiple chunks, merge them
                        # Sort by original index to maintain order
                        chunks_sorted = sorted(chunks, key=lambda x: x[0])
                        base_msg = dict(chunks_sorted[0][1])
                        # Merge content while preserving encoding (ensure_ascii=False is used in JSON serialization)
                        merged_content = "".join([str(chunk[1].get("content", "")) for chunk in chunks_sorted])
                        base_msg["content"] = merged_content
                        # Ensure ID is set
                        if not base_msg.get("id"):
                            base_msg["id"] = msg_id
                        merged_by_id[msg_id] = base_msg
                        total_chunks_merged += len(chunks)
                        logger.info(f"Merged {len(chunks)} chunks for agent={base_msg.get('agent')}, id={msg_id}, content_length={len(merged_content)}")
                
                if total_chunks_merged > 0:
                    logger.info(f"Message merge summary: {len(chunks_by_id)} messages processed, {total_chunks_merged} chunks merged")
                
                # Step 3: Reconstruct ordered list preserving original message order
                ordered_merged = []
                chunkable_seen: set[str] = set()
                
                for msg_key, is_chunkable in message_order:
                    if is_chunkable:
                        # Chunkable message - use merged version
                        if msg_key not in chunkable_seen:
                            if msg_key in merged_by_id:
                                ordered_merged.append(merged_by_id[msg_key])
                                chunkable_seen.add(msg_key)
                            else:
                                logger.warning(f"Message ID {msg_key} in message_order but not found in merged_by_id - this should not happen")
                    else:
                        # Non-chunkable message - find and add it
                        try:
                            idx = int(msg_key.split("_")[-1])
                            found = False
                            for orig_idx, msg in non_chunkable_messages:
                                if orig_idx == idx:
                                    # Handle final_report: remove marker before saving
                                    if msg.get("_is_final_report", False):
                                        final_msg = dict(msg)
                                        final_msg.pop("_is_final_report", None)
                                        ordered_merged.append(final_msg)
                                        logger.info(f"Preserved final_report message (id: {final_msg.get('id')}, content_length: {len(final_msg.get('content', ''))}, agent: {msg.get('agent')})")
                                        # #region debug log
                                        try:
                                            import time
                                            with open("/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log", "a") as f:
                                                f.write(json.dumps({
                                                    "location": "app.py:_astream_workflow_generator:1047",
                                                    "message": "Preserved final_report message",
                                                    "data": {
                                                        "message_id": final_msg.get('id'),
                                                        "agent": final_msg.get('agent'),
                                                        "content_length": len(final_msg.get('content', '')),
                                                        "has_finish_reason": "finish_reason" in final_msg,
                                                        "finish_reason": final_msg.get('finish_reason'),
                                                    },
                                                    "timestamp": int(time.time() * 1000),
                                                    "sessionId": "debug-session",
                                                    "runId": "run1",
                                                    "hypothesisId": "A"
                                                }) + "\n")
                                        except: pass
                                        # #endregion
                                    else:
                                        ordered_merged.append(msg)
                                    found = True
                                    break
                            if not found:
                                logger.warning(f"Non-chunkable message at index {idx} not found in non_chunkable_messages")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Failed to parse non_chunkable index from {msg_key}: {e}")
                
                # Verify all messages were included
                expected_count = len(chunks_by_id) + len(non_chunkable_messages)
                if len(ordered_merged) != expected_count:
                    logger.warning(f"Message count mismatch: expected {expected_count}, got {len(ordered_merged)}. "
                                 f"chunks_by_id={len(chunks_by_id)}, non_chunkable={len(non_chunkable_messages)}")
                
                logger.info(f"Message merge completed: {len(ordered_merged)} messages in final list (original: {len(persisted_messages)}, expected: {expected_count})")
                
                # Check existing conversation title before updating
                # Only update title if it hasn't been finalized (not "新对话")
                existing_title = None
                try:
                    existing_conv = get_conversation_by_thread_id(thread_id, None, True)
                    if existing_conv:
                        existing_title = existing_conv.get("title", "新对话")
                except Exception as e:
                    logger.warning(f"Failed to get existing conversation for title check: {e}")
                
                # Title protection: if title is already finalized (not "新对话"), don't update it
                final_title = conversation_title
                if existing_title and existing_title != "新对话":
                    # Title already finalized, keep the existing title
                    final_title = None  # Don't update title
                    logger.info(f"Title already finalized ({existing_title}), keeping it unchanged")
                elif conversation_title == "新对话" and existing_title and existing_title != "新对话":
                    # Don't overwrite a finalized title with default
                    final_title = None
                    logger.info(f"Keeping existing finalized title ({existing_title}) instead of default")
                
                # Determine if this is a continuation of existing conversation
                # If interrupt_feedback exists, it means user clicked "Start research" - this is a continuation
                # If is_new_conversation is True, it means this is a brand new conversation - should replace
                is_continuation = not is_new_conversation or (interrupt_feedback and interrupt_feedback.strip())
                
                # Before final update, verify existing messages if continuation
                existing_db_count = 0
                if is_continuation:
                    try:
                        existing_conv = get_conversation_by_thread_id(thread_id, None, True)
                        if existing_conv:
                            existing_messages = existing_conv.get("messages", [])
                            existing_db_count = len(existing_messages) if isinstance(existing_messages, list) else 0
                            logger.info(f"Before final update: thread_id={thread_id}, existing_db_messages={existing_db_count}, new_messages_to_append={len(ordered_merged)}")
                    except Exception as e:
                        logger.warning(f"Failed to get existing messages count before final update: {e}")
                
                logger.info(f"Final update conversation: thread_id={thread_id}, title={final_title or existing_title or conversation_title}, messages_count={len(ordered_merged)} (merged from {len(persisted_messages)} chunks), append={is_continuation}, existing_db_count={existing_db_count}")
                # Final update: append new messages if continuation, replace if new conversation
                # Skip update for tool execution requests
                if not is_tool_execution:
                    update_conversation(
                        thread_id=thread_id,
                        title=final_title,
                        messages=ordered_merged,
                        append=is_continuation,  # Append if continuation, replace if new
                    )
                
                # Verify after update
                if is_continuation and existing_db_count > 0:
                    try:
                        updated_conv = get_conversation_by_thread_id(thread_id, None, True)
                        if updated_conv:
                            updated_messages = updated_conv.get("messages", [])
                            updated_count = len(updated_messages) if isinstance(updated_messages, list) else 0
                            if updated_count < existing_db_count:
                                logger.error(
                                    f"CRITICAL: Message count decreased after final update! "
                                    f"thread_id={thread_id}, before={existing_db_count}, after={updated_count}. "
                                    f"Messages were lost!"
                                )
                            else:
                                logger.info(f"Final update verified: thread_id={thread_id}, before={existing_db_count}, after={updated_count}, added={updated_count - existing_db_count}")
                    except Exception as e:
                        logger.warning(f"Failed to verify messages after final update: {e}")
                logger.info(f"Conversation updated successfully: thread_id={thread_id}")
            except Exception as e:
                logger.warning(f"Failed to update conversation: {e}", exc_info=True)
    except Exception as e:
        logger.exception(f"Error in graph execution: {str(e)}")
        yield _make_event(
            "error",
            {
                "thread_id": thread_id,
                "error": f"Graph execution error: {str(e)}",
            },
        )


def _make_event(event_type: str, data: dict[str, any]):
    if data.get("content") == "":
        data.pop("content")
    # Ensure JSON serialization with proper encoding
    try:
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event: {event_type}\ndata: {json_data}\n\n"
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing event data: {e}")
        # Return a safe error event
        error_data = json.dumps({"error": "Serialization failed"}, ensure_ascii=False)
        return f"event: error\ndata: {error_data}\n\n"


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using volcengine TTS API."""
    app_id = get_str_env("VOLCENGINE_TTS_APPID", "")
    if not app_id:
        raise HTTPException(status_code=400, detail="VOLCENGINE_TTS_APPID is not set")
    access_token = get_str_env("VOLCENGINE_TTS_ACCESS_TOKEN", "")
    if not access_token:
        raise HTTPException(
            status_code=400, detail="VOLCENGINE_TTS_ACCESS_TOKEN is not set"
        )

    try:
        cluster = get_str_env("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
        voice_type = get_str_env("VOLCENGINE_TTS_VOICE_TYPE", "BV700_V2_streaming")

        tts_client = VolcengineTTS(
            appid=app_id,
            access_token=access_token,
            cluster=cluster,
            voice_type=voice_type,
        )
        # Call the TTS API
        result = tts_client.text_to_speech(
            text=request.text[:1024],
            encoding=request.encoding,
            speed_ratio=request.speed_ratio,
            volume_ratio=request.volume_ratio,
            pitch_ratio=request.pitch_ratio,
            text_type=request.text_type,
            with_frontend=request.with_frontend,
            frontend_type=request.frontend_type,
        )

        if not result["success"]:
            raise HTTPException(status_code=500, detail=str(result["error"]))

        # Decode the base64 audio data
        audio_data = base64.b64decode(result["audio_data"])

        # Return the audio file
        return Response(
            content=audio_data,
            media_type=f"audio/{request.encoding}",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=tts_output.{request.encoding}"
                )
            },
        )

    except Exception as e:
        logger.exception(f"Error in TTS endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/podcast/generate")
async def generate_podcast(request: GeneratePodcastRequest):
    try:
        report_content = request.content
        print(report_content)
        workflow = build_podcast_graph()
        final_state = workflow.invoke({"input": report_content})
        audio_bytes = final_state["output"]
        return Response(content=audio_bytes, media_type="audio/mp3")
    except Exception as e:
        logger.exception(f"Error occurred during podcast generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/ppt/generate")
async def generate_ppt(request: GeneratePPTRequest):
    try:
        report_content = request.content
        print(report_content)
        workflow = build_ppt_graph()
        final_state = workflow.invoke({"input": report_content})
        generated_file_path = final_state["generated_file_path"]
        with open(generated_file_path, "rb") as f:
            ppt_bytes = f.read()
        return Response(
            content=ppt_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    except Exception as e:
        logger.exception(f"Error occurred during ppt generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/prose/generate")
async def generate_prose(request: GenerateProseRequest):
    try:
        sanitized_prompt = request.prompt.replace("\r\n", "").replace("\n", "")
        logger.info(f"Generating prose for prompt: {sanitized_prompt}")
        workflow = build_prose_graph()
        events = workflow.astream(
            {
                "content": request.prompt,
                "option": request.option,
                "command": request.command,
            },
            stream_mode="messages",
            subgraphs=True,
        )
        return StreamingResponse(
            (f"data: {event[0].content}\n\n" async for _, event in events),
            media_type="text/event-stream",
        )
    except Exception as e:
        logger.exception(f"Error occurred during prose generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/prompt/enhance")
async def enhance_prompt(request: EnhancePromptRequest):
    try:
        sanitized_prompt = request.prompt.replace("\r\n", "").replace("\n", "")
        logger.info(f"Enhancing prompt: {sanitized_prompt}")

        # Convert string report_style to ReportStyle enum
        report_style = None
        if request.report_style:
            try:
                # Handle both uppercase and lowercase input
                style_mapping = {
                    "ACADEMIC": ReportStyle.ACADEMIC,
                    "POPULAR_SCIENCE": ReportStyle.POPULAR_SCIENCE,
                    "NEWS": ReportStyle.NEWS,
                    "SOCIAL_MEDIA": ReportStyle.SOCIAL_MEDIA,
                    "STRATEGIC_INVESTMENT": ReportStyle.STRATEGIC_INVESTMENT,
                }
                report_style = style_mapping.get(
                    request.report_style.upper(), ReportStyle.ACADEMIC
                )
            except Exception:
                # If invalid style, default to ACADEMIC
                report_style = ReportStyle.ACADEMIC
        else:
            report_style = ReportStyle.ACADEMIC

        workflow = build_prompt_enhancer_graph()
        final_state = workflow.invoke(
            {
                "prompt": request.prompt,
                "context": request.context,
                "report_style": report_style,
            }
        )
        return {"result": final_state["output"]}
    except Exception as e:
        logger.exception(f"Error occurred during prompt enhancement: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/mcp/server/metadata", response_model=MCPServerMetadataResponse)
async def mcp_server_metadata(request: MCPServerMetadataRequest):
    """Get information about an MCP server."""
    # Check if MCP server configuration is enabled
    if not get_bool_env("ENABLE_MCP_SERVER_CONFIGURATION", False):
        raise HTTPException(
            status_code=403,
            detail="MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features.",
        )

    try:
        # Set default timeout with a longer value for this endpoint
        timeout = 300  # Default to 300 seconds for this endpoint

        # Use custom timeout from request if provided
        if request.timeout_seconds is not None:
            timeout = request.timeout_seconds

        # Load tools from the MCP server using the utility function
        tools = await load_mcp_tools(
            server_type=request.transport,
            command=request.command,
            args=request.args,
            url=request.url,
            env=request.env,
            headers=request.headers,
            timeout_seconds=timeout,
        )

        # Create the response with tools
        response = MCPServerMetadataResponse(
            transport=request.transport,
            command=request.command,
            args=request.args,
            url=request.url,
            env=request.env,
            headers=request.headers,
            tools=tools,
        )

        return response
    except Exception as e:
        logger.exception(f"Error in MCP server metadata endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.get("/api/rag/config", response_model=RAGConfigResponse)
async def rag_config():
    """Get the config of the RAG."""
    return RAGConfigResponse(provider=SELECTED_RAG_PROVIDER)


@app.get("/api/rag/resources", response_model=RAGResourcesResponse)
async def rag_resources(request: Annotated[RAGResourceRequest, Query()]):
    """Get the resources of the RAG."""
    retriever = build_retriever()
    if retriever:
        return RAGResourcesResponse(resources=retriever.list_resources(request.query))
    return RAGResourcesResponse(resources=[])


@app.get("/rag/resources", response_model=RAGResourcesResponse)
async def rag_resources_compat(request: Annotated[RAGResourceRequest, Query()]):
    """
    兼容旧路径 /rag/resources，内部直接复用 /api/rag/resources 的逻辑。
    这样即使前端还在请求 http://localhost:8008/rag/resources 也能正常返回。
    """
    return await rag_resources(request)


@app.get("/api/rag/resources/{resource_id}/documents", response_model=RAGDocumentsResponse)
async def rag_documents(resource_id: str, page: int = 1, page_size: int = 50):
    """Get the documents in a specific resource (knowledge base) with pagination."""
    try:
        retriever = build_retriever()
        if not retriever:
            raise HTTPException(status_code=503, detail="RAG provider is not configured")
        
        # Extract dataset ID from resource_id (format: rag://dataset/{id})
        # If resource_id is already just the ID, use it directly
        if resource_id.startswith("rag://dataset/"):
            dataset_id = resource_id.replace("rag://dataset/", "")
        else:
            dataset_id = resource_id
        
        logger.info(f"Fetching documents for resource_id: {resource_id}, dataset_id: {dataset_id}, page={page}, page_size={page_size}")
        logger.info(f"RAG provider type: {type(retriever).__name__}")
        
        documents, total = retriever.list_documents(dataset_id, page=page, page_size=page_size)
        
        logger.info(f"Retrieved {len(documents)} documents (page {page}, total: {total})")
        
        # Convert Document objects to RAGDocument models
        rag_docs = [
            RAGDocument(
                id=doc.id,
                title=doc.title or doc.id,
                upload_date=doc.upload_date,
                size=doc.size,
            )
            for doc in documents
        ]
        
        return RAGDocumentsResponse(documents=rag_docs, total=total)
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Document listing is not supported by the current RAG provider"
        )
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error listing documents for resource {resource_id}: {error_msg}")
        # Return more detailed error message to help debug
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list documents: {error_msg}"
        )


@app.get("/api/rag/resources/{resource_id}/documents/{document_id}/download")
async def rag_document_download(resource_id: str, document_id: str):
    """Download a document from a specific resource (knowledge base)."""
    try:
        retriever = build_retriever()
        if not retriever:
            raise HTTPException(status_code=503, detail="RAG provider is not configured")
        
        # Extract dataset ID from resource_id (format: rag://dataset/{id})
        # If resource_id is already just the ID, use it directly
        if resource_id.startswith("rag://dataset/"):
            dataset_id = resource_id.replace("rag://dataset/", "")
        else:
            dataset_id = resource_id
        
        logger.info(f"Downloading document {document_id} from resource_id: {resource_id}, dataset_id: {dataset_id}")
        logger.info(f"RAG provider type: {type(retriever).__name__}")
        
        file_content, filename, content_type = retriever.download_document(dataset_id, document_id)
        
        # Ensure filename has proper extension
        # If filename doesn't have extension, try to infer from content_type
        import mimetypes
        if '.' not in filename or not filename.split('.')[-1] or len(filename.split('.')[-1]) > 5:
            # Filename doesn't have a valid extension, try to add one from content_type
            if content_type and content_type != "application/octet-stream":
                ext = mimetypes.guess_extension(content_type)
                if ext:
                    # Remove existing extension if it looks invalid, then add correct one
                    if '.' in filename:
                        # Check if the last part after dot looks like an extension (1-5 chars)
                        parts = filename.rsplit('.', 1)
                        if len(parts) == 2 and (len(parts[1]) > 5 or not parts[1].isalnum()):
                            filename = parts[0] + ext
                        else:
                            filename = filename + ext
                    else:
                        filename = filename + ext
        
        # Handle filename encoding for Content-Disposition header
        # Starlette requires header values to be latin-1 encodable
        from urllib.parse import quote
        try:
            # Try to encode as latin-1 (ASCII-compatible)
            filename_latin1 = filename.encode('latin-1', errors='replace').decode('latin-1')
            # If filename contains only ASCII characters, use simple format
            if filename == filename_latin1:
                content_disposition = f'attachment; filename="{filename}"'
            else:
                # For non-ASCII characters, use RFC 5987 format (filename*=UTF-8'')
                # Also provide ASCII fallback for compatibility
                encoded_filename = quote(filename, safe='')
                # Use both formats: ASCII fallback and UTF-8 encoded
                ascii_fallback = filename.encode('ascii', errors='ignore').decode('ascii')
                if ascii_fallback and ascii_fallback != filename:
                    content_disposition = f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}'
                else:
                    content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
        except Exception as e:
            # Fallback: use URL-encoded filename
            encoded_filename = quote(filename, safe='')
            content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
            logger.warning(f"Error encoding filename: {e}, using fallback")
        
        # Set response headers for file download
        headers = {
            "Content-Disposition": content_disposition,
            "Content-Type": content_type,
        }
        
        logger.info(f"Successfully downloaded document {document_id}")
        logger.info(f"  - Filename: {filename}")
        logger.info(f"  - Content-Disposition: {content_disposition}")
        logger.info(f"  - Content-Type: {content_type}")
        logger.info(f"  - Size: {len(file_content)} bytes")
        return Response(content=file_content, headers=headers)
        
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Document download is not supported by the current RAG provider"
        )
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error downloading document {document_id} from resource {resource_id}: {error_msg}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download document: {error_msg}"
        )


@app.get("/api/config", response_model=ConfigResponse)
async def config():
    """Get the config of the server."""
    return ConfigResponse(
        rag=RAGConfigResponse(provider=SELECTED_RAG_PROVIDER),
        models=get_configured_llm_models(),
    )


@app.get("/config", response_model=ConfigResponse)
async def config_compat():
    """
    兼容旧路径 /config，内部复用 /api/config 的实现。
    某些前端或调试工具可能直接请求 /config。
    """
    return await config()


@app.get("/api/conversations")
async def list_conversations(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of conversations to return"),
    offset: int = Query(0, ge=0, description="Number of conversations to skip"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get list of conversations ordered by updated_at descending.

    Returns:
        List of conversation objects with id, thread_id, title, created_at, updated_at
    """
    try:
        # 管理员或拥有 chat:read_all 权限的用户可以查看全部会话；
        # 普通用户仅能看到与自己 user_id 绑定的会话。
        can_read_all = current_user.is_superuser or current_user.has_permission("chat:read_all")
        user_id_str = None if can_read_all else str(current_user.id)
        conversations = get_conversations(
            limit=limit,
            offset=offset,
            user_id=user_id_str,
            can_read_all=can_read_all,
        )
        return {
            "conversations": conversations,
            "total": len(conversations),  # Note: For full total, would need COUNT query
        }
    except Exception as e:
        logger.exception(f"Error listing conversations: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.get("/conversations")
async def list_conversations_compat(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of conversations to return"),
    offset: int = Query(0, ge=0, description="Number of conversations to skip"),
):
    """
    兼容旧路径 /conversations，内部复用 /api/conversations 的实现。
    """
    return await list_conversations(limit=limit, offset=offset)


@app.get("/api/conversations/{thread_id}")
async def get_conversation(
    thread_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get a single conversation by thread_id.

    Args:
        thread_id: Unique identifier for the conversation thread
        current_user: Current authenticated user

    Returns:
        Conversation object with id, thread_id, title, messages, created_at, updated_at
    """
    try:
        # 管理员或拥有 chat:read_all 权限的用户可以查看全部会话；
        # 普通用户仅能看到与自己 user_id 绑定的会话。
        can_read_all = current_user.is_superuser or current_user.has_permission("chat:read_all")
        user_id_str = None if can_read_all else str(current_user.id)
        
        conversation = get_conversation_by_thread_id(thread_id, user_id_str, can_read_all)
        if conversation is None:
            raise HTTPException(status_code=404, detail=f"Conversation {thread_id} not found")
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting conversation {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.options("/api/conversations/{thread_id}")
async def options_conversation(thread_id: str):
    """Handle CORS preflight request for DELETE endpoint."""
    return Response(status_code=200)

@app.delete("/api/conversations/{thread_id}")
async def delete_conversation_endpoint(
    thread_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Delete a conversation by thread_id.

    Args:
        thread_id: Unique identifier for the conversation thread
        current_user: Current authenticated user

    Returns:
        Success message with deleted conversation ID
    """
    try:
        # 管理员或拥有 chat:delete_all 权限的用户可以删除全部会话；
        # 普通用户仅能删除与自己 user_id 绑定的会话。
        can_read_all = current_user.is_superuser or current_user.has_permission("chat:delete_all")
        user_id_str = None if can_read_all else str(current_user.id)
        
        # 先验证对话是否存在且用户有权限访问
        conversation = get_conversation_by_thread_id(thread_id, user_id_str, can_read_all)
        if conversation is None:
            raise HTTPException(status_code=404, detail=f"Conversation {thread_id} not found")
        
        success = delete_conversation(thread_id, user_id_str, can_read_all)
        if not success:
            raise HTTPException(status_code=404, detail=f"Conversation {thread_id} not found")
        return {"success": True, "thread_id": thread_id, "message": f"Conversation {thread_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting conversation {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/tools/execute", response_model=ToolExecuteResponse)
async def execute_tool(request: ToolExecuteRequest):
    """
    Execute a tool directly without going through the chat flow.
    
    This endpoint is independent of the conversation system and does not
    create or update any conversation records.
    """
    try:
        # Get tool from registry
        tool = TOOL_REGISTRY.get(request.tool_name)
        if tool is None:
            raise HTTPException(
                status_code=404,
                detail=f"Tool '{request.tool_name}' not found. Available tools: {list(TOOL_REGISTRY.keys())}"
            )
        
        # Map frontend parameters to backend tool parameters
        mapped_args = dict(request.arguments)
        if request.tool_name in PARAMETER_MAPPING:
            mapping = PARAMETER_MAPPING[request.tool_name]
            # Apply parameter name mappings
            for frontend_name, backend_name in mapping.items():
                if frontend_name in mapped_args:
                    mapped_args[backend_name] = mapped_args.pop(frontend_name)
            
            # Special handling for property_predictor_tool: convert properties array to string
            if request.tool_name == "property_predictor_tool" and "properties" in mapped_args:
                properties = mapped_args["properties"]
                if isinstance(properties, list):
                    mapped_args["properties"] = ",".join(str(p) for p in properties)
            
            # Remove unsupported parameters for visualize_molecules_tool
            if request.tool_name == "visualize_molecules_tool":
                mapped_args.pop("width", None)
                mapped_args.pop("height", None)
        
        # Execute tool with mapped arguments
        # Compress mapped_args to avoid logging large content (e.g., base64, result_json)
        compressed_args = {}
        for key, value in mapped_args.items():
            if isinstance(value, str):
                if len(value) > 200:
                    # Compress long strings (likely base64 or large JSON)
                    compressed_args[key] = f"<{key}> (length: {len(value)})"
                elif key in ["result_json", "file_base64", "pdf_file_base64"]:
                    # Always compress these fields
                    compressed_args[key] = f"<{key}> (length: {len(value)})"
                else:
                    compressed_args[key] = value
            elif isinstance(value, (list, dict)):
                # Compress large lists/dicts
                if len(str(value)) > 200:
                    compressed_args[key] = f"<{key}> ({type(value).__name__}, length: {len(value) if isinstance(value, list) else len(str(value))})"
                else:
                    compressed_args[key] = value
            else:
                compressed_args[key] = value
        logger.info(f"=== TOOL EXECUTION START ===")
        logger.info(f"Tool name: '{request.tool_name}'")
        logger.info(f"Mapped arguments: {compressed_args}")
        logger.info(f"=== TOOL EXECUTION START ===")
        
        # Tools are LangChain tools, so we need to invoke them
        # Use ainvoke for async tools, invoke for sync tools
        try:
            # Try async invoke first
            if hasattr(tool, 'ainvoke'):
                result = await tool.ainvoke(mapped_args)
            else:
                # Run sync tool in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: tool.invoke(mapped_args))
        except AttributeError:
            # Fallback to sync invoke
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: tool.invoke(mapped_args))
        
        logger.info(f"=== TOOL EXECUTION END ===")
        logger.info(f"Tool '{request.tool_name}' executed successfully")
        logger.info(f"=== TOOL EXECUTION END ===")
        return ToolExecuteResponse(result=str(result))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error executing tool '{request.tool_name}': {str(e)}")
        return ToolExecuteResponse(
            result="",
            error=f"工具执行失败: {str(e)}"
        )


@app.post("/api/sam-design/evaluate-molecule")
async def evaluate_molecule(
    request: dict,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """
    评估分子并生成评分和描述

    Request body:
    {
        "model": str,  # 模型名称（可选，如果不提供则使用basic模型）
        "smiles": str,
        "objective": str,
        "constraints": List[Dict],
        "properties": Optional[Dict]  # {HOMO, LUMO, DM}
    }
    """
    try:
        from src.llms.llm import get_llm_by_type, get_llm_by_model_name
        from langchain_core.messages import HumanMessage
        
        model_name = request.get("model")
        smiles = request.get("smiles")
        objective = request.get("objective", "")
        constraints = request.get("constraints", [])
        properties = request.get("properties", {})

        if not smiles:
            raise HTTPException(status_code=400, detail="SMILES is required")
        
        # 构建评估提示
        constraints_text = "\n".join([
            f"- {c.get('name', '')}: {c.get('value', '')}"
            for c in constraints if c.get('enabled', True)
        ])
        
        # 使用LLM同时预测性质和进行评估，合并为一次调用
        logger.info(f"=== EVALUATE MOLECULE API ===")
        logger.info(f"Using LLM to predict properties and evaluate molecule for SMILES: {smiles}")
        logger.info(f"Model: {model_name or 'basic (default)'}")
        if properties and any(properties.values()):
            logger.info(f"Note: Properties were provided but will be ignored, using LLM prediction instead")
        logger.info(f"=== EVALUATE MOLECULE API ===")
        
        # 合并性质预测和评估的prompt
        prompt = f"""你是一个SAM（自组装单分子层）分子设计评估专家。请根据以下信息，同时预测分子性质并评估分子：

**研究目标：**
{objective}

**约束条件：**
{constraints_text or '无'}

**分子SMILES：**
{smiles}

请完成以下任务：
1. 首先预测分子的以下性质：
   - HOMO（最高占据分子轨道能量，单位eV，数值范围通常在-15到-5之间）
   - LUMO（最低未占据分子轨道能量，单位eV，数值范围通常在-5到5之间）
   - DM（偶极矩，单位Debye，数值范围通常在0到10之间）

2. 然后根据预测的性质、研究目标和约束条件，评估分子并给出评分。

请使用JSON格式返回结果：
{{
  "properties": {{
    "HOMO": <HOMO值，数字>,
    "LUMO": <LUMO值，数字>,
    "DM": <偶极矩值，数字>
  }},
  "score": {{
    "total": <总评分，0-100的整数>,
    "surfaceAnchoring": <表面锚定强度评分，0-100的整数>,
    "energyLevel": <能级匹配评分，0-100的整数>,
    "packingDensity": <膜致密度和稳定性评分，0-100的整数>
  }},
  "description": "<分子的总体描述，2-3句话>",
  "explanation": "<系统解释，说明评分依据和分子特点，3-5句话>"
}}

请只返回JSON，不要包含其他文字。"""

        # 调用LLM（使用指定的模型或默认basic模型）
        if model_name:
            try:
                llm = get_llm_by_model_name(model_name)
            except Exception as e:
                logger.warning(f"Failed to get LLM by model name {model_name}, using basic: {e}")
                llm = get_llm_by_type("basic")
        else:
            llm = get_llm_by_type("basic")
        
        logger.info("Invoking LLM for combined property prediction and evaluation...")
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        
        # 解析响应
        response_text = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"LLM response length: {len(response_text)} characters")
        logger.info("=" * 80)
        logger.info("LLM RESPONSE (Combined):")
        logger.info("-" * 80)
        logger.info(response_text)
        logger.info("=" * 80)
        
        # 尝试提取JSON（支持嵌套的大括号）
        import re
        # 更强大的JSON提取：匹配平衡的大括号
        json_match = None
        brace_count = 0
        start_idx = -1
        for i, char in enumerate(response_text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx >= 0:
                    json_match = response_text[start_idx:i+1]
                    break
        
        if not json_match:
            # 回退到简单匹配
            simple_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
            if simple_match:
                json_match = simple_match.group()
        
        if json_match:
            try:
                result = json.loads(json_match)
                
                # 从合并的响应中提取properties和评估结果
                properties_data = result.get("properties", {})
                score_data = result.get("score", {})
                
                # 构建返回的properties
                predicted_properties = None
                if properties_data:
                    predicted_properties = {
                        "HOMO": properties_data.get("HOMO"),
                        "LUMO": properties_data.get("LUMO"),
                        "DM": properties_data.get("DM"),
                    }
                    logger.info(f"LLM predicted properties: {predicted_properties}")
                
                return {
                    "success": True,
                    "score": {
                        "total": score_data.get("total", 0),
                        "surfaceAnchoring": score_data.get("surfaceAnchoring"),
                        "energyLevel": score_data.get("energyLevel"),
                        "packingDensity": score_data.get("packingDensity"),
                    },
                    "description": result.get("description", ""),
                    "explanation": result.get("explanation", ""),
                    "properties": predicted_properties,  # 返回LLM预测的性质
                }
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse combined JSON: {e}")
                logger.warning(f"JSON match: {json_match[:200] if json_match else 'None'}...")
        
        # 如果JSON解析失败，返回默认值
        logger.warning("Failed to parse LLM response, returning default values")
        return {
            "success": True,
            "score": {
                "total": 70,
                "surfaceAnchoring": 70,
                "energyLevel": 70,
                "packingDensity": 70,
            },
            "description": "分子评估完成，但无法解析详细评分。",
            "explanation": response_text[:500],
            "properties": None,  # 解析失败时返回None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error evaluating molecule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to evaluate molecule: {str(e)}")


@app.post("/api/sam-design/generate-molecules")
async def generate_molecules(
    request: dict,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """
    使用LLM模型生成SAM分子
    
    Request body:
    {
        "model": str,  # 模型名称
        "objective": str,
        "constraints": List[Dict]
    }
    
    Returns:
    {
        "success": bool,
        "result": str  # LLM生成的文本结果，包含SMILES
    }
    """
    try:
        from src.llms.llm import get_llm_by_model_name
        from langchain_core.messages import HumanMessage
        
        model_name = request.get("model")
        objective = request.get("objective", "")
        constraints = request.get("constraints", [])
        
        if not model_name:
            raise HTTPException(status_code=400, detail="Model name is required")
        if not objective:
            raise HTTPException(status_code=400, detail="Objective is required")
        
        # 构建约束描述（去掉"启用"字样）
        constraints_text = "\n".join([
            f"- {c.get('name', '')}: {c.get('value', '')}"
            for c in constraints if c.get('enabled', True)
        ])
        
        # 构建生成分子的prompt（明确强调要严格按照研究目标中的数量要求）
        prompt = f"""你是一个SAM（自组装单分子层）分子设计专家。请根据以下研究目标和约束条件，生成SAM分子。

**研究目标：**
{objective}

**约束条件：**
{constraints_text or '无'}

**重要提示：**
- 请严格按照研究目标中指定的数量生成分子。如果研究目标要求生成1个分子，就只生成1个；如果要求生成多个，则按照要求的数量生成。
- 如果研究目标中没有明确指定数量，请生成1个分子。

每个分子应该：
1. 满足研究目标的要求
2. 符合给定的约束条件
3. 具有良好的表面锚定能力、能级匹配和膜致密度

请按照以下格式输出：
1. SMILES: <SMILES字符串>

如果研究目标要求生成多个分子，则按序号继续：
2. SMILES: <SMILES字符串>
3. SMILES: <SMILES字符串>
...

请只返回SMILES列表，每个SMILES一行，格式为 "序号. SMILES: <SMILES字符串>"。"""

        # 调用选择的LLM模型
        logger.info(f"Generating molecules with model: {model_name}")
        logger.info("=" * 80)
        logger.info("PROMPT (User Message):")
        logger.info("-" * 80)
        logger.info(prompt)
        logger.info("=" * 80)
        
        try:
            llm = get_llm_by_model_name(model_name)
            logger.info(f"LLM instance created successfully for model: {model_name}")
        except ValueError as e:
            logger.error(f"Failed to get LLM by model name '{model_name}': {e}")
            raise HTTPException(status_code=400, detail=f"Model '{model_name}' not found: {str(e)}")
        except Exception as e:
            logger.exception(f"Error creating LLM instance for model '{model_name}': {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create LLM instance: {str(e)}")
        
        # 调用LLM生成分子
        logger.info(f"Invoking LLM with prompt length: {len(prompt)} characters")
        try:
            # 检查LLM是否有system_message属性或方法
            messages = [HumanMessage(content=prompt)]
            
            # 如果有system message，也打印出来
            if hasattr(llm, 'system_message') and llm.system_message:
                logger.info("=" * 80)
                logger.info("SYSTEM MESSAGE:")
                logger.info("-" * 80)
                logger.info(str(llm.system_message))
                logger.info("=" * 80)
            
            response = await llm.ainvoke(messages)
            logger.info(f"LLM invocation successful for model: {model_name}")
        except Exception as e:
            logger.exception(f"Error invoking LLM for model '{model_name}': {e}")
            raise HTTPException(status_code=500, detail=f"Failed to invoke LLM: {str(e)}")
        
        # 获取响应文本
        response_text = response.content if hasattr(response, 'content') else str(response)
        logger.info("=" * 80)
        logger.info("LLM RESPONSE:")
        logger.info("-" * 80)
        logger.info(response_text)
        logger.info("=" * 80)
        logger.info(f"Response length: {len(response_text)} characters")
        
        return {
            "success": True,
            "result": response_text,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating molecules: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate molecules: {str(e)}")


@app.post("/api/sam-design/parse-objective")
async def parse_objective(
    request: dict,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """
    解析研究目标和约束为分子生成参数
    
    Request body:
    {
        "objective": str,
        "constraints": List[Dict]
    }
    
    Returns:
    {
        "scaffold_condition": str,
        "anchoring_group": str,
        "gen_size": int
    }
    """
    try:
        from src.llms.llm import get_llm_by_type
        from langchain_core.messages import HumanMessage
        
        objective = request.get("objective", "")
        constraints = request.get("constraints", [])
        
        if not objective:
            raise HTTPException(status_code=400, detail="Objective is required")
        
        # 构建约束描述（去掉"启用"字样）
        constraints_text = "\n".join([
            f"- {c.get('name', '')}: {c.get('value', '')}"
            for c in constraints if c.get('enabled', True)
        ])
        
        prompt = f"""你是一个SAM分子设计专家。请根据以下研究目标和约束条件，生成分子生成所需的参数。

**研究目标：**
{objective}

**约束条件：**
{constraints_text or '无'}

请提供以下参数（使用JSON格式）：
{{
  "scaffold_condition": "<骨架SMILES字符串，多个用逗号分隔，例如：c1ccccc1,c1ccc2c(c1)[nH]c1ccccc12>",
  "anchoring_group": "<锚定基团SMILES字符串，例如：O=P(O)(O) 表示磷酸基团>",
  "gen_size": <要生成的分子数量，整数，建议10-20>
}}

请只返回JSON，不要包含其他文字。如果无法确定具体参数，使用合理的默认值。"""

        # 调用LLM
        llm = get_llm_by_type("basic")
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        
        # 解析响应
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # 尝试提取JSON（支持嵌套的大括号）
        json_match = None
        brace_count = 0
        start_idx = -1
        for i, char in enumerate(response_text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx >= 0:
                    json_match = response_text[start_idx:i+1]
                    break
        
        if not json_match:
            # 回退到简单匹配
            simple_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
            if simple_match:
                json_match = simple_match.group()
        
        if json_match:
            try:
                result = json.loads(json_match)
                return {
                    "success": True,
                    "scaffold_condition": result.get("scaffold_condition", "c1ccccc1,c1ccc2c(c1)[nH]c1ccccc12"),
                    "anchoring_group": result.get("anchoring_group", "O=P(O)(O)"),
                    "gen_size": result.get("gen_size", 10),
                }
            except json.JSONDecodeError:
                pass
        
        # 如果JSON解析失败，返回默认值
        logger.warning(f"Failed to parse objective, using defaults. Response: {response_text[:200]}")
        return {
            "success": True,
            "scaffold_condition": "c1ccccc1,c1ccc2c(c1)[nH]c1ccccc12",
            "anchoring_group": "O=P(O)(O)",
            "gen_size": 10,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error parsing objective: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to parse objective: {str(e)}")


@app.post("/api/sam-design/history")
async def save_design_history(
    request: dict,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    保存SAM设计历史记录
    
    Request body:
    {
        "name": str,  # 历史记录名称（可选，如果不提供则自动生成）
        "objective": Dict,
        "constraints": List[Dict],
        "executionResult": Dict,
        "molecules": List[Dict]
    }
    """
    try:
        from src.server.sam_design.db import save_design_history
        from uuid import UUID
        
        name = request.get("name")
        if not name:
            # 自动生成名称：基于objective的前30个字符 + 时间戳
            objective_text = request.get("objective", {}).get("text", "")
            if objective_text:
                name = objective_text[:30] + (objective_text[30:] and "...")
            else:
                name = f"SAM设计-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        objective = request.get("objective", {})
        constraints = request.get("constraints", [])
        execution_result = request.get("executionResult", {})
        molecules = request.get("molecules", [])
        
        if not objective or not execution_result:
            raise HTTPException(status_code=400, detail="Objective and executionResult are required")
        
        logger.info(f"Saving design history for user {current_user.id}, name: {name}, molecules count: {len(molecules)}")
        
        history_id = save_design_history(
            user_id=current_user.id,
            name=name,
            objective=objective,
            constraints=constraints,
            execution_result=execution_result,
            molecules=molecules,
        )
        
        logger.info(f"Design history saved successfully with ID: {history_id}")
        
        return {
            "success": True,
            "id": str(history_id),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error saving design history: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save design history: {str(e)}")


@app.get("/api/sam-design/history")
async def get_design_history_list(
    limit: int = 100,
    offset: int = 0,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    获取当前用户的设计历史记录列表
    """
    try:
        from src.server.sam_design.db import get_design_history_list
        
        history_list = get_design_history_list(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        
        # 转换UUID和datetime为字符串
        result = []
        for item in history_list:
            result.append({
                "id": str(item["id"]),
                "name": item["name"],
                "createdAt": item["created_at"].isoformat() if isinstance(item.get("created_at"), datetime) else item.get("created_at"),
                "moleculeCount": item.get("molecule_count", 0),
            })
        
        return {
            "success": True,
            "history": result,
        }
        
    except Exception as e:
        logger.exception(f"Error getting design history list: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get design history list: {str(e)}")


@app.get("/api/sam-design/history/{history_id}")
async def get_design_history(
    history_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    获取单个设计历史记录
    """
    try:
        from src.server.sam_design.db import get_design_history
        from uuid import UUID
        
        history = get_design_history(
            history_id=UUID(history_id),
            user_id=current_user.id,
        )
        
        if not history:
            raise HTTPException(status_code=404, detail="History record not found")
        
        return {
            "success": True,
            "history": {
                "id": str(history["id"]),
                "name": history["name"],
                "createdAt": history["created_at"],
                "objective": history["objective"],
                "constraints": history["constraints"],
                "executionResult": history["execution_result"],
                "molecules": history["molecules"],
            },
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting design history: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get design history: {str(e)}")


@app.delete("/api/sam-design/history/{history_id}")
async def delete_design_history(
    history_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    删除设计历史记录
    """
    try:
        from src.server.sam_design.db import delete_design_history
        from uuid import UUID
        
        deleted = delete_design_history(
            history_id=UUID(history_id),
            user_id=current_user.id,
        )
        
        if not deleted:
            raise HTTPException(status_code=404, detail="History record not found")
        
        return {
            "success": True,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting design history: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete design history: {str(e)}")


# Data Extraction Records API
@app.post("/api/data-extraction/records", response_model=DataExtractionRecordResponse)
async def save_extraction_record(request: DataExtractionRecordRequest):
    """Save or update a data extraction record."""
    try:
        record_manager = get_record_manager()
        task_id = record_manager.save_extraction_record(
            task_name=request.task_name,
            extraction_type=request.extraction_type,
            extraction_step=request.extraction_step,
            file_name=request.file_name,
            file_size=request.file_size,
            file_base64=request.file_base64,
            pdf_url=request.pdf_url,
            model_name=request.model_name,
            categories=request.categories,
            selected_categories=request.selected_categories,
            table_data=request.table_data,
            result_json=request.result_json,
            metadata=request.metadata,
            record_id=request.record_id,
            task_id=request.task_id,
        )
        
        if not task_id:
            raise HTTPException(status_code=500, detail="Failed to save extraction record")
        
        # Get the saved record
        record = record_manager.get_extraction_record_by_id(task_id, task_id=task_id)
        if not record:
            raise HTTPException(status_code=404, detail="Record not found after saving")
        
        return DataExtractionRecordResponse(**record)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error saving extraction record: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save extraction record: {str(e)}")


@app.get("/api/data-extraction/records", response_model=DataExtractionRecordListResponse)
async def get_extraction_records(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    extraction_type: Optional[str] = Query(None, description="Filter by extraction type"),
):
    """Get list of data extraction records."""
    try:
        record_manager = get_record_manager()
        records = record_manager.get_extraction_records(
            limit=limit,
            offset=offset,
            extraction_type=extraction_type,
        )
        
        # Get total count (simplified - in production, you'd want a separate count query)
        total = len(records) if len(records) < limit else limit + offset + 1
        
        record_responses = [DataExtractionRecordResponse(**record) for record in records]
        return DataExtractionRecordListResponse(
            records=record_responses,
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.exception(f"Error getting extraction records: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get extraction records: {str(e)}")


@app.get("/api/data-extraction/records/{record_id}", response_model=DataExtractionRecordResponse)
async def get_extraction_record(record_id: str):
    """Get a single data extraction record by ID."""
    try:
        record_manager = get_record_manager()
        record = record_manager.get_extraction_record_by_id(record_id)
        
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        return DataExtractionRecordResponse(**record)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting extraction record: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get extraction record: {str(e)}")


@app.delete("/api/data-extraction/records/{record_id}")
async def delete_extraction_record(record_id: str):
    """Delete a data extraction record."""
    try:
        record_manager = get_record_manager()
        deleted = record_manager.delete_extraction_record(record_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Record not found")
        
        return {"success": True, "message": "Record deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting extraction record: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete extraction record: {str(e)}")


# ==================== Workflow API Endpoints ====================

@app.post("/api/workflow/save", response_model=WorkflowConfigResponse)
async def save_workflow(request: WorkflowConfigRequest):
    """保存工作流配置"""
    try:
        # 验证工作流名称不能为空
        if not request.name or not request.name.strip():
            raise HTTPException(status_code=400, detail="Workflow name cannot be empty")
        
        storage = get_workflow_storage()
        workflow_id = storage.save(request)
        
        # 加载保存的工作流
        workflow_data = storage.load(workflow_id)
        if not workflow_data:
            raise HTTPException(status_code=500, detail="Failed to load saved workflow")
        
        return WorkflowConfigResponse(**workflow_data)
    except HTTPException:
        raise
    except ValidationError as e:
        # Pydantic验证错误，返回422
        logger.error(f"Validation error saving workflow: {e.errors()}")
        raise HTTPException(status_code=422, detail=f"Validation error: {e.errors()}")
    except Exception as e:
        logger.exception(f"Error saving workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save workflow: {str(e)}")


@app.post("/api/workflow/from-plan", response_model=WorkflowConfigResponse)
async def generate_workflow_from_plan(plan: dict, thread_id: Optional[str] = Query(None)):
    """从Plan生成工作流配置
    
    Args:
        plan: Plan字典
        thread_id: 可选的thread_id，用于绑定工作流到对话线程
    """
    try:
        from src.workflow.plan_converter import convert_plan_to_workflow
        
        storage = get_workflow_storage()
        
        # 如果提供了thread_id，先检查是否已有工作流绑定到这个thread_id
        if thread_id:
            existing_workflow = storage.find_by_thread_id(thread_id)
            if existing_workflow:
                logger.info(f"Found existing workflow {existing_workflow.get('id')} for thread_id {thread_id}, returning existing workflow")
                return WorkflowConfigResponse(**existing_workflow)
        
        # 转换Plan为工作流配置
        workflow_config = convert_plan_to_workflow(plan)
        
        # 验证工作流名称不能为空
        if not workflow_config.name or not workflow_config.name.strip():
            raise HTTPException(status_code=400, detail="Generated workflow name cannot be empty")
        
        # 保存工作流，绑定thread_id
        workflow_id = storage.save(workflow_config, thread_id=thread_id)
        
        # 加载保存的工作流
        workflow_data = storage.load(workflow_id)
        if not workflow_data:
            raise HTTPException(status_code=500, detail="Failed to load saved workflow")
        
        return WorkflowConfigResponse(**workflow_data)
    except ValueError as e:
        logger.error(f"Invalid plan format: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid plan format: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating workflow from plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate workflow from plan: {str(e)}")


@app.get("/api/workflow/list", response_model=WorkflowListResponse)
async def list_workflows():
    """列出所有工作流"""
    try:
        storage = get_workflow_storage()
        workflows = storage.list()
        return WorkflowListResponse(workflows=workflows)
    except Exception as e:
        logger.exception(f"Error listing workflows: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list workflows: {str(e)}")


@app.get("/api/workflow/by-thread/{thread_id}", response_model=WorkflowConfigResponse)
async def get_workflow_by_thread_id(thread_id: str):
    """根据thread_id查找工作流
    
    Args:
        thread_id: 对话线程ID
        
    Returns:
        工作流配置
    """
    try:
        storage = get_workflow_storage()
        workflow_data = storage.find_by_thread_id(thread_id)
        
        if not workflow_data:
            raise HTTPException(status_code=404, detail=f"Workflow not found for thread_id: {thread_id}")
        
        return WorkflowConfigResponse(**workflow_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting workflow by thread_id: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow by thread_id: {str(e)}")


@app.get("/api/workflow/tools", response_model=List[ToolDefinition])
async def get_workflow_tools():
    """获取可用工具列表（用于工作流节点配置）"""
    try:
        tools = []
        
        # 检查 TOOL_REGISTRY 是否为空
        if not TOOL_REGISTRY:
            logger.warning("TOOL_REGISTRY is empty. No tools available for workflow.")
            return []
        
        for tool_name, tool_func in TOOL_REGISTRY.items():
            try:
                # 尝试获取工具的 schema
                tool_schema = None
                if hasattr(tool_func, "args_schema"):
                    schema = tool_func.args_schema
                    if hasattr(schema, "model_json_schema"):
                        tool_schema = schema.model_json_schema()
                    elif hasattr(schema, "schema"):
                        tool_schema = schema.schema()
                
                # 获取工具描述
                description = ""
                if hasattr(tool_func, "description"):
                    description = tool_func.description
                elif hasattr(tool_func, "__doc__"):
                    description = tool_func.__doc__ or ""
                
                # 提取参数
                parameters = []
                if tool_schema and "properties" in tool_schema:
                    for param_name, param_info in tool_schema["properties"].items():
                        required = param_name in tool_schema.get("required", [])
                        parameters.append({
                            "name": param_name,
                            "type": param_info.get("type", "string"),
                            "description": param_info.get("description", ""),
                            "required": required,
                            "default": param_info.get("default"),
                            "enum": param_info.get("enum"),
                        })
                
                tools.append(ToolDefinition(
                    name=tool_name,
                    description=description,
                    parameters=parameters,
                ))
            except Exception as tool_error:
                # 如果某个工具处理失败，记录错误但继续处理其他工具
                logger.warning(f"Failed to process tool '{tool_name}': {str(tool_error)}")
        
        return tools
    except Exception as e:
        logger.exception(f"Error getting workflow tools: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get tools: {str(e)}")


@app.get("/api/workflow/{workflow_id}", response_model=WorkflowConfigResponse)
async def get_workflow(workflow_id: str):
    """获取工作流配置"""
    try:
        storage = get_workflow_storage()
        workflow_data = storage.load(workflow_id)
        
        if not workflow_data:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        # 调试：记录执行结果字段（在转换为 Pydantic 模型之前）
        logger.info(f"[API] Loading workflow {workflow_id}: has_executed={workflow_data.get('has_executed')}, has_execution_result={bool(workflow_data.get('execution_result'))}, execution_result_type={type(workflow_data.get('execution_result'))}")
        
        # 确保 execution_result 和 has_executed 字段被正确传递
        # 如果 workflow_data 中有这些字段，确保它们被包含在响应中
        try:
            response = WorkflowConfigResponse(**workflow_data)
            # 调试：记录转换后的数据（使用 model_dump 查看序列化后的数据）
            response_dict = response.model_dump(by_alias=False, exclude_none=False)
            logger.info(f"[API] WorkflowConfigResponse created: has_executed={response.has_executed}, has_execution_result={bool(response.execution_result)}")
            logger.info(f"[API] WorkflowConfigResponse dict keys: {list(response_dict.keys())}, has_executed in dict: {'has_executed' in response_dict}, execution_result in dict: {'execution_result' in response_dict}")
            return response
        except Exception as e:
            logger.error(f"[API] Error creating WorkflowConfigResponse: {e}, workflow_data keys: {list(workflow_data.keys())}")
            raise
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error loading workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load workflow: {str(e)}")


@app.post("/api/workflow/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(request: WorkflowExecuteRequest, current_user: Optional[CurrentUser] = Depends(get_current_user_optional)):
    """执行工作流（创建运行记录，由 worker 异步执行）"""
    try:
        from src.server.workflow.executor import get_workflow_executor
        from src.server.workflow.db import get_db_connection
        from uuid import UUID
        
        executor = get_workflow_executor()
        
        # 合并执行请求中的 inputs 和 files
        workflow_inputs = request.inputs or {}
        if request.files:
            workflow_inputs["files"] = request.files
        
        # 获取工作流的当前发布版本
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT current_release_id, id as workflow_id
                    FROM workflows
                    WHERE id = %s
                """, (UUID(request.workflow_id),))
                workflow = cursor.fetchone()
                if not workflow:
                    raise ValueError(f"Workflow {request.workflow_id} not found")
                
                if not workflow['current_release_id']:
                    raise ValueError(f"Workflow {request.workflow_id} has no release")
                
                release_id = workflow['current_release_id']
                workflow_id = workflow['workflow_id']
                created_by = current_user.id if current_user else UUID('00000000-0000-0000-0000-000000000000')
            
            # 创建运行记录
            run_id = await executor.create_run(
                workflow_id=workflow_id,
                release_id=release_id,
            inputs=workflow_inputs,
                created_by=created_by,
        )
            
            return WorkflowExecuteResponse(
                success=True,
                result={"run_id": str(run_id)},
            )
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating workflow run: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create workflow run: {str(e)}")


@app.post("/api/workflow/execute/stream")
async def execute_workflow_stream(request: WorkflowExecuteRequest, current_user: Optional[CurrentUser] = Depends(get_current_user_optional)):
    """流式执行工作流，实时返回节点状态更新"""
    try:
        from src.server.workflow.executor import get_workflow_executor
        from src.server.workflow.db import get_db_connection
        from uuid import UUID
        
        executor = get_workflow_executor()
        
        # 合并执行请求中的 inputs 和 files
        workflow_inputs = request.inputs or {}
        if request.files:
            workflow_inputs["files"] = request.files
        
        # 获取工作流的当前发布版本
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT current_release_id, id as workflow_id
                    FROM workflows
                    WHERE id = %s
                """, (UUID(request.workflow_id),))
                workflow = cursor.fetchone()
                if not workflow:
                    raise ValueError(f"Workflow {request.workflow_id} not found")
                
                if not workflow['current_release_id']:
                    raise ValueError(f"Workflow {request.workflow_id} has no release")
                
                release_id = workflow['current_release_id']
                workflow_id = workflow['workflow_id']
                created_by = current_user.id if current_user else UUID('00000000-0000-0000-0000-000000000000')
            
            # 创建运行记录
            run_id = await executor.create_run(
                workflow_id=workflow_id,
                release_id=release_id,
                inputs=workflow_inputs,
                created_by=created_by,
            )
        finally:
            conn.close()
        
        # 返回流式执行
        return StreamingResponse(
            executor.execute_run_stream(run_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error executing workflow stream: {str(e)}")
        # 发送错误事件
        error_message = str(e)
        async def error_stream():
            event_data = {
                "type": "error",
                "success": False,
                "error": error_message,
            }
            yield f"data: {json.dumps(event_data)}\n\n"
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
        )


@app.post("/api/workflow/node/execute", response_model=NodeExecuteResponse)
async def execute_node(request: NodeExecuteRequest):
    """单独执行节点"""
    try:
        from src.workflow.executor import get_workflow_executor
        executor = get_workflow_executor()
        
        # 如果提供了 node_config，直接执行（不需要工作流 ID）
        if request.node_config:
            result = await executor.execute_node_direct(
                node_type=request.node_config.get("type", ""),
                node_data=request.node_config.get("data", {}),
                inputs=request.inputs,
            )
        elif request.workflow_id:
            # 从保存的工作流中执行节点
            result = await executor.execute_node(
                workflow_id=request.workflow_id,
                node_id=request.node_id,
                inputs=request.inputs,
            )
        else:
            raise ValueError("Either workflow_id or node_config must be provided")
        
        return NodeExecuteResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error executing node: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to execute node: {str(e)}")


# ============= 工作流管理端点 =============

def check_workflow_permission(
    workflow: dict,
    current_user: Optional[CurrentUser],
    require_auth: bool = True,
) -> bool:
    """
    检查用户是否有权限访问工作流
    
    Args:
        workflow: 工作流字典
        current_user: 当前用户
        require_auth: 是否要求必须登录（默认True）
        
    Returns:
        是否有权限访问
        
    Raises:
        HTTPException: 如果没有权限或未登录
    """
    if not current_user:
        if require_auth:
            raise HTTPException(status_code=401, detail="Authentication required")
        return False
    
    # 超级管理员可以访问所有工作流
    if current_user.is_superuser:
        return True
    
    permission_level = current_user.data_permission_level
    
    # 确保 UUID 比较的正确性：统一转换为 UUID 对象进行比较
    from uuid import UUID as UUIDType
    
    # 获取工作流的 created_by（用户ID），这是用户级别隔离的关键字段
    workflow_created_by = workflow.get("created_by")
    if workflow_created_by:
        if isinstance(workflow_created_by, str):
            workflow_created_by = UUIDType(workflow_created_by)
        elif not isinstance(workflow_created_by, UUIDType):
            workflow_created_by = UUIDType(str(workflow_created_by))
    
    if permission_level == "self":
        # 只能访问自己创建的工作流（用户级别隔离：基于 created_by 字段）
        has_permission = (workflow_created_by == current_user.id if workflow_created_by else False)
    elif permission_level == "department":
        # 可以访问同部门的工作流或自己创建的
        if current_user.department_id:
            workflow_dept_id = workflow.get("department_id")
            if workflow_dept_id:
                if isinstance(workflow_dept_id, str):
                    workflow_dept_id = UUIDType(workflow_dept_id)
                elif not isinstance(workflow_dept_id, UUIDType):
                    workflow_dept_id = UUIDType(str(workflow_dept_id))
            has_permission = (
                (workflow_dept_id == current_user.department_id if workflow_dept_id else False) or
                (workflow_created_by == current_user.id if workflow_created_by else False)
            )
        else:
            # 如果没有部门，只能看到自己创建的（用户级别隔离）
            has_permission = (workflow_created_by == current_user.id if workflow_created_by else False)
    elif permission_level == "organization":
        # 可以访问同组织的工作流或自己创建的
        if current_user.organization_id:
            workflow_org_id = workflow.get("organization_id")
            if workflow_org_id:
                if isinstance(workflow_org_id, str):
                    workflow_org_id = UUIDType(workflow_org_id)
                elif not isinstance(workflow_org_id, UUIDType):
                    workflow_org_id = UUIDType(str(workflow_org_id))
            has_permission = (
                (workflow_org_id == current_user.organization_id if workflow_org_id else False) or
                (workflow_created_by == current_user.id if workflow_created_by else False)
            )
        else:
            # 如果没有组织，只能看到自己创建的（用户级别隔离）
            has_permission = (workflow_created_by == current_user.id if workflow_created_by else False)
    else:  # permission_level == "all"
        # 可以访问所有工作流
        has_permission = True
    
    if not has_permission:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this workflow"
        )
    
    return True


@app.get("/api/workflows")
async def list_workflows_from_db(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """从数据库获取工作流列表"""
    try:
        from src.server.workflow.db import get_db_connection
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            query = """
                SELECT w.*, u.username as created_by_name
                FROM workflows w
                LEFT JOIN users u ON w.created_by = u.id
                WHERE 1=1
            """
            params = []
            
            # 权限过滤：根据用户的 data_permission_level 进行过滤
            if current_user:
                # 超级管理员可以看到所有工作流
                if not current_user.is_superuser:
                    permission_level = current_user.data_permission_level
                    
                    if permission_level == "self":
                        # 只能看到自己创建的工作流
                        query += " AND w.created_by = %s"
                        params.append(current_user.id)
                    elif permission_level == "department":
                        # 可以看到同部门的工作流
                        if current_user.department_id:
                            query += " AND (w.department_id = %s OR w.created_by = %s)"
                            params.extend([current_user.department_id, current_user.id])
                        else:
                            # 如果没有部门，只能看到自己创建的
                            query += " AND w.created_by = %s"
                            params.append(current_user.id)
                    elif permission_level == "organization":
                        # 可以看到同组织的工作流
                        if current_user.organization_id:
                            query += " AND (w.organization_id = %s OR w.created_by = %s)"
                            params.extend([current_user.organization_id, current_user.id])
                        else:
                            # 如果没有组织，只能看到自己创建的
                            query += " AND w.created_by = %s"
                            params.append(current_user.id)
                    # permission_level == "all" 的情况不需要额外过滤，可以看到所有工作流
            else:
                # 未登录用户不能看到任何工作流
                query += " AND 1=0"
            
            if status:
                query += " AND w.status = %s"
                params.append(status)
            
            query += " ORDER BY w.updated_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                workflows = []
                for row in rows:
                    workflow_dict = {}
                    for key, value in row.items():
                        # Convert UUID to string
                        if isinstance(value, UUID):
                            workflow_dict[key] = str(value)
                        # Convert datetime to ISO string
                        elif isinstance(value, datetime):
                            workflow_dict[key] = value.isoformat()
                        else:
                            workflow_dict[key] = value
                    workflows.append(workflow_dict)
            
            # 获取总数（也需要应用相同的权限过滤）
            count_query = """
                SELECT COUNT(*) as total
                FROM workflows w
                WHERE 1=1
            """
            count_params = []
            
            # 应用相同的权限过滤
            if current_user:
                if not current_user.is_superuser:
                    permission_level = current_user.data_permission_level
                    
                    if permission_level == "self":
                        count_query += " AND w.created_by = %s"
                        count_params.append(current_user.id)
                    elif permission_level == "department":
                        if current_user.department_id:
                            count_query += " AND (w.department_id = %s OR w.created_by = %s)"
                            count_params.extend([current_user.department_id, current_user.id])
                        else:
                            count_query += " AND w.created_by = %s"
                            count_params.append(current_user.id)
                    elif permission_level == "organization":
                        if current_user.organization_id:
                            count_query += " AND (w.organization_id = %s OR w.created_by = %s)"
                            count_params.extend([current_user.organization_id, current_user.id])
                        else:
                            count_query += " AND w.created_by = %s"
                            count_params.append(current_user.id)
            else:
                count_query += " AND 1=0"
            
            if status:
                count_query += " AND w.status = %s"
                count_params.append(status)
            
            with conn.cursor() as cursor:
                cursor.execute(count_query, count_params)
                total = cursor.fetchone()['total']
            
            return {
                "workflows": workflows,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Error getting workflows: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflows: {str(e)}")


@app.post("/api/workflows")
async def create_workflow(
    request: CreateWorkflowRequest,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """创建工作流"""
    try:
        from src.server.workflow.db import get_db_connection, create_workflow as db_create_workflow
        from uuid import UUID
        
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        conn = get_db_connection()
        try:
            workflow_id = db_create_workflow(
                conn,
                name=request.name,
                description=request.description,
                created_by=UUID(str(current_user.id)),
                status=request.status,
                organization_id=current_user.organization_id,
                department_id=current_user.department_id,
            )
            conn.commit()
            
            # 获取创建的工作流
            from src.server.workflow.db import get_workflow
            workflow = get_workflow(conn, workflow_id)
            
            if workflow:
                # Convert UUID and datetime to string
                workflow_dict = {}
                for key, value in workflow.items():
                    if isinstance(value, UUID):
                        workflow_dict[key] = str(value)
                    elif isinstance(value, datetime):
                        workflow_dict[key] = value.isoformat()
                    else:
                        workflow_dict[key] = value
                return workflow_dict
            else:
                raise HTTPException(status_code=500, detail="Failed to retrieve created workflow")
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {str(e)}")


@app.get("/api/workflows/{workflow_id}")
async def get_workflow_by_id(
    workflow_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取工作流详情"""
    try:
        from src.server.workflow.db import get_db_connection, get_workflow
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            workflow = get_workflow(conn, UUID(workflow_id))
            
            if not workflow:
                raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
            
            # 权限检查
            check_workflow_permission(workflow, current_user)
            
            # Convert UUID and datetime to string
            workflow_dict = {}
            for key, value in workflow.items():
                if isinstance(value, UUID):
                    workflow_dict[key] = str(value)
                elif isinstance(value, datetime):
                    workflow_dict[key] = value.isoformat()
                else:
                    workflow_dict[key] = value
            
            return workflow_dict
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow: {str(e)}")


@app.put("/api/workflows/{workflow_id}")
async def update_workflow_by_id(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """更新工作流"""
    try:
        from src.server.workflow.db import get_db_connection, update_workflow, get_workflow
        from uuid import UUID
        
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        conn = get_db_connection()
        try:
            # 先获取工作流，检查权限
            from src.server.workflow.db import get_workflow
            workflow = get_workflow(conn, UUID(workflow_id))
            
            if not workflow:
                raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
            
            # 权限检查
            check_workflow_permission(workflow, current_user)
            
            success = update_workflow(
                conn,
                UUID(workflow_id),
                name=request.name,
                description=request.description,
                status=request.status,
            )
            
            conn.commit()
            
            # 获取更新后的工作流
            workflow = get_workflow(conn, UUID(workflow_id))
            
            if workflow:
                # Convert UUID and datetime to string
                workflow_dict = {}
                for key, value in workflow.items():
                    if isinstance(value, UUID):
                        workflow_dict[key] = str(value)
                    elif isinstance(value, datetime):
                        workflow_dict[key] = value.isoformat()
                    else:
                        workflow_dict[key] = value
                return workflow_dict
            else:
                raise HTTPException(status_code=500, detail="Failed to retrieve updated workflow")
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update workflow: {str(e)}")


@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow_by_id(
    workflow_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """删除工作流"""
    try:
        from src.server.workflow.db import get_db_connection, delete_workflow
        from uuid import UUID
        
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        conn = get_db_connection()
        try:
            # 先获取工作流，检查权限
            from src.server.workflow.db import get_workflow
            workflow = get_workflow(conn, UUID(workflow_id))
            
            if not workflow:
                raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
            
            # 权限检查
            check_workflow_permission(workflow, current_user)
            
            success = delete_workflow(conn, UUID(workflow_id))
            
            conn.commit()
            return {"success": True, "message": f"Workflow {workflow_id} deleted"}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete workflow: {str(e)}")


@app.post("/api/workflows/{workflow_id}/draft")
async def save_workflow_draft(
    workflow_id: str,
    request: SaveDraftRequest,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """保存工作流草稿"""
    try:
        from src.server.workflow.db import get_db_connection, save_draft, get_draft, get_workflow, create_workflow
        from uuid import UUID
        
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        conn = get_db_connection()
        try:
            workflow_uuid = UUID(workflow_id)
            
            # 检查工作流是否存在，如果不存在则先创建
            workflow = get_workflow(conn, workflow_uuid)
            if not workflow:
                # 工作流不存在，先创建一个默认的工作流
                # 从草稿的 graph 中提取工作流名称（如果有的话）
                workflow_name = request.graph.get("name") or f"Workflow {workflow_id[:8]}"
                workflow_description = request.graph.get("description")
                
                # 使用指定的 workflow_id 创建工作流
                created_id = create_workflow(
                    conn,
                    name=workflow_name,
                    description=workflow_description,
                    created_by=UUID(str(current_user.id)),
                    status='draft',
                    organization_id=current_user.organization_id,
                    department_id=current_user.department_id,
                    workflow_id=workflow_uuid,  # 使用指定的 workflow_id
                )
                # 重新获取工作流以进行权限检查
                workflow = get_workflow(conn, workflow_uuid)
                if not workflow:
                    raise HTTPException(status_code=500, detail="Failed to create workflow")
            else:
                # 工作流存在，检查权限
                check_workflow_permission(workflow, current_user)
            
            draft_id = save_draft(
                conn,
                workflow_uuid,
                graph=request.graph,
                created_by=UUID(str(current_user.id)),
                is_autosave=request.is_autosave,
            )
            conn.commit()
            
            # 获取保存的草稿
            draft = get_draft(conn, UUID(workflow_id))
            
            if draft:
                # Convert UUID and datetime to string
                draft_dict = {}
                for key, value in draft.items():
                    if isinstance(value, UUID):
                        draft_dict[key] = str(value)
                    elif isinstance(value, datetime):
                        draft_dict[key] = value.isoformat()
                    else:
                        draft_dict[key] = value
                return draft_dict
            else:
                raise HTTPException(status_code=500, detail="Failed to retrieve saved draft")
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error saving draft: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save draft: {str(e)}")


@app.get("/api/workflows/{workflow_id}/draft")
async def get_workflow_draft(
    workflow_id: str,
    version: Optional[int] = None,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取工作流草稿"""
    try:
        from src.server.workflow.db import get_db_connection, get_draft
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            draft = get_draft(conn, UUID(workflow_id), version=version)
            
            if not draft:
                raise HTTPException(status_code=404, detail=f"Draft not found for workflow {workflow_id}")
            
            # Convert UUID and datetime to string
            draft_dict = {}
            for key, value in draft.items():
                if isinstance(value, UUID):
                    draft_dict[key] = str(value)
                elif isinstance(value, datetime):
                    draft_dict[key] = value.isoformat()
                else:
                    draft_dict[key] = value
            
            return draft_dict
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting draft: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get draft: {str(e)}")


@app.delete("/api/workflows/{workflow_id}/draft")
async def delete_workflow_draft(
    workflow_id: str,
    version: Optional[int] = None,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """删除工作流草稿"""
    try:
        from src.server.workflow.db import get_db_connection, delete_draft
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            success = delete_draft(conn, UUID(workflow_id), version=version)
            
            if not success:
                raise HTTPException(status_code=404, detail=f"Draft not found for workflow {workflow_id}")
            
            conn.commit()
            return {"success": True, "message": f"Draft deleted for workflow {workflow_id}"}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting draft: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete draft: {str(e)}")


@app.post("/api/workflows/{workflow_id}/release")
async def create_workflow_release(
    workflow_id: str,
    request: CreateReleaseRequest,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """发布工作流"""
    try:
        from src.server.workflow.db import get_db_connection, create_release
        from uuid import UUID
        
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        conn = get_db_connection()
        try:
            release_id = create_release(
                conn,
                UUID(workflow_id),
                UUID(request.source_draft_id),
                spec=request.spec,
                checksum=request.checksum,
                created_by=UUID(str(current_user.id)),
            )
            conn.commit()
            
            # 获取创建的发布
            from src.server.workflow.db import get_release
            release = get_release(conn, release_id)
            
            if release:
                # Convert UUID and datetime to string
                release_dict = {}
                for key, value in release.items():
                    if isinstance(value, UUID):
                        release_dict[key] = str(value)
                    elif isinstance(value, datetime):
                        release_dict[key] = value.isoformat()
                    else:
                        release_dict[key] = value
                return release_dict
            else:
                raise HTTPException(status_code=500, detail="Failed to retrieve created release")
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating release: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create release: {str(e)}")


@app.get("/api/workflows/{workflow_id}/releases")
async def get_workflow_releases(
    workflow_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取工作流的发布列表"""
    try:
        from src.server.workflow.db import get_db_connection, list_releases
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            releases = list_releases(conn, UUID(workflow_id))
            
            # Convert UUID and datetime to string
            releases_list = []
            for release in releases:
                release_dict = {}
                for key, value in release.items():
                    if isinstance(value, UUID):
                        release_dict[key] = str(value)
                    elif isinstance(value, datetime):
                        release_dict[key] = value.isoformat()
                    else:
                        release_dict[key] = value
                releases_list.append(release_dict)
            
            return {"releases": releases_list}
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Error getting releases: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get releases: {str(e)}")


# ============= 运行管理端点 =============

@app.get("/api/workflows/{workflow_id}/runs")
async def get_workflow_runs(
    workflow_id: str,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取工作流的运行列表"""
    try:
        from src.server.workflow.db import get_db_connection
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            query = """
                SELECT wr.*, u.username as created_by_name
                FROM workflow_runs wr
                LEFT JOIN users u ON wr.created_by = u.id
                WHERE wr.workflow_id = %s
            """
            params = [UUID(workflow_id)]
            
            if status:
                query += " AND wr.status = %s"
                params.append(status)
            
            query += " ORDER BY wr.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                runs = [dict(row) for row in cursor.fetchall()]
            
            # 获取总数
            count_query = """
                SELECT COUNT(*) as total
                FROM workflow_runs
                WHERE workflow_id = %s
            """
            count_params = [UUID(workflow_id)]
            if status:
                count_query += " AND status = %s"
                count_params.append(status)
            
            with conn.cursor() as cursor:
                cursor.execute(count_query, count_params)
                total = cursor.fetchone()['total']
            
            return {
                "runs": runs,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Error getting workflow runs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow runs: {str(e)}")


@app.get("/api/workflows/{workflow_id}/runs/{run_id}")
async def get_workflow_run(
    workflow_id: str,
    run_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取运行详情"""
    try:
        from src.server.workflow.db import get_db_connection
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT wr.*, u.username as created_by_name
                    FROM workflow_runs wr
                    LEFT JOIN users u ON wr.created_by = u.id
                    WHERE wr.id = %s AND wr.workflow_id = %s
                """, (UUID(run_id), UUID(workflow_id)))
                run = cursor.fetchone()
                if not run:
                    raise HTTPException(status_code=404, detail="Run not found")
                
                result = dict(run)
                # 解析output字段（如果是JSON字符串）
                if result.get("output") and isinstance(result["output"], str):
                    try:
                        result["output"] = json.loads(result["output"])
                    except json.JSONDecodeError:
                        pass
                
                return result
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting workflow run: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow run: {str(e)}")


@app.get("/api/workflows/{workflow_id}/runs/{run_id}/tasks")
async def get_run_tasks(
    workflow_id: str,
    run_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取运行的任务列表"""
    try:
        from src.server.workflow.db import get_run_tasks, get_db_connection, get_release
        from uuid import UUID
        import json
        
        conn = get_db_connection()
        try:
            tasks = get_run_tasks(conn, UUID(run_id))
            
            # 获取运行对应的 release，以便获取节点显示名称
            node_display_names = {}
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT release_id FROM workflow_runs WHERE id = %s
                """, (UUID(run_id),))
                run = cursor.fetchone()
                if run and run.get('release_id'):
                    release = get_release(conn, run['release_id'])
                    if release and release.get('spec'):
                        spec = release['spec']
                        if isinstance(spec, str):
                            spec = json.loads(spec)
                        # 从 spec 中提取节点显示名称映射
                        nodes = spec.get('nodes', [])
                        for node in nodes:
                            node_id = node.get('id')
                            node_data = node.get('data', {})
                            display_name = node_data.get('displayName') or node_data.get('display_name') or node_data.get('label') or node_id
                            if node_id:
                                node_display_names[node_id] = display_name
            
            # 为每个任务添加节点显示名称
            for task in tasks:
                node_id = task.get('node_id')
                if node_id:
                    task['node_display_name'] = node_display_names.get(node_id, node_id)
                else:
                    task['node_display_name'] = node_id or '未知节点'
            
            return {"tasks": tasks}
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Error getting run tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get run tasks: {str(e)}")


@app.get("/api/workflows/{workflow_id}/runs/{run_id}/status")
async def get_run_status(
    workflow_id: str,
    run_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取运行的状态摘要（用于状态恢复）"""
    try:
        from src.server.workflow.db import get_db_connection, get_run_tasks
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            # 获取运行信息
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, status, created_at, started_at, finished_at
                    FROM workflow_runs
                    WHERE id = %s AND workflow_id = %s
                """, (UUID(run_id), UUID(workflow_id)))
                run = cursor.fetchone()
                if not run:
                    raise HTTPException(status_code=404, detail="Run not found")
            
            # 获取所有任务的状态
            tasks = get_run_tasks(conn, UUID(run_id))
            
            # 构建节点状态映射
            node_statuses = {}
            for task in tasks:
                node_id = task['node_id']
                status = task['status']
                node_statuses[node_id] = {
                    'status': status,
                    'output': task.get('output'),
                    'error': task.get('error'),
                    'metrics': task.get('metrics'),
                    'started_at': task.get('started_at').isoformat() if task.get('started_at') else None,
                    'finished_at': task.get('finished_at').isoformat() if task.get('finished_at') else None,
                }
            
            return {
                'run_id': str(run['id']),
                'run_status': run['status'],
                'node_statuses': node_statuses,
            }
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting run status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get run status: {str(e)}")


@app.get("/api/workflows/{workflow_id}/runs/{run_id}/logs")
async def get_run_logs(
    workflow_id: str,
    run_id: str,
    after_seq: Optional[int] = None,
    limit: Optional[int] = None,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """获取运行日志"""
    try:
        from src.server.workflow.db import get_run_logs, get_db_connection
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            logs = get_run_logs(conn, UUID(run_id), after_seq=after_seq, limit=limit)
            return {"logs": logs}
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Error getting run logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get run logs: {str(e)}")


@app.post("/api/workflows/{workflow_id}/runs/{run_id}/cancel")
async def cancel_run(
    workflow_id: str,
    run_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """取消运行"""
    try:
        from src.server.workflow.db import update_run_status, get_db_connection
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            # 检查运行状态
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT status FROM workflow_runs
                    WHERE id = %s AND workflow_id = %s
                """, (UUID(run_id), UUID(workflow_id)))
                run = cursor.fetchone()
                if not run:
                    raise HTTPException(status_code=404, detail="Run not found")
                
                if run['status'] not in ('queued', 'running'):
                    raise HTTPException(status_code=400, detail=f"Cannot cancel run with status {run['status']}")
            
            # 更新状态为 canceled
            update_run_status(
                conn,
                UUID(run_id),
                'canceled',
                finished_at=datetime.now(),
            )
            conn.commit()
            
            return {"success": True, "message": "Run canceled"}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error canceling run: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel run: {str(e)}")


@app.delete("/api/workflows/{workflow_id}/runs/{run_id}")
async def delete_workflow_run(
    workflow_id: str,
    run_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """删除运行"""
    try:
        from src.server.workflow.db import get_db_connection
        from uuid import UUID
        
        conn = get_db_connection()
        try:
            # 检查运行是否存在
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT status FROM workflow_runs
                    WHERE id = %s AND workflow_id = %s
                """, (UUID(run_id), UUID(workflow_id)))
                run = cursor.fetchone()
                if not run:
                    raise HTTPException(status_code=404, detail="Run not found")
                
                # 如果运行正在进行中，不允许删除
                if run['status'] in ('queued', 'running'):
                    raise HTTPException(status_code=400, detail=f"Cannot delete run with status {run['status']}")
            
            # 删除运行（级联删除相关的任务和日志）
            with conn.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM workflow_runs
                    WHERE id = %s AND workflow_id = %s
                """, (UUID(run_id), UUID(workflow_id)))
                deleted = cursor.rowcount > 0
            
            if not deleted:
                raise HTTPException(status_code=404, detail="Run not found")
            
            conn.commit()
            return {"success": True, "message": "Run deleted"}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting run: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {str(e)}")


@app.post("/api/workflow/validate")
async def validate_workflow_endpoint(config: WorkflowConfigRequest):
    """验证工作流配置"""
    try:
        from src.workflow.validator import validate_workflow
        errors = validate_workflow(config)
        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }
    except Exception as e:
        logger.error(f"Failed to validate workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to validate workflow: {str(e)}")


@app.delete("/api/workflow/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """删除工作流"""
    try:
        storage = get_workflow_storage()
        success = storage.delete(workflow_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete workflow: {str(e)}")


@app.post("/api/workflow/{workflow_id}/duplicate", response_model=WorkflowConfigResponse)
async def duplicate_workflow(workflow_id: str):
    """复制工作流"""
    try:
        storage = get_workflow_storage()
        duplicated_data = storage.duplicate(workflow_id)
        return WorkflowConfigResponse(**duplicated_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error duplicating workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to duplicate workflow: {str(e)}")


@app.post("/api/workflow/execution-results")
async def save_execution_results(request: dict):
    """保存工作流执行结果
    
    Request body:
    {
        "workflow_id": str,
        "thread_id": Optional[str],
        "execution_logs": List[Dict],
        "final_result": Optional[Dict]
    }
    """
    try:
        workflow_id = request.get("workflow_id")
        execution_logs = request.get("execution_logs", [])
        final_result = request.get("final_result")
        thread_id = request.get("thread_id")
        
        logger.info(f"Received save execution results request: workflow_id={workflow_id}, logs_count={len(execution_logs)}, has_final_result={final_result is not None}, thread_id={thread_id}")
        
        if not workflow_id:
            raise HTTPException(status_code=400, detail="workflow_id is required")
        
        storage = get_workflow_storage()
        result_id = storage.save_execution_results(
            workflow_id=workflow_id,
            execution_logs=execution_logs,
            final_result=final_result,
            thread_id=thread_id,
        )
        
        logger.info(f"Successfully saved execution results: result_id={result_id}")
        return {"success": True, "result_id": result_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error saving execution results: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save execution results: {str(e)}")




@app.get("/api/workflow/templates")
async def get_workflow_templates():
    """获取工作流模板列表"""
    try:
        # 目前返回空列表，后续可以从配置文件或数据库加载模板
        return {"templates": []}
    except Exception as e:
        logger.exception(f"Error getting workflow templates: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow templates: {str(e)}")


@app.post("/api/workflow/upload-file")
async def upload_workflow_file(file: UploadFile = File(...)):
    """上传工作流文件"""
    try:
        # 创建上传目录
        upload_dir = Path("workflows/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成唯一文件名
        file_id = str(uuid4())
        file_ext = Path(file.filename or "file").suffix or ""
        file_path = upload_dir / f"{file_id}{file_ext}"
        
        # 保存文件
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 返回相对路径（相对于项目根目录）
        relative_path = str(file_path)
        return {"path": relative_path, "filename": file.filename}
    except Exception as e:
        logger.exception(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
