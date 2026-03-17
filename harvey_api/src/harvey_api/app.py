from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from fastapi import (
    status,
    FastAPI,
    Depends,
    UploadFile,
    HTTPException,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette import EventSourceResponse
from pydantic import BaseModel, HttpUrl

from .clients import MCPClientError
from .container import container, lifespan
from .file_manager import FileManager
from .stream import stream, Stream
from .pricing_context import pricing_context_db, DbUrlItem

app = FastAPI(title="H.A.R.V.E.Y. Pricing Assistant API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/static",
    StaticFiles(directory=container.settings.harvey_static_dir),
    name="static",
)


class ChatUrlItem(BaseModel):
    id: str
    url: HttpUrl


class ChatRequest(BaseModel):
    question: str
    pricing_url: Optional[ChatUrlItem] = None
    pricing_urls: Optional[List[ChatUrlItem]] = None
    pricing_yaml: Optional[str] = None
    pricing_yamls: Optional[List[str]] = None
    datasheet_yaml: Optional[str] = None    # Datasheet YAML (API mode)
    datasheet_yamls: Optional[List[str]] = None
    # Context mode: restricts Harvey to SaaS tools, API tools, or both.
    # "saas"  → only pricing tools (subscriptions, optimal, summary, iPricing, validate)
    # "api"   → only API analysis tools (min_time, capacity_at, …, evaluate_api_datasheet)
    # "all"   → all tools (default / backward-compatible behaviour)
    mode: Literal["saas", "api", "all"] = "all"


class ChatResponse(BaseModel):
    answer: str
    plan: Dict[str, Any]
    result: Dict[str, Any]


def get_file_manager():
    return FileManager(container.settings.harvey_static_dir)


file_mangager_dependency = Annotated[FileManager, Depends(get_file_manager)]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, file_manager_service: file_mangager_dependency
) -> ChatResponse:
    file_extension = ".yaml"
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")
    pricing_urls: List[str] = []
    if request.pricing_url:
        pricing_url_str = pydantic_url_to_str(request.pricing_url.url)
        pricing_urls.append(pricing_url_str)
        pricing_context_db[pricing_url_str] = DbUrlItem(
            request.pricing_url.id, pricing_url_str, datetime.now(timezone.utc)
        )
        file_manager_service.write_file(
            f"{request.pricing_url.id}{file_extension}", b""
        )
    if request.pricing_urls:
        pricing_urls.extend(
            str(pricing_url_item.url) for pricing_url_item in request.pricing_urls
        )
        for pricing_url_item in request.pricing_urls:
            pricing_url_str = pydantic_url_to_str(pricing_url_item.url)
            pricing_context_db[pricing_url_str] = DbUrlItem(
                pricing_url_item.id, pricing_url_str, datetime.now(timezone.utc)
            )
            file_manager_service.write_file(
                f"{pricing_url_item.id}{file_extension}", b""
            )

    pricing_yamls: List[str] = []
    if request.pricing_yaml:
        stripped = request.pricing_yaml.strip()
        if stripped:
            pricing_yamls.append(stripped)
    if request.pricing_yamls:
        pricing_yamls.extend(
            yaml.strip() for yaml in request.pricing_yamls if yaml and yaml.strip()
        )

    datasheet_yamls: List[str] = []
    if request.datasheet_yaml:
        stripped = request.datasheet_yaml.strip()
        if stripped:
            datasheet_yamls.append(stripped)
    if request.datasheet_yamls:
        datasheet_yamls.extend(
            yaml.strip() for yaml in request.datasheet_yamls if yaml and yaml.strip()
        )

    # Deduplicate while preserving order to avoid duplicated contexts when both singular
    # and plural fields are provided or when identical contents are repeated.
    if pricing_urls:
        pricing_urls = list(dict.fromkeys(pricing_urls))
    if pricing_yamls:
        pricing_yamls = list(dict.fromkeys(pricing_yamls))
    if datasheet_yamls:
        datasheet_yamls = list(dict.fromkeys(datasheet_yamls))

    try:
        response_payload = await container.agent.handle_question(
            question=question,
            pricing_urls=pricing_urls,
            yaml_contents=pricing_yamls,
            datasheet_contents=datasheet_yamls,
            mode=request.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MCPClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network dependent
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        answer=response_payload["answer"],
        plan=response_payload["plan"],
        result=response_payload["result"],
    )


@app.get("/events")
async def server_sent_evennts(
    stream: Stream = Depends(lambda: stream),
) -> EventSourceResponse:
    return EventSourceResponse(stream)


def is_yaml_file(content_type: str) -> bool:
    return content_type == "application/yaml" or content_type == "application/x-yaml"


class UploadResponse(BaseModel):
    filename: str
    relative_path: str


@app.post("/upload", status_code=status.HTTP_201_CREATED, response_model=UploadResponse)
async def upload_and_save_pricing(
    file: UploadFile, file_manager_service: file_mangager_dependency
):
    if not is_yaml_file(file.content_type):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Content-Type: {file.content_type}. Only application/yaml is supported",
        )

    filename_without_extension = get_filename_without_extension(file.filename)
    pricing_context_db[filename_without_extension] = DbUrlItem(
        filename_without_extension, None, datetime.now(timezone.utc)
    )
    contents = await file.read()
    file_manager_service.write_file(file.filename, contents)

    return UploadResponse(
        filename=file.filename, relative_path=f"/static/{file.filename}"
    )


@app.delete("/pricing/{filename}", status_code=204)
async def delete_pricing(filename: str, file_manager_service: file_mangager_dependency):
    try:
        file_manager_service.delete_file(filename)
        del pricing_context_db[get_filename_without_extension(filename)]
    except (FileNotFoundError, KeyError):
        raise HTTPException(
            status_code=404, detail=f"File with name {filename} doesn't exist"
        )


def pydantic_url_to_str(url: HttpUrl) -> str:
    return str(url)


def get_filename_without_extension(filename: str) -> str:
    return Path(filename).stem
