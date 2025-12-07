from pydantic import BaseModel

# To create the user
class UserSignup(BaseModel):
    username: str
    name: str
    hashed_password: str
    security_question: str
    hashed_security_question: str

#To login the user
class UserLogin(BaseModel):
    username: str
    password: str

#To forget the password
class UserForgetPassword(BaseModel):
    username: str
    security_question: str
    hashed_security_question: str
    new_password: str

