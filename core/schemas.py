from typing import Optional

from pydantic import BaseModel


class DeploymentResult(BaseModel):
    container_id: str
    image_tag: str
    host_port: int
    status: str
    error: Optional[str] = None
