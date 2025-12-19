# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DataExtractionRecordRequest(BaseModel):
    """Request model for saving a data extraction record."""

    task_name: Optional[str] = Field(None, description="Name of the task")
    extraction_type: str = Field("material_extraction", description="Type of extraction")
    extraction_step: int = Field(1, description="Current step (1, 2, or 3)")
    file_name: Optional[str] = Field(None, description="Name of the uploaded file")
    file_size: Optional[int] = Field(None, description="Size of the file in bytes")
    file_base64: Optional[str] = Field(None, description="Base64 encoded file content")
    pdf_url: Optional[str] = Field(None, description="PDF URL if used")
    model_name: Optional[str] = Field(None, description="Model name used")
    categories: Optional[Dict] = Field(None, description="Categories from step 2")
    selected_categories: Optional[Dict] = Field(None, description="Selected categories for step 3")
    table_data: Optional[List] = Field(None, description="Table data from step 3")
    result_json: Optional[str] = Field(None, description="Complete result JSON")
    metadata: Optional[Dict] = Field(None, description="Additional metadata")
    record_id: Optional[str] = Field(None, description="Existing record ID to update (deprecated)")
    task_id: Optional[str] = Field(None, description="Task ID to link records across steps")


class DataExtractionRecordResponse(BaseModel):
    """Response model for a data extraction record."""

    id: str
    task_id: Optional[str] = None
    task_name: Optional[str] = None
    extraction_type: str
    extraction_step: int
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_base64: Optional[str] = None
    pdf_url: Optional[str] = None
    model_name: Optional[str] = None
    categories: Optional[Dict] = None
    selected_categories: Optional[Dict] = None
    table_data: Optional[List] = None
    result_json: Optional[str] = None
    metadata: Optional[Dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DataExtractionRecordListResponse(BaseModel):
    """Response model for a list of data extraction records."""

    records: List[DataExtractionRecordResponse]
    total: int
    limit: int
    offset: int

