# runway_client.py
import os
import asyncio
import httpx

from settings import settings

# ---- Runway public API (correct host + version) ----
RUNWAY_API_BASE = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = os.getenv("RUNWAY_API_VERSION", "2024-11-06")

# Model & defaults (can be overridden by env)
MODEL = os.getenv("RUNWAY_MODEL", "gen4_turbo")
DURATION_SEC = int(os.getenv("RUNWAY_DURATION_SEC", "8"))
OUTPUT_FPS = int(os.getenv("RUNWAY_OUTPUT_FPS", "24"))
RATIO = os.getenv("RUNWAY_RATIO", "1280:720")  # valid for gen4_turbo

class RunwayError(Exception):
    pass

def _headers():
    api_key = os.getenv("RUNWAY_API_KEY") or settings.runway_api_key
    if not api_key:
        raise RunwayError("RUNWAY_API_KEY not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": RUNWAY_VERSION,
        "Content-Type": "application/json",
    }

async def _create_task(client: httpx.AsyncClient, image_url: str, motion_id: str, style: str) -> str:
    """
    Start an image->video generation (new Runway public API).
    Returns task id.
    """
    payload = {
        "promptImage": image_url,
        "model": MODEL,
        "duration": DURATION_SEC,
        "ratio": RATIO,
        "fps": OUTPUT_FPS,
        "outputFormat": "mp4",
        # optional, keep in case you map motions/styles later
        "motionPreset": motion_id,
        "style": style,
    }
    r = await client.post(f"{RUNWAY_API_BASE}/image_to_video", json=payload)
    if r.status_code >= 300:
        raise RunwayError(f"create failed: {r.status_code} {r.text}")
    data = r.json()
    return data["id"]

async def _wait_for_task(client: httpx.AsyncClient, task_id: str) -> str:
    """
    Poll task until it succeeds and return the first output URL.
    """
    while True:
        r = await client.get(f"{RUNWAY_API_BASE}/tasks/{task_id}")
        if r.status_code >= 300:
            raise RunwayError(f"status failed: {r.status_code} {r.text}")
        data = r.json()
        status = data.get("status")
        if status == "SUCCEEDED" or status == "succeeded":
            outputs = data.get("output") or data.get("outputs") or []
            if isinstance(outputs, list) and outputs:
                return outputs[0]
            # some responses use dict with "uri"
            if isinstance(outputs, dict) and outputs.get("uri"):
                return outputs["uri"]
            raise RunwayError("no video URL in output")
        if status in ("FAILED", "failed", "CANCELED", "cancelled"):
            raise RunwayError(f"task failed: {data}")
        await asyncio.sleep(2)

async def generate_and_get_video_bytes(image_url: str, motion_id: str, style: str) -> bytes:
    """
    High-level: create task, wait, download MP4, return bytes.
    """
    async with httpx.AsyncClient(timeout=None, headers=_headers()) as client:
        task_id = await _create_task(client, image_url, motion_id, style)
        video_url = await _wait_for_task(client, task_id)
        resp = await client.get(video_url)
        if resp.status_code >= 300:
            raise RunwayError(f"download failed: {resp.status_code} {resp.text}")
        return resp.content