import os
import warnings
import time
import collections
import shutil
import queue
from datetime import datetime
import cv2
import threading
import numpy as np  # Added for the background cache updater

# SUPPRESS NOISE
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import tensorflow as tf

try:
    tf.config.set_visible_devices([], 'GPU')
except Exception:
    pass

from ultralytics import YOLO

from db.crud_events import log_event_start, log_event_end, create_unknown_person
from config import MODEL_PATH, PRE_ROLL_SECONDS, EVENTS_DIR, COOLDOWN_SECONDS
from ai_engine.face_recognition import identify_face, FaceCache
from db.session import SessionLocal  # Added to allow the background thread to fetch new data
from sqlalchemy import text

# Define our new directory structure
TEMP_DIR = "media/temp"
FAMILY_DIR = os.path.join(EVENTS_DIR, "family")
UNWANTED_DIR = os.path.join(EVENTS_DIR, "unwanted")

# Ensure directories exist
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(FAMILY_DIR, exist_ok=True)
os.makedirs(UNWANTED_DIR, exist_ok=True)


# --- BACKGROUND DISK WRITER ---
def disk_writer_thread(filename, fps, width, height, frame_queue):
    """Saves frames to disk in the background so the camera NEVER drops a frame."""
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    while True:
        frame = frame_queue.get()
        if frame is None:  # None is our signal to stop recording
            break
        writer.write(frame)

    writer.release()


