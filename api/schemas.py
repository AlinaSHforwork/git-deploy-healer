from pydantic import BaseModel, Field

class Repository(BaseModel):
    name: str
    clone_url: str

class PushEvent(BaseModel):
    ref: str
    repository: Repository
    after: str = Field(..., description="The commit hash")