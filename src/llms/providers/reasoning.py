# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Universal reasoning content extraction for all thinking models.

This module provides wrapper classes that extract reasoning/thinking content
from various model providers (Doubao, Azure OpenAI, OpenAI, etc.)
"""

import logging
from typing import Any, Dict, Iterator, List, Mapping, Optional, Type, Union, cast

import openai
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
    ChatMessageChunk,
    FunctionMessageChunk,
    HumanMessageChunk,
    SystemMessageChunk,
    ToolMessageChunk,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_openai.chat_models.base import (
    _create_usage_metadata,
    _handle_openai_bad_request,
    warnings,
)

logger = logging.getLogger(__name__)


def _extract_reasoning_content_from_delta(delta_dict: Mapping[str, Any]) -> Optional[str]:
    """Extract reasoning content from delta dictionary.

    Supports multiple field names used by different providers:
    - reasoning_content (OpenAI, Azure OpenAI)
    - thinking (some providers)
    - reasoning (some providers)
    - thought (some providers)
    - thought_content (some providers)

    Args:
        delta_dict: Delta dictionary from streaming response

    Returns:
        Optional reasoning content string or None if not found
    """
    # Try various field names that different providers might use
    reasoning_fields = [
        "reasoning_content",
        "thinking",
        "reasoning",
        "thought",
        "thought_content",
    ]

    for field in reasoning_fields:
        if field in delta_dict and delta_dict[field]:
            content = delta_dict[field]
            if isinstance(content, str) and content.strip():
                logger.debug(f"Found reasoning content in delta.{field}")
                return content
    return None


def _extract_reasoning_content_from_response(response: Any) -> Optional[str]:
    """Extract reasoning content from non-streaming response object.

    Args:
        response: Response object (BaseModel or dict) from API

    Returns:
        Optional reasoning content string or None if not found
    """
    if not response:
        return None

    reasoning_fields = [
        "reasoning_content",
        "thinking",
        "reasoning",
        "thought",
        "thought_content",
    ]

    # Try accessing via attributes (OpenAI BaseModel format)
    if isinstance(response, openai.BaseModel) or hasattr(response, "choices"):
        try:
            if hasattr(response, "choices") and response.choices:
                message = response.choices[0].message
                for field in reasoning_fields:
                    if hasattr(message, field):
                        content = getattr(message, field)
                        if content and isinstance(content, str) and content.strip():
                            logger.debug(f"Found reasoning content in response.{field}")
                            return content
        except (IndexError, AttributeError):
            pass

    # Try accessing via dict (raw dict response)
    if isinstance(response, dict):
        if "choices" in response and response["choices"]:
            try:
                message = response["choices"][0].get("message", {})
                for field in reasoning_fields:
                    if field in message and message[field]:
                        content = message[field]
                        if isinstance(content, str) and content.strip():
                            logger.debug(f"Found reasoning content in dict.{field}")
                            return content
            except (IndexError, KeyError):
                pass

    return None


def _convert_delta_to_message_chunk(
    delta_dict: Mapping[str, Any], default_class: Type[BaseMessageChunk]
) -> BaseMessageChunk:
    """Convert a delta dictionary to a message chunk with reasoning content extraction.

    This is based on langchain_openai's implementation but adds reasoning content extraction.
    """
    message_id = delta_dict.get("id")
    role = cast(str, delta_dict.get("role", ""))
    content = cast(str, delta_dict.get("content") or "")
    additional_kwargs: Dict[str, Any] = {}

    # Handle function calls
    if function_call_data := delta_dict.get("function_call"):
        function_call = dict(function_call_data)
        if "name" in function_call and function_call["name"] is None:
            function_call["name"] = ""
        additional_kwargs["function_call"] = function_call

    # Handle tool calls
    tool_call_chunks = []
    if raw_tool_calls := delta_dict.get("tool_calls"):
        additional_kwargs["tool_calls"] = raw_tool_calls
        try:
            tool_call_chunks = [
                tool_call_chunk(
                    name=rtc.get("function", {}).get("name"),
                    args=rtc.get("function", {}).get("arguments"),
                    id=rtc.get("id"),
                    index=rtc.get("index", 0),
                )
                for rtc in raw_tool_calls
                if rtc.get("function")  # Ensure function key exists
            ]
        except (KeyError, TypeError):
            # Log the error but continue processing
            pass

    # Extract reasoning content from delta
    reasoning_content = _extract_reasoning_content_from_delta(delta_dict)
    if reasoning_content:
        additional_kwargs["reasoning_content"] = reasoning_content

    # Return appropriate message chunk based on role
    if role == "user" or default_class == HumanMessageChunk:
        return HumanMessageChunk(content=content, id=message_id)
    elif role == "assistant" or default_class == AIMessageChunk:
        return AIMessageChunk(
            content=content,
            additional_kwargs=additional_kwargs,
            id=message_id,
            tool_call_chunks=tool_call_chunks,  # type: ignore[arg-type]
        )
    elif role in ("system", "developer") or default_class == SystemMessageChunk:
        if role == "developer":
            additional_kwargs = {"__openai_role__": "developer"}
        return SystemMessageChunk(
            content=content, id=message_id, additional_kwargs=additional_kwargs
        )
    elif role == "function" or default_class == FunctionMessageChunk:
        function_name = delta_dict.get("name", "")
        return FunctionMessageChunk(content=content, name=function_name, id=message_id)
    elif role == "tool" or default_class == ToolMessageChunk:
        tool_call_id = delta_dict.get("tool_call_id", "")
        return ToolMessageChunk(
            content=content, tool_call_id=tool_call_id, id=message_id
        )
    elif role or default_class == ChatMessageChunk:
        return ChatMessageChunk(content=content, role=role, id=message_id)
    else:
        return default_class(content=content, id=message_id)  # type: ignore


def _convert_chunk_to_generation_chunk(
    chunk: Dict[str, Any],
    default_chunk_class: Type[BaseMessageChunk],
    base_generation_info: Optional[Dict[str, Any]],
) -> Optional[ChatGenerationChunk]:
    """Convert a streaming chunk to a generation chunk with reasoning content.

    This is based on langchain_openai's implementation but adds reasoning content extraction.
    """
    # Skip content.delta type chunks from beta.chat.completions.stream
    if chunk.get("type") == "content.delta":
        return None

    token_usage = chunk.get("usage")
    choices = (
        chunk.get("choices", [])
        # Handle chunks from beta.chat.completions.stream format
        or chunk.get("chunk", {}).get("choices", [])
    )

    usage_metadata: Optional[UsageMetadata] = (
        _create_usage_metadata(token_usage) if token_usage else None
    )

    # Handle empty choices
    if not choices:
        generation_chunk = ChatGenerationChunk(
            message=default_chunk_class(content="", usage_metadata=usage_metadata)
        )
        return generation_chunk

    choice = choices[0]
    if choice.get("delta") is None:
        return None

    message_chunk = _convert_delta_to_message_chunk(
        choice["delta"], default_chunk_class
    )
    generation_info = dict(base_generation_info) if base_generation_info else {}

    # Add finish reason and model info if available
    if finish_reason := choice.get("finish_reason"):
        generation_info["finish_reason"] = finish_reason
        if model_name := chunk.get("model"):
            generation_info["model_name"] = model_name
        if system_fingerprint := chunk.get("system_fingerprint"):
            generation_info["system_fingerprint"] = system_fingerprint

    # Add log probabilities if available
    if logprobs := choice.get("logprobs"):
        generation_info["logprobs"] = logprobs

    # Attach usage metadata to AI message chunks
    if usage_metadata and isinstance(message_chunk, AIMessageChunk):
        message_chunk.usage_metadata = usage_metadata

    generation_chunk = ChatGenerationChunk(
        message=message_chunk, generation_info=generation_info or None
    )
    return generation_chunk


class ChatOpenAIWithReasoning(ChatOpenAI):
    """Extended ChatOpenAI with universal reasoning content extraction.

    This class extends ChatOpenAI to extract reasoning/thinking content
    from various model providers that support thinking models (Doubao, OpenAI, etc.).
    """

    def _create_chat_result(
        self,
        response: Union[Dict[str, Any], openai.BaseModel],
        generation_info: Optional[Dict[str, Any]] = None,
    ) -> ChatResult:
        """Create a chat result with reasoning content extraction."""
        chat_result = super()._create_chat_result(response, generation_info)

        # Extract reasoning content from response
        reasoning_content = _extract_reasoning_content_from_response(response)
        if reasoning_content and chat_result.generations:
            chat_result.generations[0].message.additional_kwargs[
                "reasoning_content"
            ] = reasoning_content
            logger.debug(f"Extracted reasoning content (length: {len(reasoning_content)})")

        return chat_result

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream responses with reasoning content extraction."""
        kwargs["stream"] = True
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        default_chunk_class: Type[BaseMessageChunk] = AIMessageChunk
        base_generation_info: Dict[str, Any] = {}

        # Handle response format for beta completions
        if "response_format" in payload:
            if self.include_response_headers:
                warnings.warn(
                    "Cannot currently include response headers when response_format is "
                    "specified."
                )
            payload.pop("stream")
            response_stream = self.root_client.beta.chat.completions.stream(**payload)
            context_manager = response_stream
        else:
            # Handle regular streaming with optional response headers
            if self.include_response_headers:
                raw_response = self.client.with_raw_response.create(**payload)
                response = raw_response.parse()
                base_generation_info = {"headers": dict(raw_response.headers)}
            else:
                response = self.client.create(**payload)
            context_manager = response

        try:
            with context_manager as response:
                is_first_chunk = True
                for chunk in response:
                    # Convert chunk to dict if it's a model object
                    if not isinstance(chunk, dict):
                        chunk = chunk.model_dump()

                    generation_chunk = _convert_chunk_to_generation_chunk(
                        chunk,
                        default_chunk_class,
                        base_generation_info if is_first_chunk else {},
                    )

                    if generation_chunk is None:
                        continue

                    # Update default chunk class for subsequent chunks
                    default_chunk_class = generation_chunk.message.__class__

                    # Handle log probabilities for callback
                    logprobs = (generation_chunk.generation_info or {}).get("logprobs")
                    if run_manager:
                        run_manager.on_llm_new_token(
                            generation_chunk.text,
                            chunk=generation_chunk,
                            logprobs=logprobs,
                        )

                    is_first_chunk = False
                    yield generation_chunk

        except openai.BadRequestError as e:
            _handle_openai_bad_request(e)

        # Handle final completion for response_format requests
        if hasattr(response, "get_final_completion") and "response_format" in payload:
            try:
                final_completion = response.get_final_completion()
                generation_chunk = self._get_generation_chunk_from_completion(
                    final_completion
                )
                if run_manager:
                    run_manager.on_llm_new_token(
                        generation_chunk.text, chunk=generation_chunk
                    )
                yield generation_chunk
            except AttributeError:
                # If get_final_completion method doesn't exist, continue without it
                pass


