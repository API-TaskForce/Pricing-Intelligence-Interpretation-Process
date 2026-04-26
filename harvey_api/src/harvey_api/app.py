from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import (
    Request,
    status,
    FastAPI,
    Depends,
    UploadFile,
    HTTPException,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette import EventSourceResponse
from pydantic import BaseModel

from .auth import CurrentUser
from .clients import MCPClientError
from .container import container, lifespan
from .file_manager import FileManager
from .stream import stream, Stream

app = FastAPI(title="H.A.R.V.E.Y. API Analysis Assistant", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a 500 with CORS headers intact."""
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
    )


app.mount(
    "/static",
    StaticFiles(directory=container.settings.harvey_static_dir),
    name="static",
)


class ChatRequest(BaseModel):
    class HistoryMessage(BaseModel):
        role: str
        content: str

    question: str
    datasheet_yaml: Optional[str] = None
    datasheet_yamls: Optional[List[str]] = None
    datasheet_url: Optional[str] = None
    datasheet_urls: Optional[List[str]] = None
    history: Optional[List[HistoryMessage]] = None
    api_key: Optional[str] = None
    query_mode: Optional[str] = "guided"


class ChatResponse(BaseModel):
    answer: str
    plan: Dict[str, Any]
    result: Dict[str, Any]


def get_file_manager():
    return FileManager(container.settings.harvey_static_dir)


file_manager_dependency = Annotated[FileManager, Depends(get_file_manager)]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@app.get("/auth/me")
async def auth_me(current_user: CurrentUser) -> dict[str, str]:
    username, role = current_user
    return {"username": username, "role": role}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: CurrentUser,
) -> ChatResponse:
    username, role = current_user

    if role == "student" and not request.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required. Please provide your Gemini API key.",
        )

    # Admin always uses the server key; students always use Gemini with their own key.
    request_api_key = None if role == "admin" else request.api_key
    request_provider = "openai" if role == "admin" else "gemini"

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    datasheet_yamls: List[str] = []
    if request.datasheet_yaml:
        stripped = request.datasheet_yaml.strip()
        if stripped:
            datasheet_yamls.append(stripped)
    if request.datasheet_yamls:
        datasheet_yamls.extend(y.strip() for y in request.datasheet_yamls if y and y.strip())
    datasheet_yamls = list(dict.fromkeys(datasheet_yamls))

    datasheet_urls: List[str] = []
    if request.datasheet_url:
        stripped = request.datasheet_url.strip()
        if stripped:
            datasheet_urls.append(stripped)
    if request.datasheet_urls:
        datasheet_urls.extend(u.strip() for u in request.datasheet_urls if u and u.strip())
    datasheet_urls = list(dict.fromkeys(datasheet_urls))

    query_mode = request.query_mode if request.query_mode in ("guided", "autonomous") else "guided"

    try:
        response_payload = await container.agent.handle_question(
            question=question,
            datasheet_contents=datasheet_yamls,
            datasheet_urls=datasheet_urls,
            history=[item.model_dump() for item in request.history] if request.history else None,
            api_key=request_api_key,
            provider=request_provider,
            query_mode=query_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MCPClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        answer=response_payload["answer"],
        plan=response_payload["plan"],
        result=response_payload["result"],
    )


@app.get("/events")
async def server_sent_events(
    stream: Stream = Depends(lambda: stream),
) -> EventSourceResponse:
    return EventSourceResponse(stream)


def is_yaml_file(content_type: str) -> bool:
    return content_type in ("application/yaml", "application/x-yaml")


class UploadResponse(BaseModel):
    filename: str
    relative_path: str


@app.post("/upload", status_code=status.HTTP_201_CREATED, response_model=UploadResponse)
async def upload_datasheet(
    file: UploadFile,
    file_manager_service: file_manager_dependency,
    current_user: CurrentUser,
):
    if not is_yaml_file(file.content_type):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Content-Type: {file.content_type}. Only application/yaml is supported.",
        )
    contents = await file.read()
    file_manager_service.write_file(file.filename, contents)
    return UploadResponse(filename=file.filename, relative_path=f"/static/{file.filename}")


@app.delete("/pricing/{filename}", status_code=204)
async def delete_datasheet(
    filename: str,
    file_manager_service: file_manager_dependency,
    current_user: CurrentUser,
):
    try:
        file_manager_service.delete_file(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File {filename} not found.")
