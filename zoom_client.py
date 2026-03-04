"""
Cliente Zoom: token Server-to-Server y obtención de grabaciones/transcripciones.
Requisito: reuniones grabadas en la nube (cloud recording).
"""
import httpx
from config import (
    ZOOM_ACCOUNT_ID,
    ZOOM_CLIENT_ID,
    ZOOM_CLIENT_SECRET,
    ZOOM_USER_ID,
)

ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE = "https://api.zoom.us/v2"


def get_zoom_access_token() -> str:
    """Obtiene access token con Server-to-Server OAuth (JWT ya no se usa en cuentas nuevas)."""
    if not all([ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET]):
        raise ValueError(
            "Faltan ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID o ZOOM_CLIENT_SECRET en .env"
        )
    with httpx.Client() as client:
        resp = client.post(
            ZOOM_TOKEN_URL,
            params={"grant_type": "account_credentials", "account_id": ZOOM_ACCOUNT_ID},
            auth=(ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET),
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def list_recordings(user_id: str = ZOOM_USER_ID, page_size: int = 30):
    """Lista grabaciones en la nube del usuario. Requiere scope recording:read (o read:admin)."""
    token = get_zoom_access_token()
    with httpx.Client() as client:
        r = client.get(
            f"{ZOOM_API_BASE}/users/{user_id}/recordings",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": page_size},
        )
        r.raise_for_status()
        return r.json()


def get_meeting_recordings(meeting_id: str):
    """Obtiene los archivos de grabación de una reunión (incluye transcripción si existe)."""
    token = get_zoom_access_token()
    with httpx.Client() as client:
        r = client.get(
            f"{ZOOM_API_BASE}/meetings/{meeting_id}/recordings",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        return r.json()


def get_transcript_from_recordings(recordings_data: dict) -> str | None:
    """
    Extrae el contenido de transcripción de la respuesta de recordings.
    Zoom puede devolver archivos de tipo 'transcript' o 'vtt' con download_url.
    """
    recording_files = recordings_data.get("recording_files") or []
    for f in recording_files:
        if f.get("file_type") == "TRANSCRIPT" or (
            f.get("file_extension") and "transcript" in f.get("file_extension", "").lower()
        ):
            download_url = f.get("download_url")
            if download_url and f.get("status") == "completed":
                # La URL suele requerir token; si tu app tiene download_url con token, la usamos
                with httpx.Client(follow_redirects=True) as client:
                    try:
                        # Zoom a veces exige token en la URL
                        token = get_zoom_access_token()
                        resp = client.get(
                            download_url,
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if resp.status_code == 200:
                            return resp.text
                    except Exception:
                        pass
    return None
