# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from typing import List, Optional
from urllib.parse import urlparse

import requests

from src.config.loader import get_str_env
from src.rag.retriever import Chunk, Document, Resource, Retriever


class RAGFlowProvider(Retriever):
    """
    RAGFlowProvider is a provider that uses RAGFlow to retrieve documents.
    """

    api_url: str
    api_key: str
    page_size: int = 10
    cross_languages: Optional[List[str]] = None

    def __init__(self):
        api_url = get_str_env("RAGFLOW_API_URL", "")
        if not api_url:
            raise ValueError("RAGFLOW_API_URL is not set in conf.yaml ENV section")
        self.api_url = api_url

        api_key = get_str_env("RAGFLOW_API_KEY", "")
        if not api_key:
            raise ValueError("RAGFLOW_API_KEY is not set in conf.yaml ENV section")
        self.api_key = api_key

        page_size_str = get_str_env("RAGFLOW_PAGE_SIZE", "10")
        try:
            self.page_size = int(page_size_str)
        except ValueError:
            self.page_size = 10

        self.cross_languages = None
        cross_languages = get_str_env("RAGFLOW_CROSS_LANGUAGES", "")
        if cross_languages:
            self.cross_languages = cross_languages.split(",")

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        dataset_ids: list[str] = []
        document_ids: list[str] = []

        for resource in resources:
            dataset_id, document_id = parse_uri(resource.uri)
            dataset_ids.append(dataset_id)
            if document_id:
                document_ids.append(document_id)

        payload = {
            "question": query,
            "dataset_ids": dataset_ids,
            "document_ids": document_ids,
            "page_size": self.page_size,
        }

        if self.cross_languages:
            payload["cross_languages"] = self.cross_languages

        response = requests.post(
            f"{self.api_url}/api/v1/retrieval", headers=headers, json=payload
        )

        if response.status_code != 200:
            raise Exception(f"Failed to query documents: {response.text}")

        result = response.json()
        data = result.get("data", {})
        doc_aggs = data.get("doc_aggs", [])
        docs: dict[str, Document] = {
            doc.get("doc_id"): Document(
                id=doc.get("doc_id"),
                title=doc.get("doc_name"),
                chunks=[],
            )
            for doc in doc_aggs
        }

        for chunk in data.get("chunks", []):
            doc = docs.get(chunk.get("document_id"))
            if doc:
                doc.chunks.append(
                    Chunk(
                        content=chunk.get("content"),
                        similarity=chunk.get("similarity"),
                    )
                )

        return list(docs.values())

    def list_resources(self, query: str | None = None) -> list[Resource]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        params = {}
        if query:
            params["name"] = query

        response = requests.get(
            f"{self.api_url}/api/v1/datasets", headers=headers, params=params
        )

        if response.status_code != 200:
            raise Exception(f"Failed to list resources: {response.text}")

        result = response.json()
        resources = []

        for item in result.get("data", []):
            item = Resource(
                uri=f"rag://dataset/{item.get('id')}",
                title=item.get("name", ""),
                description=item.get("description", ""),
            )
            resources.append(item)

        return resources

    def list_documents(self, resource_id: str, page: int = 1, page_size: int = 50) -> tuple[list[Document], int]:
        """
        List documents in a dataset (knowledge base) with pagination.
        
        According to RAGFlow API documentation:
        GET /api/v1/datasets/{dataset_id}/documents?page={page}&page_size={page_size}&...
        
        Args:
            resource_id: The dataset ID
            page: Page number (1-based, default: 1)
            page_size: Number of documents per page (default: 50)
            
        Returns:
            Tuple of (list of documents in the dataset, total count)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # RAGFlow API endpoint: GET /api/v1/datasets/{dataset_id}/documents
        # Fetch only the requested page
        params = {
            "page": page,
            "page_size": page_size,
        }
        
        endpoint = f"{self.api_url}/api/v1/datasets/{resource_id}/documents"
        logger.info(f"Fetching documents from {endpoint}, page={page}, page_size={page_size}")
        
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                error_text = response.text[:500] if len(response.text) > 500 else response.text
                raise Exception(f"API returned status {response.status_code}: {error_text}")
            
            result = response.json()
            logger.info(f"Response keys: {result.keys() if isinstance(result, dict) else 'Not a dict'}")
            
            # Check for error code in response
            if isinstance(result, dict):
                code = result.get("code")
                if code is not None and code != 0 and code != 200:
                    error_msg = result.get("message", "Unknown error")
                    raise Exception(f"API error code {code}: {error_msg}")
            
            # Extract documents from response
            # RAGFlow API response structure: {"code": 0, "data": {"docs": [...], "total": N}}
            data = result.get("data", {})
            if isinstance(data, dict):
                # RAGFlow uses "docs" key for the document list
                items = data.get("docs", data.get("items", data.get("list", data.get("data", []))))
                total = data.get("total", 0)
            elif isinstance(data, list):
                items = data
                total = len(data)
            else:
                items = []
                total = 0
            
            if not isinstance(items, list):
                logger.warning(f"Items is not a list: {type(items)}")
                items = []
                total = 0
            
            logger.info(f"Page {page}: Found {len(items)} documents (total: {total})")
            
            # Parse documents
            documents = []
            for item in items:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dict item: {type(item)}")
                    continue
                
                # Extract document information
                doc_id = item.get("id") or item.get("doc_id") or item.get("document_id")
                if not doc_id:
                    logger.warning(f"Document item missing ID: {item}")
                    continue
                
                doc_name = item.get("name") or item.get("doc_name") or item.get("title") or item.get("file_name") or str(doc_id)
                
                # Extract upload date (create_time in RAGFlow)
                upload_date = None
                for date_key in ["create_time", "created_at", "upload_time", "created_time", "upload_at", "create_at"]:
                    if date_key in item:
                        upload_date = item.get(date_key)
                        break
                
                # Extract file size (if available)
                size = None
                for size_key in ["size", "file_size", "document_size", "bytes"]:
                    if size_key in item:
                        size_value = item.get(size_key)
                        if isinstance(size_value, (int, float)):
                            size = int(size_value)
                        break
                
                doc = Document(
                    id=str(doc_id),
                    title=str(doc_name),
                    upload_date=str(upload_date) if upload_date else None,
                    size=size,
                )
                documents.append(doc)
            
            logger.info(f"Successfully retrieved {len(documents)} documents (page {page}, total: {total})")
            return documents, total
            
        except requests.exceptions.RequestException as e:
            error_detail = f"Request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail += f" | Response: {e.response.text[:500]}"
                except:
                    pass
            logger.error(f"Request failed for {endpoint}: {error_detail}")
            raise Exception(error_detail)
        except Exception as e:
            logger.error(f"Error processing response from {endpoint}: {e}", exc_info=True)
            raise

    def download_document(self, resource_id: str, document_id: str) -> tuple[bytes, str, str]:
        """
        Download a document from a dataset (knowledge base).
        
        According to RAGFlow API documentation:
        GET /api/v1/datasets/{dataset_id}/documents/{document_id}
        
        Args:
            resource_id: The dataset ID
            document_id: The document ID to download
            
        Returns:
            Tuple of (file content as bytes, filename, content_type)
        """
        import logging
        import mimetypes
        logger = logging.getLogger(__name__)
        
        # First, get document info to retrieve the filename
        # We'll search for the document in the list to get its name
        filename_from_list = None
        content_type = "application/octet-stream"
        
        try:
            # Try to get document info from list_documents
            # Search through pages to find the document
            page = 1
            page_size = 50
            found_doc = None
            
            while True:
                documents, total = self.list_documents(resource_id, page=page, page_size=page_size)
                for doc in documents:
                    if doc.id == document_id:
                        found_doc = doc
                        break
                if found_doc or len(documents) < page_size or page * page_size >= total:
                    break
                page += 1
            
            if found_doc and found_doc.title:
                filename_from_list = found_doc.title
                # Try to determine content type from file extension
                if '.' in filename_from_list:
                    guessed_type, _ = mimetypes.guess_type(filename_from_list)
                    if guessed_type:
                        content_type = guessed_type
                    else:
                        # If mimetypes can't guess, try common extensions
                        ext = filename_from_list.lower().split('.')[-1]
                        ext_to_type = {
                            'pdf': 'application/pdf',
                            'doc': 'application/msword',
                            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            'xls': 'application/vnd.ms-excel',
                            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'ppt': 'application/vnd.ms-powerpoint',
                            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                            'txt': 'text/plain',
                            'html': 'text/html',
                            'xml': 'application/xml',
                            'json': 'application/json',
                        }
                        content_type = ext_to_type.get(ext, "application/octet-stream")
        except Exception as e:
            logger.warning(f"Could not get document info for {document_id}: {e}, using default filename")
        
        # Default filename if we couldn't get it from list
        filename = filename_from_list if filename_from_list else f"document_{document_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        endpoint = f"{self.api_url}/api/v1/datasets/{resource_id}/documents/{document_id}"
        logger.info(f"Downloading document from {endpoint}")
        
        try:
            response = requests.get(endpoint, headers=headers, timeout=60, stream=True)
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                error_text = response.text[:500] if len(response.text) > 500 else response.text
                raise Exception(f"API returned status {response.status_code}: {error_text}")
            
            # Try to get filename and content type from response headers
            # But prioritize filename from document list if it has extension
            filename_from_header = None
            content_disposition = response.headers.get("Content-Disposition", "")
            if content_disposition:
                import re
                # Try filename* first (UTF-8 encoded)
                filename_star_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
                if filename_star_match:
                    from urllib.parse import unquote
                    filename_from_header = unquote(filename_star_match.group(1))
                else:
                    # Fall back to regular filename
                    filename_match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^\s;]+)', content_disposition)
                    if filename_match:
                        filename_from_header = filename_match.group(1).strip('\'"')
            
            response_content_type = response.headers.get("Content-Type", "")
            if response_content_type:
                # Remove charset if present
                content_type = response_content_type.split(';')[0].strip()
            
            # Use filename from document list if it has extension, otherwise use header filename
            # Priority: filename_from_list (with extension) > filename_from_header > default
            if filename_from_list and '.' in filename_from_list:
                # Use filename from list if it has extension
                filename = filename_from_list
                # Also update content_type based on extension if not already set correctly
                if content_type == "application/octet-stream" and '.' in filename_from_list:
                    ext = filename_from_list.lower().split('.')[-1]
                    ext_to_type = {
                        'pdf': 'application/pdf',
                        'doc': 'application/msword',
                        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'xls': 'application/vnd.ms-excel',
                        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'ppt': 'application/vnd.ms-powerpoint',
                        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                        'txt': 'text/plain',
                        'html': 'text/html',
                        'xml': 'application/xml',
                        'json': 'application/json',
                    }
                    if ext in ext_to_type:
                        content_type = ext_to_type[ext]
            elif filename_from_header:
                # Use filename from header if list filename doesn't have extension
                filename = filename_from_header
                # If header filename doesn't have extension but list filename does, use list filename
                if '.' not in filename and filename_from_list and '.' in filename_from_list:
                    filename = filename_from_list
            # else keep the default filename set earlier
            
            # Return the file content as bytes
            file_content = response.content
            logger.info(f"Successfully downloaded document {document_id}, filename: {filename}, size: {len(file_content)} bytes, content_type: {content_type}")
            return file_content, filename, content_type
            
        except requests.exceptions.RequestException as e:
            error_detail = f"Request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail += f" | Response: {e.response.text[:500]}"
                except:
                    pass
            logger.error(f"Request failed for {endpoint}: {error_detail}")
            raise Exception(error_detail)
        except Exception as e:
            logger.error(f"Error downloading document from {endpoint}: {e}", exc_info=True)
            raise


def parse_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "rag":
        raise ValueError(f"Invalid URI: {uri}")
    return parsed.path.split("/")[1], parsed.fragment
