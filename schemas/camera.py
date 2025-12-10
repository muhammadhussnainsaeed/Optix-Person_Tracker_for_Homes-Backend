from pydantic import BaseModel

class Camera_Detail(BaseModel):
    name: str
    location: str
    video_url: str
    description: str
    privacy: bool

class Create_Camera(BaseModel):
    user_id: str
    username: str
    name: str
    location: str
    video_url: str
    description: str
    is_private: bool
    jwt_token: str
    floor_id: str
