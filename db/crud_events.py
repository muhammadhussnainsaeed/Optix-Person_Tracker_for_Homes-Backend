import uuid
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.session import SessionLocal

def log_event_start(user_id: str, camera_id: str, person_id: str, event_type: str, video_path: str) -> str:
    db: Session = SessionLocal()
    event_id = str(uuid.uuid4())
    try:
        query = text("""
            INSERT INTO event_logs (id, user_id, camera_id, person_id, event_type, snapshot_url, detected_at)
            VALUES (:id, :uid, :cid, :pid, :evt, :path, NOW())
        """)
        db.execute(query, {
            "id": event_id,
            "uid": user_id,
            "cid": camera_id,
            "pid": person_id if person_id else None,
            "evt": event_type,
            "path": video_path
        })
        db.commit()
        return event_id
    except Exception as e:
        print(f"❌ [DB] Failed to log event start: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def log_event_end(event_id: str):
    if not event_id: return
    db: Session = SessionLocal()
    try:
        query = text("UPDATE event_logs SET exited_at = NOW() WHERE id = :id")
        db.execute(query, {"id": event_id})
        db.commit()
    except Exception as e:
        print(f"❌ [DB] Failed to log event end: {e}")
        db.rollback()
    finally:
        db.close()