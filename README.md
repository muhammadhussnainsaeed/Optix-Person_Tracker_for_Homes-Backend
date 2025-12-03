#  Optix(Person Tracker for Homes) - Backend API

> **FastAPI backend for a cross-platform Home Surveillance System. Integrates YOLOv8 & DeepFace for real-time family vs. intruder detection, 2D floor plan syncing, and intelligent event logging.**

## About The Project

This repository hosts the backend API and database management for a Final Year Project (FYP) focused on intelligent home security. The system allows users to map their home layouts, place CCTV cameras digitally, and receive real-time AI alerts.

Going beyond passive video recording, this system employs real-time identity recognition to distinguish between family members and potential threats, logging their specific journey through the home in a centralized database.

## Tech Stack

* **Framework:** Python (FastAPI)
* **Database:** PostgreSQL (using `JSONB` for floor plans & `UUID` for IDs)
* **AI/ML:** YOLOv8 (Person Detection), DeepFace (Face Recognition), OpenCV
* **Authentication:** JWT (JSON Web Tokens)
* **Deployment:** Uvicorn / Gunicorn

## Features & Functionality

### Expected Features
* **Secure Authentication:** User Sign Up, Sign In, and Password Recovery using secure hashing.
* **Camera Management:** CRUD operations for RTSP/Video streams with "Privacy" tagging.
* **Digital Floor Plan:** Storage for vector-based floor maps (Rooms, Walls, Doors) allowing cross-platform syncing between iOS, Android, and Web.
* **Family Management:** specific profiles for family members with photo uploads for AI training.
* **AI Surveillance Engine:** Real-time processing of RTSP feeds to detect humans.
* **Intelligent Alerting:** Differentiates between:
    * **Family(Allowed):** Logs presence (e.g., "Ali spotted in Kitchen").
    * **Threat Recognition(Reappearing):** Identifies returning intruders from the unwantedlist and sends critical alerts.
    * **Auto-Indexing(First-Time):** Automatically detects first-time visitors, registers them as new "Unwanted" profiles with unique codenames, and notifies the user instantly.
* **"Codenames" for Intruders:** automatically assigns distinct, user-friendly names (e.g., *"Teal Falcon 882"*) to unknown subjects for easier tracking across multiple logs.
* **Journey Tracking:** Grouping unwanted individual logs into a timeline to show a person's path through the house (Main Gate → Room 1 → Kitchen).
