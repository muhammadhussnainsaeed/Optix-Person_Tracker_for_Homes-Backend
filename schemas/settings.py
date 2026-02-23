from pydantic import BaseModel

class UpdateName(BaseModel):
    username: str
    user_id: str
    name: str
    jwt_token: str

class UpdatePassword(BaseModel):
    username: str
    user_id: str
    old_password: str
    new_password: str
    jwt_token: str

class UpdateSecurityQuestionAnswer(BaseModel):
    username: str
    user_id: str
    security_question: str
    security_answer: str
    password: str
    jwt_token: str