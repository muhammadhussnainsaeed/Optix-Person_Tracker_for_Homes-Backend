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

@router.post("/family/add")
def add_family_member_with_photos(name: str = Form(...), relationship: str = Form(...), username: str = Form(...),
                                  jwt_token: str = Form(...),user_id: str = Form(...),files: List[UploadFile] = File(...),
                                  db: Session = Depends(session.get_db)):
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
        raise HTTPException(status_code=400, detail="You must upload exactly 3 persons.")

    try:
        person_type = "FAMILY"
        query_person = text("""
                    INSERT INTO persons (
                        user_id, 
                        name,
                        person_type
                    )
                    VALUES (
                        :user_id, 
                        :name,
                        :person_type
                    )
                    RETURNING id, name 
                """)

        result = db.execute(query_person,{
            "user_id": user_data.user_id,
            "name": user_data.name,
            "person_type": person_type
        })

        new_person_row= result.fetchone()
        new_person_id = new_person_row[0]
        new_person_name = new_person_row[1]

        # --- Step 1: Insert Family Member Details ---
        query_member = text("""
            INSERT INTO family_members (
                person_id,
                relationship
            )
            VALUES (
                :person_id,
                :relationship
            )
            RETURNING relationship 
        """)

        result = db.execute(query_member, {
            "person_id": new_person_id,
            "relationship": user_data.relationship,
        })

        # Capture the new ID
        new_person_row = result.fetchone()
        new_person_relationship = new_person_row[0]


        for index, file in enumerate(files):

            new_filename = f"{new_person_id}_{index}.png"

            save_path = f"media/persons/{new_filename}"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            # Save to disk
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            is_primary = False
            if index == 0:
                is_primary = True
            # Save path to DB
            query_photo = text("""
                INSERT INTO person_photos (
                    person_id, 
                    photo_url,
                    is_primary
                )
                VALUES (
                    :person_id, 
                    :photo_url,
                    :is_primary
                )
            """)

            db.execute(query_photo, {
                "person_id": new_person_id,
                "photo_url": save_path,
                "is_primary": is_primary
            })

        # --- Step 3: Commit ---
        db.commit()

        return {
            "message": "Family Member and Photos added successfully",
            "user_id": user_data.user_id,
            "member_id": str(new_person_id),
            "member_name": new_person_name,
            "member_relationship": new_person_relationship,
            "photos_saved": 3
        }

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Transaction failed.")


@router.put("/family/update")
def update_family_member_with_photos(person_id: int = Form(...),name: str = Form(...),relationship: str = Form(...),
        username: str = Form(...),jwt_token: str = Form(...),user_id: str = Form(...),
        files: List[UploadFile] = File(...),db: Session = Depends(session.get_db)):
    # --- 1. Security & Verification ---
    token_verification = security.verify_token(jwt_token)
    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    # Validation: Checking there must three Pictures
    if len(files) != 3:
        raise HTTPException(status_code=400, detail="You must upload exactly 3 persons.")

    try:

        # Ensure this person actually belongs to the user
        check_query = text("SELECT id FROM persons WHERE id = :person_id AND user_id = :user_id")
        result = db.execute(check_query, {"person_id": person_id, "user_id": user_id})

        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Family member not found.")

        # --- 3. Update Text Data ---

        # A. Update Name
        update_person = text("UPDATE persons SET name = :name WHERE id = :person_id")
        db.execute(update_person, {"name": name, "person_id": person_id})

        # B. Update Relationship
        update_member = text("UPDATE family_members SET relationship = :rel WHERE person_id = :person_id")
        db.execute(update_member, {"rel": relationship, "person_id": person_id})

        # --- 4. Replace Photos (The "Overwrite" Logic) ---

        # A. Find and DELETE old photos from Disk
        old_photos_query = text("SELECT photo_url FROM person_photos WHERE person_id = :person_id")
        old_rows = db.execute(old_photos_query, {"person_id": person_id}).fetchall()

        for row in old_rows:
            file_path = row[0]
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)  # Delete actual file
                except OSError:
                    pass  # Ignore if file was already gone

        # B. DELETE old photos from Database
        delete_query = text("DELETE FROM person_photos WHERE person_id = :person_id")
        db.execute(delete_query, {"person_id": person_id})

        # C. INSERT New Photos (Exactly like "Add" logic)
        for index, file in enumerate(files):
            # We assume these are fresh photos
            new_filename = f"{person_id}_{index}_v2.png"
            save_path = f"media/persons/{new_filename}"

            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            # Save new file to disk
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            # First photo is primary
            is_primary = (index == 0)

            # Insert into DB
            insert_photo = text("""
                                INSERT INTO person_photos (person_id, photo_url, is_primary)
                                VALUES (:person_id, :photo_url, :is_primary)
                                """)
            db.execute(insert_photo, {
                "person_id": person_id,
                "photo_url": save_path,
                "is_primary": is_primary
            })

        # --- 5. Commit ---
        db.commit()

        return {
            "message": "Family member fully updated",
            "person_id": person_id,
            "name": name,
            "relationship": relationship,
            "photos_replaced": 3
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        print(f"Update Error: {e}")
        raise HTTPException(status_code=500, detail="Transaction failed.")

@router.get("/family/fetch_all")
def fetch_list(username: str,jwt_token: str, user_id: str, db: Session = Depends(session.get_db)):

    token_verification= security.verify_token(jwt_token)

    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        SELECT 
            p.id, 
            p.name, 
            f.relationship,
            ph.photo_url
        FROM persons p
        JOIN family_members f ON p.id = f.person_id
        LEFT JOIN person_photos ph ON p.id = ph.person_id AND ph.is_primary = TRUE
        WHERE p.user_id = :user_id 
          AND p.person_type = 'FAMILY'
    """)

    result = db.execute(query, {"user_id": user_id})
    family_members = result.mappings().all()

    return {
        "message": "Family Members fetched successfully",
        "count": len(family_members),
        "family_members": family_members
    }
