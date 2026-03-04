"""
API para obtener transcripciones de Zoom y generar resumen unificado
de la sala principal + todas las salas (breakout rooms).
"""
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Zoom
ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "")
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
ZOOM_USER_ID = os.getenv("ZOOM_USER_ID", "me")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Recall.ai (bots que graban sala principal + cada breakout room)
RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_REGION = os.getenv("RECALL_REGION", "us-east-1")  # us-east-1, eu-central-1, etc.
RECALL_WEBHOOK_SECRET = os.getenv("RECALL_WEBHOOK_SECRET", "")  # opcional: verificar firma
