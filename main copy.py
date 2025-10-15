# main.py
# ------------------------------------------------------------------------------------
#  What this file does (quick read):
# - Exposes a tiny FastAPI service with:
#     POST /jobs         -> start a render (Runway image→video)
#     GET  /jobs/{id}    -> poll status (queued|processing|done|error)
#     GET  /files/local/{key} -> serve locally-saved MP4s when STORAGE=local
# - On completion:
#     • STORAGE=r2   -> uploads bytes to Cloudflare R2 and returns a presigned URL
#     • STORAGE=local-> writes MP4 under ./local_renders and serves from /files/local
# - NEW:
#     • Versioned keys in R2: renders/YYYY-MM-DD/<job_id>.mp4
#     • Job logs in R2: logs/jobs/YYYY-MM-DD/<job_id>.json (or logs/jobs_failed/… on errors)
# ------------------------------------------------------------------------------------

import os
import uuid
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict

from fastapi import FastAPI, BackgroundTasks, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# App settings (lightweight; adjust if you already have a settings module)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
STORAGE = os.getenv("STORAGE", "local").lower()  # "r2" or "local"

LOCAL_DIR = os.path.join(os.getcwd(), "local_renders")
os.makedirs(LOCAL_DIR, exist_ok=True)

# R2 client is safe to import whether we use it or not
use_r2 = STORAGE == "r2"
if use_r2:
    from r2_client import (
        upload_bytes_and_get_url,
        upload_to_key,
        get_object_stream,
    )

# Runway client (your async generator that returns bytes)
from runway_client import generate_and_get_video_bytes as runway_generate


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="PetGroove API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for your domains later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Job store (in-memory)
# -----------------------------------------------------------------------------
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

# very lightweight job memory
_jobs: Dict[str, Dict] = {}


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    # small hint to ourselves that this is the streaming build
    return {"ok": True, "impl": "streaming-v1"}


# -----------------------------------------------------------------------------
# Helpers for versioned keys & logs (NEW)
# -----------------------------------------------------------------------------
def _today_folder() -> str:
    # UTC folders keep things stable across regions/timezones
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _render_key(job_id: str) -> str:
    # e.g. renders/2025-10-15/<job_id>.mp4
    return f"renders/{_today_folder()}/{job_id}.mp4"

def _log_key(job_id: str, status: str) -> str:
    # success → logs/jobs/YYYY-MM-DD/<job_id>.json
    # error   → logs/jobs_failed/YYYY-MM-DD/<job_id>.json
    base = "logs/jobs" if status == "success" else "logs/jobs_failed"
    return f"{base}/{_today_folder()}/{job_id}.json"


# -----------------------------------------------------------------------------
# Job lifecycle
# -----------------------------------------------------------------------------
@app.post("/jobs", response_model=CreateJobResponse)
async def create_job(payload: CreateJobRequest, background: BackgroundTasks):
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"id": job_id, "status": "queued", "video_url": None, "error": None}

    # kick off processing
    background.add_task(_process_job, job_id, payload.image_url, payload.motion_id, payload.style or "photoreal")

    return CreateJobResponse(id=job_id, status="queued", video_url=None, error=None)


@app.get("/jobs/{job_id}", response_model=GetJobResponse)
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return GetJobResponse(**job)


async def _process_job(job_id: str, image_url: str, motion_id: str, style: str):
    # mark processing
    job = _jobs.get(job_id)
    if not job:
        return
    job["status"] = "processing"

    # Common fields for logs
    log_common = {
        "job_id": job_id,
        "image_url": image_url,
        "motion_id": motion_id,
        "style": style,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "storage": STORAGE,
    }

    try:
        # 1) call Runway and get MP4 bytes
        video_bytes = await runway_generate(image_url=image_url, motion_id=motion_id, style=style)

        # 2) store & produce a client-visible URL (versioned by day/job_id)
        if use_r2:
            key = _render_key(job_id)
            video_url = upload_bytes_and_get_url(
                data=video_bytes,
                key=key,                        # <-- versioned placement in R2
                content_type="video/mp4",
                expires=3600,                    # only applies when falling back to presigned URL
            )

            # success log to R2 (non-blocking best-effort)
            log_doc = {
                **log_common,
                "status": "success",
                "storage_key": key,
                "video_url": video_url,
            }
            try:
                upload_to_key(
                    data=json.dumps(log_doc, ensure_ascii=False).encode("utf-8"),
                    key=_log_key(job_id, "success"),
                    content_type="application/json",
                )
            except Exception:
                # don't fail the job if logging fails
                pass
        else:
            # save locally and serve via /files/local/{filename}
            fname = f"{uuid.uuid4().hex}.mp4"
            fpath = os.path.join(LOCAL_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(video_bytes)
            video_url = f"{PUBLIC_BASE_URL}/files/local/{fname}"

        # 3) done
        job["status"] = "done"
        job["video_url"] = video_url
        job["error"] = None

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["video_url"] = None

        # write a failure log to R2 if available
        if use_r2:
            log_doc = {
                **log_common,
                "status": "error",
                "error": str(e),
            }
            try:
                upload_to_key(
                    data=json.dumps(log_doc, ensure_ascii=False).encode("utf-8"),
                    key=_log_key(job_id, "error"),
                    content_type="application/json",
                )
            except Exception:
                pass


# -----------------------------------------------------------------------------
# Streaming route for files
# -----------------------------------------------------------------------------
# Supports:
# - local files at /files/local/{filename}
# - R2 keys at  /files/{any/r2/key.mp4}  (when STORAGE=r2)
#
# If you keep returning “pretty” public URLs (like https://storage.petgroove.app/renders/xxx.mp4)
# the browser will fetch directly from R2 and this route won’t be used for those.
# It’s still handy if you’d rather stream through your API or keep presigned URLs private.
from fastapi.responses import FileResponse, StreamingResponse

@app.get("/files/{key:path}")
def stream_file(key: str):
    """
    Stream content either from the local filesystem or directly from R2.
    """
    if key.startswith("local/"):
        # Serve local files from local_renders
        local_name = key.split("/", 1)[1] if "/" in key else key
        file_path = os.path.join(LOCAL_DIR, local_name)
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail="file not found")
        # Let the browser stream
        return FileResponse(file_path, media_type="video/mp4")

    # If not local, optionally proxy from R2 (useful if you want to keep URLs private)
    if use_r2:
        try:
            body, content_type = get_object_stream(key)
        except Exception:
            raise HTTPException(status_code=404, detail="object not found")

        # Wrap botocore StreamingBody as an async generator
        def iter_chunks():
            for chunk in iter(lambda: body.read(1024 * 1024), b""):
                yield chunk

        return StreamingResponse(iter_chunks(), media_type=content_type or "application/octet-stream")

    # If we get here on local mode, the key wasn’t under /local
    raise HTTPException(status_code=404, detail="file not found")


# -----------------------------------------------------------------------------
# Optional: a tiny index for sanity
# -----------------------------------------------------------------------------
@app.get("/")
def index():
    return {"service": "petgroove-api", "storage": STORAGE, "public_base": PUBLIC_BASE_URL}