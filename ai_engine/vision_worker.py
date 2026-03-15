import os
import warnings

# 1. SUPPRESS NOISE FOR WINDOWS CHILD PROCESSES
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import tensorflow as tf

try:
    tf.config.set_visible_devices([], 'GPU')
except Exception:
    pass

import cv2
import time
import collections
from datetime import datetime
from ultralytics import YOLO

# Import your custom modules
from db.crud_events import log_event_start, log_event_end
from config import MODEL_PATH, PRE_ROLL_SECONDS, EVENTS_DIR, COOLDOWN_SECONDS
from ai_engine.face_recognition import identify_face


def camera_worker_process(camera_id: str, video_url: str, user_id: str, user_cache: dict, alert_queue):
    """
    Isolated GPU process for a single camera.
    Accepts 5 arguments now, including the multiprocessing alert_queue.
    """
    print(f"📹 [CAM {camera_id[-4:]}] Process started on GPU.")

    cap = cv2.VideoCapture(video_url)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps != fps: fps = 20.0

    buffer_size = int(fps * PRE_ROLL_SECONDS)
    frame_buffer = collections.deque(maxlen=buffer_size)

    # Init YOLO strictly on GPU
    try:
        model = YOLO(MODEL_PATH)
        model.to('cuda:0')
    except Exception as e:
        print(f"❌ [CAM {camera_id[-4:]}] YOLO Error: {e}")
        return

    is_recording = False
    event_id = None
    event_writer = None
    frames_since_last_seen = 0
    last_alert_time = 0

    while True:
        success, frame = cap.read()
        if not success:
            time.sleep(0.1)
            continue

        frame_buffer.append(frame)

        # YOLO Tracking
        results = model.track(frame, persist=True, verbose=False, device='cuda:0')

        person_detected = False
        det_id, det_type = None, "unwanted_detected"

        for r in results:
            if r.boxes is not None and len(r.boxes) > 0:
                boxes = r.boxes.xyxy.int().cpu().numpy()
                classes = r.boxes.cls.int().cpu().numpy()

                for box, cls in zip(boxes, classes):
                    if model.names[cls] == "human-face":
                        person_detected = True

                        # Only run Face Matching if we aren't already actively recording them
                        if not is_recording:
                            x1, y1, x2, y2 = map(int, box)
                            face_crop = frame[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10]

                            if face_crop.size > 0:
                                name, det_id, det_type = identify_face(face_crop, user_cache)

                                # --- WEBSOCKET ALERT LOGIC ---
                                if det_type == "unwanted_detected" or name == "Unknown":
                                    current_time = time.time()
                                    if current_time - last_alert_time > COOLDOWN_SECONDS:
                                        print(f"🚨 [CAM {camera_id[-4:]}] Intruder Alert: {name}")

                                        # Send to FastAPI Main Process
                                        alert_queue.put({
                                            "type": "alert",
                                            "camera_id": camera_id,
                                            "message": f"Intruder detected on camera {camera_id[-4:]}!",
                                            "timestamp": current_time
                                        })
                                        last_alert_time = current_time
                        break

        # --- VIDEO BUFFER LOGIC ---
        if person_detected:
            frames_since_last_seen = 0

            if not is_recording:
                is_recording = True
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_filename = os.path.join(EVENTS_DIR, f"{camera_id}_{timestamp}.mp4")

                h, w, _ = frame.shape
                event_writer = cv2.VideoWriter(video_filename, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

                # Write the 5-second time machine buffer
                for b_frame in frame_buffer:
                    event_writer.write(b_frame)

                print(f"🎥 [CAM {camera_id[-4:]}] Event started. Pre-roll dumped to {video_filename}")
                event_id = log_event_start(user_id, camera_id, det_id, det_type, video_filename)
            else:
                event_writer.write(frame)

        else:
            if is_recording:
                event_writer.write(frame)
                frames_since_last_seen += 1

                if frames_since_last_seen >= buffer_size:
                    print(f"🛑 [CAM {camera_id[-4:]}] Event ended. Video saved.")
                    is_recording = False
                    event_writer.release()
                    log_event_end(event_id)
                    event_id = None