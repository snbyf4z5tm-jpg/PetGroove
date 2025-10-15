# main.py
# ------------------------------------------------------------------------------------
#  FastAPI service for PetGroove:
#  - POST /jobs           -> enqueue a render (Runway image→video)
#  - GET  /jobs/{id}      -> poll status (queued|processing|done|error)
#  - GET  /files/{key}    -> stream local or R2 (fallback)
#  - GET  /debug/config   -> runtime env (hide in prod)
#  Persistence:
#    * SQLModel + SQLite (petgroove.db) for durable jobs (survives restarts)
#  Storage:
#    * R2 uploads with pretty public URLs via R2_PUBLIC_BASE, or local fallback
# ------------------------------------------------------------------------------------

import os
import uuid
import json
import asyncio
import base64
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

# 🔴 DB imports: SQLModel for persistence
from sqlmodel import SQLModel, Field as SQLField, Session, create_engine, select

# App settings
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
STORAGE = os.getenv("STORAGE", "local").lower()  # "r2" or "local"
DEBUG = os.getenv("DEBUG", "true").lower() in {"1", "true", "yes"}

LOCAL_DIR = os.path.join(os.getcwd(), "local_renders")
os.makedirs(LOCAL_DIR, exist_ok=True)

use_r2 = STORAGE == "r2"
if use_r2:
    from r2_client import upload_bytes_and_get_url, upload_to_key, get_object_stream

from runway_client import generate_and_get_video_bytes as runway_generate

# ---------------- DB setup ----------------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./petgroove.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})

class Job(SQLModel, table=True):
    id: str = SQLField(primary_key=True, index=True)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    image_url: str
    motion_id: str
    style: str = "photoreal"
    status: str = "queued"  # queued|processing|done|error
    video_url: Optional[str] = None
    error: Optional[str] = None

def init_db():
    SQLModel.metadata.create_all(engine)

# ------------- FastAPI app --------------
app = FastAPI(title="PetGroove API", version="0.2.0")

# 🔴 In prod, tighten this list to your domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def _on_startup():
    init_db()

# ---------- Schemas ----------
class CreateJobRequest(BaseModel):
    image_url: str = Field(..., description="Source pet image URL")
    motion_id: str = Field(..., description="Runway motion preset id")
    style: Optional[str] = Field("photoreal", description="Optional style")

class CreateJobResponse(BaseModel):
    id: str
    status: str
    video_url: Optional[str] = None
    error: Optional[str] = None

class GetJobResponse(BaseModel):
    id: str
    status: str
    video_url: Optional[str] = None
    error: Optional[str] = None

# ---------- Health ----------
@app.get("/health")
def health():
    return {"ok": True, "impl": "streaming-v1", "storage": STORAGE}

# -----------------------------------------------------------------------------
# Utilities: make image URL acceptable for Runway
# -----------------------------------------------------------------------------
async def _prepare_prompt_image(image_url: str) -> str:
    """
    Runway requires that `promptImage` be either an HTTPS URL that returns
    a valid `Content-Length` header or a data URI. Some hosts/CDNs do not
    return Content-Length, which triggers 400 errors.

    Strategy:
    1) HEAD the URL; if Content-Length is present and >0, pass the final URL.
    2) Otherwise, GET the bytes and return a data URI (base64).
    """
    timeout = httpx.Timeout(10.0, connect=10.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        try:
            head = await client.head(image_url)
            cl = head.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > 0:
                # Accept and return the resolved URL after redirects
                return str(head.request.url)
        except Exception:
            # If HEAD fails, fall back to GET + inline
            pass

        # Fall back: fetch bytes and inline (cap size to ~10MB)
        r = await client.get(image_url)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "image/jpeg")
        data = r.content
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Image too large (>10MB) for inline data URI.")

        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{b64}"

# ---------- Helpers (versioned keys + logs) ----------
def _today_folder() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _render_key(job_id: str) -> str:
    return f"renders/{_today_folder()}/{job_id}.mp4"

def _log_key(job_id: str, status: str) -> str:
    base = "logs/jobs" if status == "success" else "logs/jobs_failed"
    return f"{base}/{_today_folder()}/{job_id}.json"

