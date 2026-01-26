from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, null, Delete
from db import session
from core import security
from schemas import camera
from schemas.camera import Update_Camera, Delete_Camera, Update_Camera_Network

router = APIRouter(tags=["Camera"])

@router.get("/camera/fetch_all")
def fetch_list(username: str,jwt_token: str, user_id: str, db: Session = Depends(session.get_db)):

    token_verification= security.verify_token(jwt_token)

    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        SELECT id, name, location, description, video_url, is_private, floor_id
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
        RETURNING id, name, video_url
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
        "id": result[0],
        "name": result[1],
        "video_url": result[2]
    }

@router.put("/camera/update")
def update_camera(user_data: Update_Camera, db: Session = Depends(session.get_db)):
    # 1. Verify JWT Token
    token_verification = security.verify_token(user_data.jwt_token)

    if user_data.username != token_verification:
        raise HTTPException(status_code=401, detail="Verification Failed")

    # 2. Define the UPDATE Query
    query = text("""
                 UPDATE cameras
                 SET name        = :name,
                     location    = :location,
                     video_url   = :video_url,
                     description = :description,
                     is_private  = :is_private,
                     floor_id    = :floor_id
                 WHERE id = :camera_id
                   AND user_id = :user_id RETURNING id, name, video_url
                 """)

    # 3. Execute the Query
    result = db.execute(query, {
        "camera_id": user_data.camera_id,
        "user_id": user_data.user_id,
        "name": user_data.name,
        "location": user_data.location,
        "video_url": user_data.video_url,
        "description": user_data.description,
        "is_private": user_data.is_private,
        "floor_id": user_data.floor_id
    })

    updated_row = result.fetchone()

    # 4. Check if a row was actually updated
    if not updated_row:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Camera not found or you do not have permission to edit it"
        )

    db.commit()

    return {
        "message": "Camera updated successfully",
        "id": updated_row[0],
        "name": updated_row[1],
        "video_url": updated_row[2]
    }

@router.delete("/camera/delete")
def delete_camera(user_data: Delete_Camera, db: Session = Depends(session.get_db)):
    # 1. Verify JWT Token
    token_verification = security.verify_token(user_data.jwt_token)
    if user_data.username != token_verification:
        raise HTTPException(status_code=401, detail="Verification Failed")

    try:
        # Execute deletions for related tables first
        # We filter by camera_id.
        # Note: If you want to be extra safe, you could join cameras to verify user ownership here too,
        # but usually, the primary camera delete handles the ownership logic.

        db.execute(text("DELETE FROM event_logs WHERE camera_id = :c_id"), {"c_id": user_data.camera_id})
        print("Deleted from the EventLogs table")
        db.execute(text("DELETE FROM camera_links WHERE camera_id_to = :c_id OR camera_id_from = :c_id"), {"c_id": user_data.camera_id})
        print("Deleted from the CameraLinks table")

        # Final delete on the main table with user_id verification
        result = db.execute(text("""
                                 DELETE
                                 FROM cameras
                                 WHERE id = :c_id
                                   AND user_id = :u_id RETURNING id
                                 """), {"c_id": user_data.camera_id, "u_id": user_data.user_id})

        # If RETURNING id is empty, it means nothing was deleted (wrong ID or wrong User)
        if not result.fetchone():
            db.rollback()
            raise HTTPException(status_code=404, detail="Camera not found or unauthorized")

        db.commit()
        return {"status": "success", "message": "Camera and related logs purged."}

    except Exception as e:
        db.rollback()
        # Log the error internally here
        raise HTTPException(status_code=500, detail="Internal Server Error during deletion")

@router.get("/camera/network/fetch")
def fetch_camera_network(username: str,jwt_token: str, user_id: str,camera_id: str,  db: Session = Depends(session.get_db)):

    token_verification = security.verify_token(jwt_token)
    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    query = text("""
        SELECT 
        CASE 
        -- If the Input ID is in the 'FROM' column, take the 'TO' ID
            WHEN camera_id_from = :camera_id THEN camera_id_to
        -- If the Input ID is in the 'TO' column, take the 'FROM' ID
            ELSE camera_id_from 
        END AS connected_camera_id
            FROM camera_links
        WHERE camera_id_from = :camera_id OR camera_id_to = :camera_id
    """)

    result = db.execute(query, {"camera_id": camera_id})
    camera_links = result.mappings().all()

    return {
        "message": "Camera Links fetched successfully",
        "count": len(camera_links),
        "cameras": camera_links
    }

