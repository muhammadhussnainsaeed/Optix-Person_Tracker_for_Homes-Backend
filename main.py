from fastapi import FastAPI
import psycopg2
import jwt
import json
import os

ai_Model = True

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Surveillance System Online", "version": "1.0"}

try:

    conn = psycopg2.connect("dbname=home_surveillance_db user=postgres password=12345 host=192.168.100.8 port=5432")

    print("✅ SUCCESS: psycopg2-binary is working perfectly!")
    conn.close()
except Exception as e:
    print(f"❌ ERROR: {e}")