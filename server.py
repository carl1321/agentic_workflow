# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Server script for running the AgenticWorkflow API.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn

# 日志格式（后续若指定日志目录会复用）
_LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FMT)
logger = logging.getLogger(__name__)


def _setup_log_file(log_dir: str) -> None:
    """将根 logger 的日志同时写入指定目录下的 server.log。无权限时回退到当前工作目录下的同名目录。"""
    if not log_dir or not str(log_dir).strip():
        return
    log_path = Path(log_dir).resolve()
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # 无权限（如 /logs）时回退到当前工作目录下的同名目录，如 ./logs
        fallback = Path.cwd() / Path(log_dir).name
        if fallback != log_path:
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                log_path = fallback
                logger.info("Using log directory under cwd: %s", log_path)
            except OSError:
                logger.warning("Cannot create log directory %s or %s: %s. Logging to console only.", log_path, fallback, e)
                return
        else:
            logger.warning("Cannot create log directory %s: %s. Logging to console only.", log_path, e)
            return
    log_file = log_path / "server.log"
    try:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_LOG_FMT))
        logging.getLogger().addHandler(fh)
        logger.info("Logging to file: %s", log_file)
    except OSError as e:
        logger.warning("Cannot open log file %s: %s. Logging to console only.", log_file, e)

# To ensure compatibility with Windows event loop issues when using Uvicorn and Asyncio Checkpointer,
# This is necessary because some libraries expect a selector-based event loop.
# This is a workaround for issues with Uvicorn and Watchdog on Windows.
# See:
# Since Python 3.8 the default on Windows is the Proactor event loop,
# which lacks add_reader/add_writer and can break libraries that expect selector-based I/O (e.g., some Uvicorn/Watchdog/stdio integrations).
# For compatibility, this forces the selector loop.
if os.name == "nt":
    logger.info("Setting Windows event loop policy for asyncio")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def handle_shutdown(signum, frame):
    """Handle graceful shutdown on SIGTERM/SIGINT"""
    logger.info("Received shutdown signal. Starting graceful shutdown...")
    # 不要在这里调用 sys.exit()，因为 uvicorn 会处理优雅关闭
    # 直接退出会导致 atexit 回调中的异常
    # uvicorn 会自动处理信号并优雅关闭


# Register signal handlers
signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

if __name__ == "__main__":
    # Load configuration from conf.yaml
    # Environment variables can still override YAML config
    from src.config.loader import load_yaml_config, get_bool_env, get_str_env
    
    config = load_yaml_config("conf.yaml")
    env_config = config.get("ENV", {})
    
    # Set default environment variables for checkpoint saver if not already set
    # Priority: environment variable > YAML config > default
    if not os.getenv("LANGGRAPH_CHECKPOINT_SAVER"):
        checkpoint_saver = env_config.get("LANGGRAPH_CHECKPOINT_SAVER", True)
        os.environ["LANGGRAPH_CHECKPOINT_SAVER"] = str(checkpoint_saver).lower()
    if not os.getenv("LANGGRAPH_CHECKPOINT_DB_URL"):
        # Default PostgreSQL connection string
        # Format: postgresql://user:password@host:port/database
        # You can override this by setting LANGGRAPH_CHECKPOINT_DB_URL in conf.yaml or environment variable
        db_url = env_config.get("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
        os.environ["LANGGRAPH_CHECKPOINT_DB_URL"] = db_url

    # 搜索引擎等工具从 os.environ 读取 API Key，将 conf.yaml ENV 中的 key 注入（若尚未设置）
    if not os.getenv("TAVILY_API_KEY") and env_config.get("TAVILY_API_KEY"):
        os.environ["TAVILY_API_KEY"] = str(env_config["TAVILY_API_KEY"]).strip()
    if not os.getenv("BRAVE_SEARCH_API_KEY") and env_config.get("BRAVE_API_KEY"):
        os.environ["BRAVE_SEARCH_API_KEY"] = str(env_config["BRAVE_API_KEY"]).strip()

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run the AgenticWorkflow API server")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (default: True except on Windows)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to bind the server to (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8008,
        help="Port to bind the server to (default: 8008)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level (default: info)",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="Directory to write server.log (overrides conf.yaml ENV.LOG_DIR)",
    )

    args = parser.parse_args()

    # 日志写入目录：命令行 --log-dir > 环境变量 LOG_DIR > conf.yaml ENV.LOG_DIR
    log_dir = args.log_dir or os.getenv("LOG_DIR") or (env_config.get("LOG_DIR") if isinstance(env_config.get("LOG_DIR"), str) else None)
    if log_dir:
        _setup_log_file(log_dir)

    # Determine reload setting
    reload = False
    if args.reload:
        reload = True

    try:
        logger.info(f"Starting AgenticWorkflow API server on {args.host}:{args.port}")
        uvicorn.run(
            "src.server.app:app",
            host=args.host,
            port=args.port,
            reload=reload,
            log_level=args.log_level,
        )
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        sys.exit(1)