class AzureChatOpenAIWithReasoning(AzureChatOpenAI):
    """Extended AzureChatOpenAI with universal reasoning content extraction.

    This class extends AzureChatOpenAI to extract reasoning/thinking content
    from Azure OpenAI thinking models.
    """

    def _create_chat_result(
        self,
        response: Union[Dict[str, Any], openai.BaseModel],
        generation_info: Optional[Dict[str, Any]] = None,
    ) -> ChatResult:
        """Create a chat result with reasoning content extraction."""
        chat_result = super()._create_chat_result(response, generation_info)

        # Extract reasoning content from response
        reasoning_content = _extract_reasoning_content_from_response(response)
        if reasoning_content and chat_result.generations:
            chat_result.generations[0].message.additional_kwargs[
                "reasoning_content"
            ] = reasoning_content
            logger.debug(f"Extracted reasoning content from Azure (length: {len(reasoning_content)})")

        return chat_result

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream responses with reasoning content extraction."""
        kwargs["stream"] = True
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        default_chunk_class: Type[BaseMessageChunk] = AIMessageChunk
        base_generation_info: Dict[str, Any] = {}

        # Azure OpenAI uses the same streaming format as OpenAI
        # Handle response format for beta completions
        if "response_format" in payload:
            if self.include_response_headers:
                warnings.warn(
                    "Cannot currently include response headers when response_format is "
                    "specified."
                )
            payload.pop("stream")
            response_stream = self.root_client.beta.chat.completions.stream(**payload)
            context_manager = response_stream
        else:
            # Handle regular streaming
            if self.include_response_headers:
                raw_response = self.client.with_raw_response.create(**payload)
                response = raw_response.parse()
                base_generation_info = {"headers": dict(raw_response.headers)}
            else:
                response = self.client.create(**payload)
            context_manager = response

        try:
            with context_manager as response:
                is_first_chunk = True
                for chunk in response:
                    # Convert chunk to dict if it's a model object
                    if not isinstance(chunk, dict):
                        chunk = chunk.model_dump()

                    generation_chunk = _convert_chunk_to_generation_chunk(
                        chunk,
                        default_chunk_class,
                        base_generation_info if is_first_chunk else {},
                    )

                    if generation_chunk is None:
                        continue

                    # Update default chunk class for subsequent chunks
                    default_chunk_class = generation_chunk.message.__class__

                    # Handle log probabilities for callback
                    logprobs = (generation_chunk.generation_info or {}).get("logprobs")
                    if run_manager:
                        run_manager.on_llm_new_token(
                            generation_chunk.text,
                            chunk=generation_chunk,
                            logprobs=logprobs,
                        )

                    is_first_chunk = False
                    yield generation_chunk

        except openai.BadRequestError as e:
            _handle_openai_bad_request(e)

        # Handle final completion for response_format requests
        if hasattr(response, "get_final_completion") and "response_format" in payload:
            try:
                final_completion = response.get_final_completion()
                generation_chunk = self._get_generation_chunk_from_completion(
                    final_completion
                )
                if run_manager:
                    run_manager.on_llm_new_token(
                        generation_chunk.text, chunk=generation_chunk
                    )
                yield generation_chunk
            except AttributeError:
                # If get_final_completion method doesn't exist, continue without it
                pass
