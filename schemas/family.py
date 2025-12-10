from pydantic import BaseModel

class AddFamilyMember(BaseModel):
    name: str
    relationship: str
    username: str
    jwt_token: str
    user_id: str