def camera_worker_process(camera_id: str, camera_name: str, video_url: str, user_id: str, user_cache: dict,
                          alert_queue, command_queue):
    print(f"📹 [{camera_name}] Process started. Verifying connection...")

    # --- NEW: FAKE/DEAD LINK CHECK ---
    cap = cv2.VideoCapture(video_url)

    if not cap.isOpened():
        print(f"❌ [{camera_name}] DEAD LINK! Cannot connect to {video_url}. Shutting down worker to save resources.")
        return

    # Try reading a single frame to ensure it's not a fake/empty stream
    success, _ = cap.read()
    if not success:
        print(f"❌ [{camera_name}] FAKE STREAM! Connected but receiving no video data. Shutting down worker.")
        cap.release()
        return

    # If we made it here, the link is valid and transmitting.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps != fps: fps = 20.0

    buffer_size = int(fps * PRE_ROLL_SECONDS)
    frame_buffer = collections.deque(maxlen=buffer_size)

    try:
        model = YOLO(MODEL_PATH)
        model.to('cuda:0')
    except Exception as e:
        print(f"❌ [CAM] YOLO Error: {e}")
        return

    # --- VIDEO RECORDING STATE ---
    is_recording = False
    temp_filename = ""
    event_timestamp = ""
    frames_since_last_seen = 0

    # Queue for our background video writer
    video_write_queue = None
    video_thread = None

    # --- AI IDENTIFICATION STATE ---
    is_identifying = False
    alert_sent_this_event = False
    identity_locked = False

    current_match_name = "Unknown"
    current_match_id = None
    current_match_type = "UNWANTED"

    def face_identification_task(crop_img):
        nonlocal is_identifying, alert_sent_this_event, identity_locked
        nonlocal current_match_name, current_match_id, current_match_type

        try:
            name, det_id, det_type = identify_face(crop_img, user_cache)
            current_time = datetime.now().isoformat()

            if name != "Unknown":
                print(f"✅ [{camera_name}] AI Identified: {name} ({det_type})")
                current_match_name = name
                current_match_id = det_id
                current_match_type = det_type

                if det_type == "UNWANTED" and not alert_sent_this_event:
                    alert_queue.put({
                        "type": "alert",
                        "user_id": user_id,
                        "person_id": current_match_id,
                        "camera_id": camera_id,
                        "camera_name": camera_name,
                        "person_name": current_match_name,
                        "timestamp": current_time
                    })
                    alert_sent_this_event = True
            else:
                print(f"🚨 [{camera_name}] Unknown face! Generating new profile...")

                # --- CHANGED: Unpack the ID and the new UI name ---
                new_pid, generated_name = create_unknown_person(user_id, crop_img)

                if new_pid:
                    # --- CHANGED: Use the generated name instead of "Unknown_Intruder" ---
                    current_match_name = generated_name
                    current_match_id = new_pid
                    current_match_type = "UNWANTED"

                    # Cache the new intruder immediately for the current loop
                    try:
                        from deepface import DeepFace
                        rep = DeepFace.represent(img_path=crop_img, model_name="ArcFace", enforce_detection=False)[0]
                        user_cache[new_pid] = {
                            "name": generated_name,  # --- CHANGED: Cache the UI name ---
                            "type": "UNWANTED",
                            "embedding": rep["embedding"]
                        }
                    except Exception as e:
                        print(f"⚠️ Could not cache new intruder: {e}")

                    if not alert_sent_this_event:
                        alert_queue.put({
                            "type": "alert",
                            "user_id": user_id,
                            "person_id": current_match_id,
                            "camera_id": camera_id,
                            "camera_name": camera_name,
                            "person_name": current_match_name,
                            "timestamp": current_time
                        })
                        alert_sent_this_event = True

            identity_locked = True
        except Exception as e:
            import traceback
            print(f"❌ [THREAD ERROR] Face ID Failed: {traceback.format_exc()}")
        finally:
            is_identifying = False

    while True:
        # --- NEW: IPC COMMAND QUEUE MAILBOX CHECK ---
        try:
            cmd = command_queue.get_nowait()
            if cmd.get("action") == "RELOAD_FACES" and cmd.get("user_id") == user_id:
                print(f"🔄 [{camera_name}] RELOAD COMMAND RECEIVED! Fetching fresh faces from DB...")

                # Fetch new data using the helper from face_recognition.py
                new_cache = FaceCache.get_updated_user_cache(user_id)

                # Safely update the dictionary in memory
                user_cache.clear()
                user_cache.update(new_cache)
                print(f"✅ [{camera_name}] Memory synced instantly.")
        except queue.Empty:
            pass  # No messages, just proceed to read the video frame normally

        success, frame = cap.read()
        if not success:
            time.sleep(0.01)
            continue

        frame_buffer.append(frame)
        results = model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False, device='cuda:0')

        person_in_frame = False
        face_box = None

        for r in results:
            if r.boxes is not None and len(r.boxes) > 0:
                boxes = r.boxes.xyxy.int().cpu().numpy()
                classes = r.boxes.cls.int().cpu().numpy()

                for box, cls in zip(boxes, classes):
                    class_name = model.names[cls]
                    if class_name == "person":
                        person_in_frame = True
                    if class_name == "human-face" and face_box is None:
                        face_box = box

        # --- EVENT LOGIC ---
        if person_in_frame:
            frames_since_last_seen = 0

            if not is_recording:
                # 1. START RECORDING NON-BLOCKING
                is_recording = True
                identity_locked = False
                alert_sent_this_event = False

                current_match_name = "Unknown"
                current_match_id = None
                current_match_type = "UNWANTED"

                event_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_filename = os.path.join(TEMP_DIR, f"temp_{camera_id}_{event_timestamp}.mp4")

                h, w, _ = frame.shape

                # Start the background Disk Writer thread
                video_write_queue = queue.Queue()
                video_thread = threading.Thread(target=disk_writer_thread,
                                                args=(temp_filename, fps, w, h, video_write_queue))
                video_thread.start()

                # Instantly dump the pre-roll to the queue (virtually 0 delay)
                for b_frame in frame_buffer:
                    video_write_queue.put(b_frame)

                print(f"🎥 [{camera_name}] Person entered. Recording dynamically to temp buffer...")
            else:
                # Keep sending frames to the queue
                video_write_queue.put(frame)

                # 2. RUN BACKGROUND FACE HUNT
                if not identity_locked and not is_identifying and face_box is not None:
                    is_identifying = True
                    x1, y1, x2, y2 = map(int, face_box)
                    face_crop = frame[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10].copy()

                    if face_crop.size > 0:
                        threading.Thread(target=face_identification_task, args=(face_crop,)).start()
                    else:
                        is_identifying = False
        else:

            if is_recording:
                video_write_queue.put(frame)
                frames_since_last_seen += 1

                if frames_since_last_seen >= buffer_size:
                    # 3. PERSON LEFT - STOP DISK WRITER
                    is_recording = False
                    # Signal the disk writer thread to finish and close the file
                    video_write_queue.put(None)
                    video_thread.join()  # Wait a split second to ensure it safely closed the file
                    safe_name = current_match_name.replace(" ", "_")
                    final_filename = f"{safe_name}_{event_timestamp}.mp4"

                    # Decide paths based on person type
                    if current_match_type == "FAMILY":
                        final_path = os.path.join(FAMILY_DIR, final_filename)  # Full path for Windows to move the file
                        db_video_path = f"media/events/family/{final_filename}"  # Clean path for PostgreSQL
                    else:
                        final_path = os.path.join(UNWANTED_DIR, final_filename)
                        db_video_path = f"media/events/unwanted/{final_filename}"

                    # Move the file on the hard drive using the full absolute path
                    shutil.move(temp_filename, final_path)
                    print(f"🛑 [{camera_name}] Event ended. Saved locally to: {final_path}")
                    # 4. WRITE TO DATABASE
                    db_event_string = f"{current_match_type.lower()}_detected"
                    event_id = log_event_start(
                        user_id=user_id,
                        camera_id=camera_id,
                        person_id=current_match_id,
                        event_type=db_event_string,
                        video_path=db_video_path  # <-- FIX: Save ONLY the clean relative path to the DB!
                    )
                    log_event_end(event_id)

