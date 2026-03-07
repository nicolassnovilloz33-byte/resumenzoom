"""
Cliente Recall.ai: crear bots que graban la sala principal y cada breakout room,
y obtener la transcripción de cada uno cuando terminan.
Soporta transcripción en tiempo real si BASE_PUBLIC_URL está configurada.
"""
import httpx
from config import RECALL_API_KEY, RECALL_REGION, BASE_PUBLIC_URL

RECALL_BASE = f"https://{RECALL_REGION}.recall.ai/api/v1"


def _headers():
    if not RECALL_API_KEY:
        raise ValueError("Falta RECALL_API_KEY en z.env")
    return {"Authorization": f"Token {RECALL_API_KEY}", "Content-Type": "application/json"}


def _recording_config() -> dict:
    """Config de grabación: con tiempo real si BASE_PUBLIC_URL está definida."""
    base = (BASE_PUBLIC_URL or "").strip().rstrip("/")
    if base:
        return {
            "transcript": {"provider": {"recallai_streaming": {}}},
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": f"{base}/webhooks/recall/realtime",
                    "events": ["transcript.data", "transcript.partial_data"],
                }
            ],
        }
    return {"transcript": {"provider": {"meeting_captions": {}}}}


def create_bot_main_room(meeting_url: str, metadata: dict | None = None) -> dict:
    """
    Crea un bot que se queda en la sala principal y rechaza invitaciones a breakouts.
    Recibe webhooks bot.breakout_room_opened cuando se abren salas.
    """
    body = {
        "meeting_url": meeting_url,
        "bot_name": "ResumenZoom-SalaPrincipal",
        "breakout_room": {"mode": "join_main_room"},
        "recording_config": _recording_config(),
    }
    if metadata:
        body["metadata"] = metadata
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{RECALL_BASE}/bot", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


def create_bot_breakout_room(
    meeting_url: str, room_id: str, room_name: str = "", metadata: dict | None = None
) -> dict:
    """
    Crea un bot que entra en una sala de trabajo específica (por ID).
    Llamar cuando recibís el webhook bot.breakout_room_opened.
    """
    body = {
        "meeting_url": meeting_url,
        "bot_name": f"ResumenZoom-{room_name or room_id[:8]}",
        "breakout_room": {"mode": "join_specific_room", "room_id": room_id},
        "recording_config": _recording_config(),
    }
    if metadata:
        body["metadata"] = metadata
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{RECALL_BASE}/bot", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


def create_bot_auto_accept(
    meeting_url: str, bot_name: str, metadata: dict | None = None
) -> dict:
    """
    Crea un bot que acepta cuando el host lo asigna a una sala.
    Para uso con "asignación manual": creás N bots, el host los asigna a cada sala.
    Así ningún participante elige sala (ideal para confidencialidad entre ISPs).
    """
    body = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "breakout_room": {"mode": "auto_accept_all_invites"},
        "recording_config": _recording_config(),
    }
    if metadata:
        body["metadata"] = metadata
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{RECALL_BASE}/bot", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


def get_bot(bot_id: str) -> dict:
    """Obtiene el estado y grabaciones de un bot."""
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{RECALL_BASE}/bot/{bot_id}", headers=_headers())
        r.raise_for_status()
        return r.json()


def leave_bot(bot_id: str) -> bool:
    """Saca al bot de la reunión (leave call). Irreversible."""
    with httpx.Client(timeout=15) as client:
        r = client.post(f"{RECALL_BASE}/bot/{bot_id}/leave", headers=_headers())
        if r.status_code in (200, 204):
            return True
        try:
            r.raise_for_status()
        except Exception:
            pass
        return False


def get_transcript_text(bot_id: str) -> str | None:
    """
    Descarga la transcripción del bot (cuando status es 'done') y la devuelve como texto.
    Recall devuelve JSON con participantes y words[].text.
    """
    bot = get_bot(bot_id)
    recordings = bot.get("recordings") or []
    for rec in recordings:
        shortcuts = rec.get("media_shortcuts") or {}
        transcript = shortcuts.get("transcript") or {}
        data = transcript.get("data") or {}
        url = data.get("download_url")
        if not url:
            continue
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                continue
            raw = resp.json()
        # Formato: lista de { participant, words: [ { text } ] }
        if isinstance(raw, list):
            parts = []
            for block in raw:
                for w in (block.get("words") or []):
                    t = w.get("text") or ""
                    if t:
                        parts.append(t)
            return " ".join(parts).strip() or None
        return None
    return None
