from fastapi import FastAPI
import psycopg2
from schemas.

app = FastAPI()

@app.post("/login")
def login(data: UserLogin):
