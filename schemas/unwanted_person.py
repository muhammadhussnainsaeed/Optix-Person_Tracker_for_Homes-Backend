from pydantic import BaseModel

class UnmarkWantedPerson(BaseModel):
    username: str
    user_id: str
    jwt_token: str
    unwanted_person_id: str
    family_member_id: str