@router.get("/camera/graph")
def camera_graph(username: str, jwt_token: str, user_id: str, db: Session = Depends(session.get_db)):

    token_verification = security.verify_token(jwt_token)
    if username != token_verification:
        raise HTTPException(status_code=400, detail="Verification Failed")

    # 1. Fetch all cameras belonging to the user
    query = text("""
                 SELECT id
                 FROM cameras
                 WHERE user_id = :user_id
                 """)

    result = db.execute(query, {"user_id": user_id})
    camera_list = result.mappings().all()

    camera_graph_data = {}

    # 2. Iterate through each camera to find its neighbors
    for camera in camera_list:
        current_id = str(camera["id"])

        query_for_network = text("""
                                 SELECT CASE
                                            WHEN camera_id_from = :camera_id THEN camera_id_to
                                            ELSE camera_id_from
                                            END AS connected_camera_id
                                 FROM camera_links
                                 WHERE camera_id_from = :camera_id
                                    OR camera_id_to = :camera_id
                                 """)

        result2 = db.execute(query_for_network, {"camera_id": current_id})
        # Extract the IDs into a flat list of strings
        connections = [str(row["connected_camera_id"]) for row in result2.mappings().all()]

        # 3. Map the camera ID to its list of connections
        camera_graph_data[current_id] = connections

    return {
        "message": "Camera graph fetched successfully",
        "graph": camera_graph_data
    }

@router.put("/camera/network/update")
def update_camera_network(data: Update_Camera_Network, db: Session = Depends(session.get_db)):

    # 1. Verify Token
    token_verification = security.verify_token(data.jwt_token)
    if data.username != token_verification:
        raise HTTPException(status_code=401, detail="Verification Failed")

    try:
        # 2. Delete all existing links involving this camera
        delete_query = text("""
                            DELETE
                            FROM camera_links
                            WHERE camera_id_from = :camera_id
                               OR camera_id_to = :camera_id
                            """)
        db.execute(delete_query, {"camera_id": data.camera_id})

        # 3. Batch Insert new links
        if data.connected_camera_ids:
            insert_query = text("""
                                INSERT INTO camera_links (camera_id_from, camera_id_to)
                                VALUES (:camera_id, :target_id)
                                """)

            for target_id in data.connected_camera_ids:
                # Basic safety: don't link a camera to itself
                if target_id == data.camera_id:
                    continue

                db.execute(insert_query, {
                    "camera_id": data.camera_id,
                    "target_id": target_id
                })

        db.commit()
        return {
            "message": "Camera network updated successfully",
            "connected_count": len(data.connected_camera_ids)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update network: {str(e)}")

# @router.get("/camera/details")
# def camera_details(username: str,jwt_token: str, user_id: str, camera_id: str, db: Session = Depends(session.get_db)):
#     user_data = camera.Camera_Detail(
#         username=username,
#         user_id=user_id,
#         jwt_token=jwt_token,
#         camera_id=camera_id
#     )
#
#     token_verification = security.verify_token(user_data.jwt_token)
#
#     if user_data.username != token_verification:
#         raise HTTPException(status_code=400, detail="Verification Failed")
#
#     query = text("""
#             SELECT id, name, location, description, video_url, is_private
#             FROM cameras
#             WHERE id = :camera_id AND user_id = :user_id
#         """)
#
#     result = db.execute(query, {
#         "camera_id": user_data.camera_id,
#         "user_id": user_data.user_id
#     })
#     camera_detail = result.mappings().fetchone()
#
#     final_video_url = camera_detail["video_url"]
#     if bool(camera_detail["is_private"]):
#         final_video_url = None
#
#     return {
#         "message": "Camera Detail fetched successfully",
#         "id": str(camera_detail["id"]),
#         "name": camera_detail["name"],
#         "location": camera_detail["location"],  # Matches your DB schema
#         "description": camera_detail["description"],
#         "video_url": final_video_url
#     }