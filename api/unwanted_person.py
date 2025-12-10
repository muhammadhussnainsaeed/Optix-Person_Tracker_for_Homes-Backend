from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from db import session
from core import security
from schemas import unwanted_person

router = APIRouter(tags=["Unwanted Person"])

@router.get("/unwanted_person/fetch_all")
def fetch_list(username: str,jwt_token: str, user_id: str, db: Session = Depends(session.get_db)):

    token_verification= security.verify_token(jwt_token)

    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        SELECT 
                el.log_id,
                el.detected_at,
                el.exited_at,
                el.snapshot_url, 
                up.name AS person_name, 
                c.location AS room_name,
                f.title AS floor_title
            FROM event_logs el
            JOIN unwanted_persons up ON el.unwanted_person_id = up.id 
            LEFT JOIN cameras c ON el.camera_id = c.id
            LEFT JOIN floors f ON c.floor_id = f.id
            WHERE el.user_id = :user_id
              AND el.event_type = 'unwanted_detected'
            ORDER BY el.detected_at DESC
    """)

    result = db.execute(query, {"user_id": user_id})
    unwanted_person_list = result.mappings().all()

    return {
        "message": "Unwanted Person list fetched successfully",
        "count": len(unwanted_person_list),
        "unwanted_person_list": unwanted_person_list
    }

# @router.post("/unwanted-person/unmark")
# def unmark()