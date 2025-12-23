from pydantic import BaseModel
from typing import Optional

class DeploymentResult(BaseModel):
    container_id: str
    image_tag: str
    host_port: int
    status: str
    error: Optional[str] = None