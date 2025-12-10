from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import text
from db import session
from core import security
from schemas import camera, user

router = APIRouter(tags=["Camera"])

@router.get("/camera/fetch_all")
def fetch_list(username: str,jwt_token: str, user_id: str, db: Session = Depends(session.get_db)):

    token_verification= security.verify_token(jwt_token)

    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        SELECT id, name, description, is_private
        FROM cameras 
        WHERE user_id = :user_id
    """)

    result = db.execute(query, {"user_id": user_id})
    cameras = result.mappings().all()

    return {
        "message": "Cameras fetched successfully",
        "count": len(cameras),
        "cameras": cameras
    }

@router.post("/camera/add")
def add_camera(user_data: camera.Create_Camera, db: Session = Depends(session.get_db)):
    token_verification = security.verify_token(user_data.jwt_token)

    if user_data.username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        INSERT INTO cameras (
            user_id, 
            name, 
            location, 
            video_url, 
            description, 
            is_private,
            floor_id
        )
        VALUES (
            :user_id, 
            :name, 
            :location, 
            :video_url, 
            :description, 
            :is_private,
            :floor_id
        )
        RETURNING name, video_url
    """)

    result = db.execute(query, {
        "user_id": user_data.user_id,
        "name": user_data.name,
        "location": user_data.location,
        "video_url": user_data.video_url,
        "description": user_data.description,
        "is_private": user_data.is_private,
        "floor_id": user_data.floor_id
    })

    result = result.fetchone()
    db.commit()

    return {
        "message": "Camera Added successfully",
        "name": result[0],
        "video_url": result[1]
    }