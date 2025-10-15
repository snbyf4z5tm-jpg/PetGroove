# job_store.py
import time, threading
from typing import Dict, Optional

class Job:
    def __init__(self, job_id: str, image_url: str, motion_id: str, style: str):
        self.id = job_id
        self.image_url = image_url
        self.motion_id = motion_id
        self.style = style
        self.status = "queued"          # queued | processing | done | error
        self.video_url: Optional[str] = None
        self.error: Optional[str] = None
        self.created_at = int(time.time())

class JobStore:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job: Job):
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job: return
            for k, v in kwargs.items():
                setattr(job, k, v)

job_store = JobStore()
