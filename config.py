import os

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "ai_engine/weights/best.pt")
DB_PATH = os.path.join(BASE_DIR, "media/persons")
EVENTS_DIR = os.path.join(BASE_DIR, "media/events")

# AI Settings
COOLDOWN_SECONDS = 15
FACE_MATCH_THRESHOLD = 0.68 # VGG-Face typical threshold
PRE_ROLL_SECONDS = 5
POST_ROLL_SECONDS = 5

# Ensure media directories exist
os.makedirs(EVENTS_DIR, exist_ok=True)
os.makedirs(DB_PATH, exist_ok=True)