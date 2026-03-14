import os
import time
from multiprocessing import Queue

import cv2
from deepface import DeepFace
from ultralytics import YOLO

# --- CONFIGURATION ---
MODEL_PATH = "ai_engine/weights/best.pt"  # Adjust path if your model is elsewhere
DB_PATH = "media/persons"  # Folder containing known family photos
CAMERA_SOURCE = 0  # 0 for webcam, or an IP/RTSP link
COOLDOWN_SECONDS = 15  # How long to wait before re-alerting the same unknown person


def run_ai_worker(alert_queue: Queue):
    print("🤖 [AI WORKER] Initializing AI Engine...")

    # 1. Load YOLO Model
    try:
        model = YOLO(MODEL_PATH)
    except Exception as e:
        print(f"❌ [AI WORKER] Failed to load YOLO: {e}")
        return

    # Ensure DeepFace DB path exists
    os.makedirs(DB_PATH, exist_ok=True)

    # 2. State Memory (The "ID Lock")
    # Keeps track of who is who: { track_id: "Hussnain" or "Unknown" }
    known_tracks = {}

    # Cooldown memory to prevent spamming the WebSocket
    last_alert_time = 0

    # 3. Connect to Camera
    cap = cv2.VideoCapture(CAMERA_SOURCE)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("❌ [AI WORKER] Could not connect to camera.")
        return

    print("🎥 [AI WORKER] Video stream active. Running detection...")

    while True:
        success, frame = cap.read()
        if not success:
            print("⚠️ [AI WORKER] Frame drop. Retrying...")
            time.sleep(1)
            continue

        # 4. YOLO Inference with TRACKING enabled (persist=True)
        # We use stream=True for memory efficiency in while loops
        results = model.track(frame, persist=True, tracker="botsort.yaml", verbose=False, stream=True)

        for result in results:
            # If no boxes or no tracking IDs yet, skip
            if result.boxes is None or result.boxes.id is None:
                continue

            boxes = result.boxes.xyxy.cpu().numpy()  # Bounding box coordinates
            track_ids = result.boxes.id.int().cpu().numpy()  # Tracking IDs
            class_ids = result.boxes.cls.int().cpu().numpy()  # Class IDs (e.g., Person, Face)

            for box, track_id, class_id in zip(boxes, track_ids, class_ids):
                class_name = model.names[class_id]

                # We only want to run DeepFace if YOLO detects a "human-face"
                if class_name == "human-face":

                    # --- SCENARIO 1: We ALREADY know who this is ---
                    if track_id in known_tracks:
                        identity = known_tracks[track_id]
                        # Just draw the name on the screen
                        draw_box(frame, box, identity, (0, 255, 0) if identity != "Unknown" else (0, 0, 255))

                        # Trigger alert logic if it's an intruder
                        if identity == "Unknown":
                            current_time = time.time()
                            if current_time - last_alert_time > COOLDOWN_SECONDS:
                                print(f"🚨 [AI WORKER] Unknown person detected! (ID: {track_id})")

                                # Send to FastAPI
                                alert_queue.put({
                                    "type": "alert",
                                    "room": "Living Room",
                                    "message": "Intruder Alert!",
                                    "timestamp": current_time
                                })
                                last_alert_time = current_time

                                # TODO: Save to PostgreSQL EventLog here

                    # --- SCENARIO 2: A NEW face we haven't checked yet ---
                    else:
                        print(f"🔍 [AI WORKER] New face detected (ID: {track_id}). Analyzing...")

                        # 1. Crop the face from the frame using bounding box coordinates
                        x1, y1, x2, y2 = map(int, box)
                        # Add a small buffer around the face for better DeepFace accuracy
                        face_crop = frame[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10]

                        if face_crop.size == 0:
                            continue

                        # 2. Run DeepFace (enforce_detection=False because YOLO already found the face)
                        try:
                            df_result = DeepFace.find(
                                img_path=face_crop,
                                db_path=DB_PATH,
                                model_name="VGG-Face",  # Fast and reliable model
                                enforce_detection=False,
                                silent=True
                            )

                            # 3. Evaluate the result
                            if len(df_result) > 0 and not df_result[0].empty:
                                # Match found! Extract the filename (e.g., 'hussnain.jpg' -> 'hussnain')
                                matched_file = df_result[0]['identity'][0]
                                identity = os.path.basename(matched_file).split('.')[0]
                                print(f"✅ [AI WORKER] Match found: {identity}")
                            else:
                                identity = "Unknown"
                                print(f"❌ [AI WORKER] No match. Marked as Unknown.")

                        except Exception as e:
                            print(f"⚠️ [AI WORKER] DeepFace Error: {e}")
                            identity = "Unknown"

                        # 4. Save to State Memory so we don't check this ID again!
                        known_tracks[track_id] = identity

        # (Optional) Display the frame for debugging on your local machine
        cv2.imshow("Optix AI Vision", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


def draw_box(img, box, text, color):
    """Helper function to draw clean bounding boxes."""
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    cv2.putText(img, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)