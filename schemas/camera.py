from pydantic import BaseModel
from typing import List

class Camera_Detail(BaseModel):
    camera_id: str
    username: str
    user_id: str
    jwt_token: str

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

class Update_Camera(BaseModel):
    user_id: str
    username: str
    camera_id: str
    name: str
    location: str
    video_url: str
    description: str
    is_private: bool
    jwt_token: str
    floor_id: str

class Delete_Camera(BaseModel):
    user_id: str
    username: str
    camera_id: str
    jwt_token: str

class Update_Camera_Network(BaseModel):
    user_id: str
    username: str
    jwt_token: str
    camera_id: str
    connected_camera_id: List[str]