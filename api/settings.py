from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core import security
from db import session
from schemas import settings

router = APIRouter(tags=["Settings"])

@router.put("/settings/update_name")
def update_name(user_data: settings.UpdateName, db: Session = Depends(session.get_db)):

    token_verification = security.verify_token(user_data.jwt_token)

    if user_data.username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
                 UPDATE users
                 SET name = :name
                 WHERE id = :user_id
                   AND username = :username RETURNING name
                 """)

    # 3. Execute the Query
    result = db.execute(query, {
        "name": user_data.name,
        "user_id": user_data.user_id,
        "username": user_data.username
    })

    updated_row = result.fetchone()

    # 4. Check if a row was actually updated
    if not updated_row:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="User not found or you do not have permission to edit it"
        )

    db.commit()

    return {
        "message": "Name Updated Successfully",
        "name": updated_row[0]
    }

@router.put("/settings/update_password")
def update_password(user_data: settings.UpdatePassword, db: Session = Depends(session.get_db)):

    token_verification = security.verify_token(user_data.jwt_token)

    if user_data.username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    check_user_query = text("SELECT id,hashed_password FROM users WHERE username = :username and id = :userid")

    result = db.execute(check_user_query, {"username": user_data.username, "userid": user_data.user_id}).fetchone()

    if not result:
        raise HTTPException(status_code=400, detail="Username not exists")

    if not security.verify_password(user_data.old_password,result[1]):
        raise HTTPException(status_code=400, detail="Incorrect Password")

    hashed_password = security.hash_password(user_data.new_password)

    insert_query = text("""
        UPDATE users
        SET
            hashed_password = :hashed_password
        WHERE username = :username
            RETURNING id;
            """)

    try:
        result = db.execute(insert_query, {
            "username": user_data.username,
            "hashed_password": hashed_password
        })

        user_id = result.fetchone()[0]
        db.commit()

        return {
            "message": "User password updated successfully",
            "username": user_id
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Updating failed")

    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


from sqlalchemy.exc import IntegrityError
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text


# Assuming router, security, settings, and session are defined elsewhere

@router.put("/settings/update_security_question_answer")
def update_security_question_answer(user_data: settings.UpdateSecurityQuestionAnswer,
                                    db: Session = Depends(session.get_db)):
    # 1. Verify Token
    token_verification = security.verify_token(user_data.jwt_token)
    if user_data.username != token_verification:
        raise HTTPException(status_code=401, detail="Verification Failed")

    # 2. Fetch User & Verify Identity
    check_user_query = text("""
                            SELECT id, hashed_password
                            FROM users
                            WHERE username = :username
                              AND id = :id
                            """)

    user_record = db.execute(check_user_query, {
        "username": user_data.username,
        "id": user_data.user_id
    }).fetchone()

    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")

    # Access tuple/Row elements safely (index 1 is hashed_password)
    if not security.verify_password(user_data.password, user_record[1]):
        raise HTTPException(status_code=401, detail="Incorrect Password")

    # 3. Hash Answer & Update
    hashed_answer = security.hash_password(user_data.security_answer)

    # Use the Primary Key (id) for the WHERE clause instead of username
    update_query = text("""
                        UPDATE users
                        SET hashed_security_answer     = :hashed_answer,
                            security_question = :security_question
                        WHERE id = :id RETURNING id;
                        """)

    try:
        result = db.execute(update_query, {
            "hashed_answer": hashed_answer,
            "security_question": user_data.security_question,
            "id": user_data.user_id
        })

        updated_row = result.fetchone()

        if not updated_row:
            db.rollback()
            raise HTTPException(status_code=400, detail="Update failed, user may have been deleted.")

        updated_id = updated_row[0]
        db.commit()

        return {
            "message": "User Security Q&A updated successfully",
            "id": updated_id
        }

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Database integrity error during update")

    except Exception as e:
        db.rollback()
        # Log the actual exception 'e' internally here for debugging
        raise HTTPException(status_code=500, detail="Internal server error")