import os

# --- BASE PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "ai_engine", "weights", "best.pt")
DB_PATH = os.path.join(BASE_DIR, "media", "persons")
EVENTS_DIR = os.path.join(BASE_DIR, "media", "events")

# --- CENTRALIZED SUBDIRECTORIES ---
TEMP_DIR = os.path.join(BASE_DIR, "media", "temp")
FAMILY_DIR = os.path.join(EVENTS_DIR, "family")
UNWANTED_DIR = os.path.join(EVENTS_DIR, "unwanted")

# --- AI SETTINGS ---
COOLDOWN_SECONDS = 15
FACE_MATCH_THRESHOLD = 0.68 # 0.68 is the optimal cosine distance for ArcFace
PRE_ROLL_SECONDS = 3
POST_ROLL_SECONDS = 3

# --- INITIALIZATION ---
# Ensure all media directories exist on startup
for directory in [DB_PATH, TEMP_DIR, FAMILY_DIR, UNWANTED_DIR]:
    os.makedirs(directory, exist_ok=True)