##Old Function
# def camera_worker_process(camera_id: str, camera_name: str, video_url: str, user_id: str, user_cache: dict,
#                           alert_queue):
#     print(f"📹 [{camera_name}] Process started. Verifying connection...")
#
#     # --- NEW: FAKE/DEAD LINK CHECK ---
#     cap = cv2.VideoCapture(video_url)
#
#     if not cap.isOpened():
#         print(f"❌ [{camera_name}] DEAD LINK! Cannot connect to {video_url}. Shutting down worker to save resources.")
#         return
#
#     # Try reading a single frame to ensure it's not a fake/empty stream
#     success, _ = cap.read()
#     if not success:
#         print(f"❌ [{camera_name}] FAKE STREAM! Connected but receiving no video data. Shutting down worker.")
#         cap.release()
#         return
#
#     # If we made it here, the link is valid and transmitting.
#     cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
#
#     fps = cap.get(cv2.CAP_PROP_FPS)
#     if not fps or fps != fps: fps = 20.0
#
#     buffer_size = int(fps * PRE_ROLL_SECONDS)
#     frame_buffer = collections.deque(maxlen=buffer_size)
#
#     try:
#         model = YOLO(MODEL_PATH)
#         model.to('cuda:0')
#     except Exception as e:
#         print(f"❌ [CAM] YOLO Error: {e}")
#         return
#
#     # --- NEW: BACKGROUND CACHE UPDATER ---
#     def auto_update_cache_task():
#         """Periodically fetches new database records every 5 minutes to keep AI updated without restarting."""
#         from deepface import DeepFace
#         while True:
#             time.sleep(300)  # Wait 5 minutes
#             try:
#                 db = SessionLocal()
#                 raw_query = text("""
#                                     SELECT p.id AS person_id, p.name, p.person_type, pp.photo_url
#                                     FROM persons p
#                                     JOIN person_photos pp ON p.id = pp.person_id
#                                     WHERE p.user_id = CAST(:uid AS uuid)
#                                 """)
#                 results = db.execute(raw_query, {"uid": user_id}).fetchall()
#                 db.close()
#
#                 # Group photos by person
#                 person_data = {}
#                 for row in results:
#                     pid = str(row.person_id)
#                     person_data.setdefault(pid, {"name": row.name, "type": row.person_type, "photos": []})
#                     person_data[pid]["photos"].append(row.photo_url)
#
#                 new_cache = {}
#                 for pid, data in person_data.items():
#                     # If person is already in our cache perfectly, skip math to save CPU
#                     if pid in user_cache and user_cache[pid]["name"] == data["name"]:
#                         new_cache[pid] = user_cache[pid]
#                         continue
#
#                     # Otherwise, calculate new embeddings for the new/updated person
#                     embeddings = []
#                     for photo_path in data["photos"]:
#                         try:
#                             rep = \
#                             DeepFace.represent(img_path=photo_path, model_name="ArcFace", enforce_detection=False)[0]
#                             embeddings.append(rep["embedding"])
#                         except Exception:
#                             pass
#
#                     if embeddings:
#                         new_cache[pid] = {
#                             "name": data["name"],
#                             "type": data["type"],
#                             "embedding": np.mean(embeddings, axis=0)
#                         }
#
#                 # Update the live memory dict in-place safely
#                 user_cache.clear()
#                 user_cache.update(new_cache)
#                 print(f"🔄 [{camera_name}] Memory synced. AI knows the latest faces.")
#             except Exception as e:
#                 print(f"⚠️ [{camera_name}] Background cache sync failed: {e}")
#
#     # Start the auto-updater as a background daemon
#     updater_thread = threading.Thread(target=auto_update_cache_task, daemon=True)
#     updater_thread.start()
#
#     # --- VIDEO RECORDING STATE ---
#     is_recording = False
#     temp_filename = ""
#     event_timestamp = ""
#     frames_since_last_seen = 0
#
#     # Queue for our background video writer
#     video_write_queue = None
#     video_thread = None
#
#     # --- AI IDENTIFICATION STATE ---
#     is_identifying = False
#     alert_sent_this_event = False
#     identity_locked = False
#
#     current_match_name = "Unknown"
#     current_match_id = None
#     current_match_type = "UNWANTED"
#
#     def face_identification_task(crop_img):
#         nonlocal is_identifying, alert_sent_this_event, identity_locked
#         nonlocal current_match_name, current_match_id, current_match_type
#
#         try:
#             name, det_id, det_type = identify_face(crop_img, user_cache)
#             current_time = datetime.now().isoformat()
#
#             if name != "Unknown":
#                 print(f"✅ [{camera_name}] AI Identified: {name} ({det_type})")
#                 current_match_name = name
#                 current_match_id = det_id
#                 current_match_type = det_type
#
#                 if det_type == "UNWANTED" and not alert_sent_this_event:
#                     alert_queue.put({
#                         "type": "alert",
#                         "user_id": user_id,
#                         "person_id": current_match_id,
#                         "camera_id": camera_id,
#                         "camera_name": camera_name,
#                         "person_name": current_match_name,
#                         "timestamp": current_time
#                     })
#                     alert_sent_this_event = True
#             else:
#                 print(f"🚨 [{camera_name}] Unknown face! Generating new profile...")
#
#                 # --- CHANGED: Unpack the ID and the new UI name ---
#                 new_pid, generated_name = create_unknown_person(user_id, crop_img)
#
#                 if new_pid:
#                     # --- CHANGED: Use the generated name instead of "Unknown_Intruder" ---
#                     current_match_name = generated_name
#                     current_match_id = new_pid
#                     current_match_type = "UNWANTED"
#
#                     # Cache the new intruder immediately for the current loop
#                     try:
#                         from deepface import DeepFace
#                         rep = DeepFace.represent(img_path=crop_img, model_name="ArcFace", enforce_detection=False)[0]
#                         user_cache[new_pid] = {
#                             "name": generated_name,  # --- CHANGED: Cache the UI name ---
#                             "type": "UNWANTED",
#                             "embedding": rep["embedding"]
#                         }
#                     except Exception as e:
#                         print(f"⚠️ Could not cache new intruder: {e}")
#
#                     if not alert_sent_this_event:
#                         alert_queue.put({
#                             "type": "alert",
#                             "user_id": user_id,
#                             "person_id": current_match_id,
#                             "camera_id": camera_id,
#                             "camera_name": camera_name,
#                             "person_name": current_match_name,
#                             "timestamp": current_time
#                         })
#                         alert_sent_this_event = True
#
#             identity_locked = True
#         except Exception as e:
#             import traceback
#             print(f"❌ [THREAD ERROR] Face ID Failed: {traceback.format_exc()}")
#         finally:
#             is_identifying = False
#
#     while True:
#         success, frame = cap.read()
#         if not success:
#             time.sleep(0.01)
#             continue
#
#         frame_buffer.append(frame)
#         results = model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False, device='cuda:0')
#
#         person_in_frame = False
#         face_box = None
#
#         for r in results:
#             if r.boxes is not None and len(r.boxes) > 0:
#                 boxes = r.boxes.xyxy.int().cpu().numpy()
#                 classes = r.boxes.cls.int().cpu().numpy()
#
#                 for box, cls in zip(boxes, classes):
#                     class_name = model.names[cls]
#                     if class_name == "person":
#                         person_in_frame = True
#                     if class_name == "human-face" and face_box is None:
#                         face_box = box
#
#         # --- EVENT LOGIC ---
#         if person_in_frame:
#             frames_since_last_seen = 0
#
#             if not is_recording:
#                 # 1. START RECORDING NON-BLOCKING
#                 is_recording = True
#                 identity_locked = False
#                 alert_sent_this_event = False
#
#                 current_match_name = "Unknown"
#                 current_match_id = None
#                 current_match_type = "UNWANTED"
#
#                 event_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#                 temp_filename = os.path.join(TEMP_DIR, f"temp_{camera_id}_{event_timestamp}.mp4")
#
#                 h, w, _ = frame.shape
#
#                 # Start the background Disk Writer thread
#                 video_write_queue = queue.Queue()
#                 video_thread = threading.Thread(target=disk_writer_thread,
#                                                 args=(temp_filename, fps, w, h, video_write_queue))
#                 video_thread.start()
#
#                 # Instantly dump the pre-roll to the queue (virtually 0 delay)
#                 for b_frame in frame_buffer:
#                     video_write_queue.put(b_frame)
#
#                 print(f"🎥 [{camera_name}] Person entered. Recording dynamically to temp buffer...")
#             else:
#                 # Keep sending frames to the queue
#                 video_write_queue.put(frame)
#
#                 # 2. RUN BACKGROUND FACE HUNT
#                 if not identity_locked and not is_identifying and face_box is not None:
#                     is_identifying = True
#                     x1, y1, x2, y2 = map(int, face_box)
#                     face_crop = frame[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10].copy()
#
#                     if face_crop.size > 0:
#                         threading.Thread(target=face_identification_task, args=(face_crop,)).start()
#                     else:
#                         is_identifying = False
#         else:
#
#             if is_recording:
#                 video_write_queue.put(frame)
#                 frames_since_last_seen += 1
#
#                 if frames_since_last_seen >= buffer_size:
#                     # 3. PERSON LEFT - STOP DISK WRITER
#                     is_recording = False
#                     # Signal the disk writer thread to finish and close the file
#                     video_write_queue.put(None)
#                     video_thread.join()  # Wait a split second to ensure it safely closed the file
#                     safe_name = current_match_name.replace(" ", "_")
#                     final_filename = f"{safe_name}_{event_timestamp}.mp4"
#
#                     # Decide paths based on person type
#                     if current_match_type == "FAMILY":
#                         final_path = os.path.join(FAMILY_DIR, final_filename)  # Full path for Windows to move the file
#                         db_video_path = f"media/events/family/{final_filename}"  # Clean path for PostgreSQL
#                     else:
#                         final_path = os.path.join(UNWANTED_DIR, final_filename)
#                         db_video_path = f"media/events/unwanted/{final_filename}"
#
#                     # Move the file on the hard drive using the full absolute path
#                     shutil.move(temp_filename, final_path)
#                     print(f"🛑 [{camera_name}] Event ended. Saved locally to: {final_path}")
#                     # 4. WRITE TO DATABASE
#                     db_event_string = f"{current_match_type.lower()}_detected"
#                     event_id = log_event_start(
#                         user_id=user_id,
#                         camera_id=camera_id,
#                         person_id=current_match_id,
#                         event_type=db_event_string,
#                         video_path=db_video_path  # <-- FIX: Save ONLY the clean relative path to the DB!
#                     )
#                     log_event_end(event_id)