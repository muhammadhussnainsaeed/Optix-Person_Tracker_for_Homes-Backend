#
# from fastapi import FastAPI
# import uvicorn
# from api import auth,cameras,dashboard,floor,family,unwanted_person,logs,settings
# from fastapi.staticfiles import StaticFiles
#
# app = FastAPI()
# app.include_router(auth.router)
# app.include_router(dashboard.router)
# app.include_router(cameras.router)
# app.include_router(floor.router)
# app.include_router(family.router)
# app.include_router(unwanted_person.router)
# app.include_router(logs.router)
# app.include_router(settings.router)
# app.mount("/media", StaticFiles(directory="media"), name="media")
#
# @app.get("/")
# def read_root():
#     return {"status": "Surveillance System Online", "version": "1.0"}
#
#
#
# # try:
# #     conn = psycopg2.connect("dbname=home_surveillance_db user=postgres password=12345 host=127.0.0.1 port=5432")
# #     print("✅ SUCCESS: psycopg2-binary is working perfectly!")
# #     conn.close()
# # except Exception as e:
# #     print(f"❌ ERROR: {e}")
#
#
# if __name__ == '__main__':
#     uvicorn.run (app, host='0.0.0.0' , port=8888)
#
# @app.get("/endpoint")
# def function12():
#     return {"status": "Surveillance System Online", "version": "1.0"}


import os
import warnings

# ==========================================
# 1. SUPPRESS TENSORFLOW & DEPRECATION NOISE
# (Must be at the absolute top of the file)
# ==========================================
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import tensorflow as tf

try:
    tf.config.set_visible_devices([], 'GPU')
except Exception:
    pass

# ==========================================
# 2. STANDARD IMPORTS
# ==========================================
import asyncio
import multiprocessing
import queue
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

# Your App Routers
from api import auth, cameras, dashboard, floor, family, unwanted_person, logs, settings

# The new AI Engine modules (from the updated architecture)
from ai_engine.face_recognition import FaceCache
from ai_engine.vision_worker import camera_worker_process

# ==========================================
# 3. GLOBAL STATE & WEBSOCKET BRIDGE
# ==========================================
alert_queue = multiprocessing.Queue()
active_ai_processes = []  # Tracks all running camera processes


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)


manager = ConnectionManager()


async def watch_queue():
    """Background task to constantly check if the AI found an intruder."""
    print("🌐 [WebSocket] Listening for AI alerts...")
    while True:
        try:
            alert = alert_queue.get_nowait()
            print(f"🚨 [FastAPI] Broadcasting Alert: {alert}")
            await manager.broadcast(alert)
        except queue.Empty:
            await asyncio.sleep(0.1)


# ==========================================
# 4. APP LIFESPAN (Startup & Shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting FastAPI Server...")

    # 1. Start the Background Queue Watcher for WebSockets
    asyncio.create_task(watch_queue())

    # 2. Sync database faces into memory
    FaceCache.sync_from_db()

    # 3. Spawn a dedicated GPU process for each camera
    cameras = FaceCache.get_all_cameras()
    print(f"🤖 Booting up AI Engine for {len(cameras)} cameras...")

    for cam_id, cam_data in cameras.items():
        user_id = cam_data["user_id"]
        user_cache = FaceCache.get_user_cache(user_id)

        # Pass the alert_queue to the worker so it can trigger iOS notifications
        p = multiprocessing.Process(
            target=camera_worker_process,
            args=(cam_id, cam_data["video_url"], user_id, user_cache, alert_queue),
            name=f"CamWorker-{cam_id[-4:]}"
        )
        p.start()
        active_ai_processes.append(p)

    yield  # The server is now running!

    print("🛑 Shutting down server and releasing GPU memory...")
    # 4. Clean up AI Processes on shutdown to prevent VRAM leaks
    for p in active_ai_processes:
        p.terminate()
        p.join()
    print("✅ All AI workers terminated cleanly.")


# ==========================================
# 5. FASTAPI INITIALIZATION & ROUTERS
# ==========================================
app = FastAPI(lifespan=lifespan)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(cameras.router)
app.include_router(floor.router)
app.include_router(family.router)
app.include_router(unwanted_person.router)
app.include_router(logs.router)
app.include_router(settings.router)

app.mount("/media", StaticFiles(directory="media"), name="media")


@app.get("/")
def read_root():
    return {"status": "Surveillance System Online", "version": "1.0"}


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("App disconnected from WebSockets.")


if __name__ == '__main__':
    # NOTE: On Windows, using multiprocessing with reload=True can sometimes cause duplicate workers.
    # If your GPU memory suddenly spikes to 100%, change reload=False.
    uvicorn.run("main:app", host='0.0.0.0', port=8888, reload=True)