# ---------- Jobs ----------
@app.post("/jobs", response_model=CreateJobResponse)
async def create_job(payload: CreateJobRequest, background: BackgroundTasks):
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id,
        image_url=payload.image_url,
        motion_id=payload.motion_id,
        style=payload.style or "photoreal",
        status="queued",
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()

    # 🔴 Background worker does the heavy lifting
    background.add_task(_process_job, job_id)
    return CreateJobResponse(id=job_id, status="queued")

@app.get("/jobs/{job_id}", response_model=GetJobResponse)
def get_job(job_id: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return GetJobResponse(id=job.id, status=job.status, video_url=job.video_url, error=job.error)

async def _process_job(job_id: str):
    """Background worker: process one job from the DB by id."""
    # Mark processing and copy fields we need outside of the DB session
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            return
        # copy out primitives *before* the session closes to avoid detached errors
        image_url = job.image_url
        motion_id = job.motion_id
        style = job.style
        job.status = "processing"
        session.add(job)
        session.commit()

    # Common fields for optional logging
    log_common = {
        "job_id": job_id,
        "storage": STORAGE,
    }

    try:
        # 1) Prepare image: ensure Content-Length or inline as data URI
        prompt_image = await _prepare_prompt_image(image_url)

        # 2) Generate MP4 bytes via Runway
        video_bytes = await runway_generate(
            image_url=prompt_image,
            motion_id=motion_id,
            style=style,
        )

        # 3) Store & build public URL
        if use_r2:
            key = _render_key(job_id)
            video_url = upload_bytes_and_get_url(
                data=video_bytes,
                key=key,
                content_type="video/mp4",
                expires=3600,
            )
            # (best effort) write a success log document
            try:
                upload_to_key(
                    data=json.dumps({**log_common, "status": "success", "storage_key": key, "video_url": video_url}).encode("utf-8"),
                    key=_log_key(job_id, "success"),
                    content_type="application/json",
                )
            except Exception:
                pass
        else:
            fname = f"{uuid.uuid4().hex}.mp4"
            fpath = os.path.join(LOCAL_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(video_bytes)
            video_url = f"{PUBLIC_BASE_URL}/files/local/{fname}"

        # 4) Persist success
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if not job:
                return
            job.status = "done"
            job.video_url = video_url
            job.error = None
            session.add(job)
            session.commit()

    except Exception as e:
        err = str(e)
        # Persist error
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if not job:
                return
            job.status = "error"
            job.error = err
            job.video_url = None
            session.add(job)
            session.commit()

        # (best effort) error log to R2
        if use_r2:
            try:
                upload_to_key(
                    data=json.dumps({**log_common, "status": "error", "error": err}).encode("utf-8"),
                    key=_log_key(job_id, "error"),
                    content_type="application/json",
                )
            except Exception:
                pass

# ---------- Streaming route ----------
@app.get("/files/{key:path}")
def stream_file(key: str):
    if key.startswith("local/"):
        local_name = key.split("/", 1)[1] if "/" in key else key
        file_path = os.path.join(LOCAL_DIR, local_name)
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(file_path, media_type="video/mp4")

    if use_r2:
        try:
            body, content_type = get_object_stream(key)
        except Exception:
            raise HTTPException(status_code=404, detail="object not found")

        def iter_chunks():
            for chunk in iter(lambda: body.read(1024 * 1024), b""):
                yield chunk

        return StreamingResponse(iter_chunks(), media_type=content_type or "application/octet-stream")

    raise HTTPException(status_code=404, detail="file not found")

# ---------- Index ----------
@app.get("/")
def index():
    return {"service": "petgroove-api", "storage": STORAGE, "public_base": PUBLIC_BASE_URL}

# ---------- Debug (hide in prod) ----------
if DEBUG:
    @app.get("/debug/config")
    def debug_config():
        return {
            "STORAGE": STORAGE,
            "R2_ENDPOINT_URL": os.getenv("R2_ENDPOINT_URL"),
            "R2_PUBLIC_BASE": os.getenv("R2_PUBLIC_BASE"),
            "R2_BUCKET": os.getenv("R2_BUCKET"),
            "RUNWAY_API_VERSION": os.getenv("RUNWAY_API_VERSION"),
            "DB_URL": DB_URL,
        }