from db import session
from core import security
from schemas import family
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List
import shutil
import os

router = APIRouter(tags=["Family"])

# @router.post("/family/add")
# def add_camera(user_data: family.AddFamilyMember, db: Session = Depends(session.get_db)):
#     token_verification = security.verify_token(user_data.jwt_token)
#
#     if user_data.username != token_verification:
#         raise HTTPException(status_code=400, detail="Verification Failed")
#
#     query = text("""
#         INSERT INTO family_members (
#             user_id,
#             name,
#             relationship
#         )
#         VALUES (
#             :user_id,
#             :name,
#             :relationship
#         )
#         RETURNING user_id, name
#     """)
#
#     result = db.execute(query, {
#         "user_id": user_data.user_id,
#         "name": user_data.name,
#         "relationship": user_data.relationship,
#     })
#
#     result = result.fetchone()
#     db.commit()
#
#     return {
#         "message": "Family Member Added successfully",
#         "user_id": str(result[0]),
#         "name": result[1]
#     }
@router.post("/family/add")
def add_family_member_with_photos(
        # We take inputs as Form(...) to handle Multipart data
        name: str = Form(...),
        relationship: str = Form(...),
        username: str = Form(...),
        jwt_token: str = Form(...),
        user_id: str = Form(...),
        files: List[UploadFile] = File(...),
        db: Session = Depends(session.get_db)
):
    # 2. Pack Form data into your Pydantic model for validation/usage
    user_data = family.AddFamilyMember(
        name=name,
        relationship=relationship,
        username=username,
        jwt_token=jwt_token,
        user_id=user_id
    )

    # --- Verification ---
    token_verification = security.verify_token(user_data.jwt_token)
    if user_data.username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    if len(files) != 3:
        raise HTTPException(status_code=400, detail="You must upload exactly 3 photos.")

    try:
        # --- Step 1: Insert Family Member Details ---
        query_member = text("""
            INSERT INTO family_members (
                user_id, 
                name, 
                relationship
            )
            VALUES (
                :user_id, 
                :name, 
                :relationship
            )
            RETURNING id, name 
        """)

        result = db.execute(query_member, {
            "user_id": user_data.user_id,
            "name": user_data.name,
            "relationship": user_data.relationship,
        })

        # Capture the new ID
        new_member_row = result.fetchone()
        new_member_id = new_member_row[0]

        # --- Step 2: Save Images (Renamed by Member ID) ---
        # We use 'enumerate' to get an index (0, 1, 2) to ensure unique names
        for index, file in enumerate(files):
            # Logic: Rename file to {member_id}_{index}_{original_name}
            # Example: "55_0_selfie.png"
            new_filename = f"{new_member_id}_{index}.png"

            save_path = f"uploads/photos/{new_filename}"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            # Save to disk
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            # Save path to DB
            query_photo = text("""
                INSERT INTO family_member_photos (
                    family_member_id, 
                    photo_url
                )
                VALUES (
                    :member_id, 
                    :photo_url
                )
            """)

            db.execute(query_photo, {
                "member_id": new_member_id,
                "photo_url": save_path
            })

        # --- Step 3: Commit ---
        db.commit()

        return {
            "message": "Family Member and Photos added successfully",
            "user_id": user_data.user_id,
            "member_id": str(new_member_id),
            "photos_saved": 3
        }

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Transaction failed.")

@router.get("/family/fetch_all")
def fetch_list(username: str,jwt_token: str, user_id: str, db: Session = Depends(session.get_db)):

    token_verification= security.verify_token(jwt_token)

    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        SELECT id, name, relationship
        FROM family_members
        WHERE user_id = :user_id
    """)

    result = db.execute(query, {"user_id": user_id})
    family_members = result.mappings().all()

    return {
        "message": "Family Members fetched successfully",
        "count": len(family_members),
        "cameras": family_members
    }
