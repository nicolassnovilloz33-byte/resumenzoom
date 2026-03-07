"""
API para obtener transcripciones de Zoom y generar resumen unificado
de la sala principal + todas las salas (breakout rooms).
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Cargar variables desde z.env (misma carpeta que este archivo)
_env_path = Path(__file__).resolve().parent / "z.env"
load_dotenv(_env_path)

# Zoom
ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "")
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
ZOOM_USER_ID = os.getenv("ZOOM_USER_ID", "me")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Recall.ai (bots que graban sala principal + cada breakout room)
RECALL_API_KEY = (os.getenv("RECALL_API_KEY") or "").strip()
RECALL_REGION = (os.getenv("RECALL_REGION") or "us-west-2").strip()
RECALL_WEBHOOK_SECRET = (os.getenv("RECALL_WEBHOOK_SECRET") or "").strip()
