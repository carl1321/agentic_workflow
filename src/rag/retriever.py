# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import abc

from pydantic import BaseModel, Field


class Chunk:
    content: str
    similarity: float

    def __init__(self, content: str, similarity: float):
        self.content = content
        self.similarity = similarity


class Document:
    """
    Document is a class that represents a document.
    """

    id: str
    url: str | None = None
    title: str | None = None
    chunks: list[Chunk] = []
    upload_date: str | None = None
    size: int | None = None

    def __init__(
        self,
        id: str,
        url: str | None = None,
        title: str | None = None,
        chunks: list[Chunk] = [],
        upload_date: str | None = None,
        size: int | None = None,
    ):
        self.id = id
        self.url = url
        self.title = title
        self.chunks = chunks
        self.upload_date = upload_date
        self.size = size

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "content": "\n\n".join([chunk.content for chunk in self.chunks]),
        }
        if self.url:
            d["url"] = self.url
        if self.title:
            d["title"] = self.title
        return d


class Resource(BaseModel):
    """
    Resource is a class that represents a resource.
    """

    uri: str = Field(..., description="The URI of the resource")
    title: str = Field(..., description="The title of the resource")
    description: str | None = Field("", description="The description of the resource")


class Retriever(abc.ABC):
    """
    Define a RAG provider, which can be used to query documents and resources.
    """

    @abc.abstractmethod
    def list_resources(self, query: str | None = None) -> list[Resource]:
        """
        List resources from the rag provider.
        """
        pass

    @abc.abstractmethod
    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        """
        Query relevant documents from the resources.
        """
        pass

    def list_documents(self, resource_id: str, page: int = 1, page_size: int = 50) -> tuple[list[Document], int]:
        """
        List documents in a resource (knowledge base) with pagination.
        This method is optional and may not be implemented by all providers.
        
        Args:
            resource_id: The ID of the resource (dataset ID)
            page: Page number (1-based, default: 1)
            page_size: Number of documents per page (default: 50)
            
        Returns:
            Tuple of (list of documents in the resource, total count)
        """
        raise NotImplementedError("list_documents is not implemented for this provider")

    def download_document(self, resource_id: str, document_id: str) -> tuple[bytes, str, str]:
        """
        Download a document from a resource (knowledge base).
        This method is optional and may not be implemented by all providers.
        
        Args:
            resource_id: The ID of the resource (dataset ID)
            document_id: The ID of the document to download
            
        Returns:
            Tuple of (file content as bytes, filename, content_type)
        """
        raise NotImplementedError("download_document is not implemented for this provider")
