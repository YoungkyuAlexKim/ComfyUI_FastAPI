from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class ImageItem(BaseModel):
    id: str
    url: str
    thumb_url: Optional[str] = None
    created_at: str
    meta: Optional[Dict[str, Any]] = None


class PaginatedImages(BaseModel):
    items: List[ImageItem]
    page: int
    size: int
    total: int
    total_pages: int


class ControlItem(BaseModel):
    id: str
    url: str
    thumb_url: Optional[str] = None
    created_at: str
    meta: Optional[Dict[str, Any]] = None


class PaginatedControls(BaseModel):
    items: List[ControlItem]
    page: int
    size: int
    total: int
    total_pages: int


class WorkflowItem(BaseModel):
    id: str
    name: str
    description: str
    node_count: int
    style_prompt: str
    negative_prompt: str
    recommended_prompt: str


class WorkflowsResponse(BaseModel):
    workflows: List[WorkflowItem]


class OkResponse(BaseModel):
    ok: bool


class UploadControlResponse(BaseModel):
    ok: bool
    id: str
    url: str


class EnqueueResponse(BaseModel):
    job_id: str
    status: str
    position: int


class JobStatusResponse(BaseModel):
    id: str
    status: str
    progress: float
    position: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CancelActiveResponse(BaseModel):
    message: str
    job_id: str


class TranslateResponse(BaseModel):
    translated_text: str


