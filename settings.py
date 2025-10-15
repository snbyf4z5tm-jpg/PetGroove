# settings.py
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

# Load variables from .env at import time
load_dotenv()

class Settings(BaseModel):
    r2_access_key_id: str = Field(default=os.getenv("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = Field(default=os.getenv("R2_SECRET_ACCESS_KEY", ""))
    r2_endpoint_url: str = Field(default=os.getenv("R2_ENDPOINT_URL", ""))
    r2_bucket: str = Field(default=os.getenv("R2_BUCKET", "petgroove"))
    r2_public_base: str = Field(default=os.getenv("R2_PUBLIC_BASE", ""))
    runway_api_key: str = Field(default=os.getenv("RUNWAY_API_KEY", ""))
    runway_api_version: str = Field(default=os.getenv("RUNWAY_API_VERSION", "2024-11-06")) 
    public_base_url: str = Field(default=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"))

settings = Settings()
