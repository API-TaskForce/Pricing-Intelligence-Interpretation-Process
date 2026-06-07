from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

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
from pydantic import BaseModel

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

app.mount(
    "/static",
    StaticFiles(directory=container.settings.harvey_static_dir),
    name="static",
)


class ChatRequest(BaseModel):
    question: str
    datasheet_yaml: Optional[str] = None
    datasheet_yamls: Optional[List[str]] = None
    datasheet_url: Optional[str] = None
    datasheet_urls: Optional[List[str]] = None
    history: Optional[List[Dict[str, str]]] = None


class ChatResponse(BaseModel):
    answer: str
    plan: Dict[str, Any]
    result: Dict[str, Any]
    usage: Optional[Dict[str, int]] = None


def get_file_manager():
    return FileManager(container.settings.harvey_static_dir)


file_manager_dependency = Annotated[FileManager, Depends(get_file_manager)]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    yaml_contents: List[str] = []
    if request.datasheet_yaml:
        stripped = request.datasheet_yaml.strip()
        if stripped:
            yaml_contents.append(stripped)
    if request.datasheet_yamls:
        yaml_contents.extend(
            y.strip() for y in request.datasheet_yamls if y and y.strip()
        )
    yaml_contents = list(dict.fromkeys(yaml_contents))

    url_list: List[str] = []
    if request.datasheet_url:
        stripped = request.datasheet_url.strip()
        if stripped:
            url_list.append(stripped)
    if request.datasheet_urls:
        url_list.extend(u.strip() for u in request.datasheet_urls if u and u.strip())
    url_list = list(dict.fromkeys(url_list))

    try:
        response_payload = await container.agent.handle_question(
            question=question,
            datasheet_contents=yaml_contents or None,
            datasheet_urls=url_list or None,
            history=request.history,
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
        usage=response_payload.get("usage"),
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
):
    if not is_yaml_file(file.content_type):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Content-Type: {file.content_type}. Only application/yaml is supported.",
        )
    contents = await file.read()
    file_manager_service.write_file(file.filename, contents)
    return UploadResponse(filename=file.filename, relative_path=f"/static/{file.filename}")


@app.delete("/datasheet/{filename}", status_code=204)
async def delete_datasheet(
    filename: str,
    file_manager_service: file_manager_dependency,
):
    try:
        file_manager_service.delete_file(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File {filename} not found.")
