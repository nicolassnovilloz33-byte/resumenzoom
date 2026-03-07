"""
Estado de sesiones de reunión: un bot en sala principal + N bots en breakout rooms.
Cuando todos terminan, se genera el resumen automáticamente.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# En memoria (para producción usar Redis/DB)
_sessions: dict[str, "Session"] = {}
_bot_to_session: dict[str, str] = {}  # bot_id -> session_id


def _extract_meeting_id(meeting_url: str | dict | None) -> str | None:
    """Extrae el ID numérico de la reunión de una URL de Zoom."""
    if not meeting_url:
        return None
    if isinstance(meeting_url, dict):
        meeting_url = meeting_url.get("url") or meeting_url.get("meeting_url") or ""
    if not isinstance(meeting_url, str):
        return None
    m = re.search(r"zoom\.us/j/(\d+)", meeting_url)
    return m.group(1) if m else None


@dataclass
class RoomBot:
    bot_id: str
    room_id: str
    room_name: str
    transcript: str | None = None  # None = aún no procesado, "" = error o vacío
    realtime_transcript: str = ""  # Acumulado en tiempo real (transcript.data)


@dataclass
class Session:
    session_id: str
    meeting_url: str
    meeting_id: str | None  # ID numérico de Zoom para buscar por reunión
    main_bot_id: str
    main_transcript: str | None = None
    main_realtime_transcript: str = ""  # Acumulado en tiempo real
    room_bots: list[RoomBot] = field(default_factory=list)
    status: str = "recording"  # recording | processing | done
    summary: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def all_bots_done(self) -> bool:
        if self.main_transcript is None:
            return False
        return all(r.transcript is not None for r in self.room_bots)


def create_session(meeting_url: str | dict, main_bot_id: str) -> Session:
    sid = str(uuid.uuid4())
    if isinstance(meeting_url, str):
        url_str = meeting_url
    else:
        url_str = (meeting_url.get("url") or meeting_url.get("meeting_url")) if isinstance(meeting_url, dict) else ""
        url_str = url_str if isinstance(url_str, str) else ""
    meeting_id = _extract_meeting_id(url_str)
    s = Session(
        session_id=sid,
        meeting_url=url_str,
        meeting_id=meeting_id,
        main_bot_id=main_bot_id,
    )
    _sessions[sid] = s
    _bot_to_session[main_bot_id] = sid
    return s


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def get_latest_session_by_meeting_id(meeting_id: str) -> Session | None:
    """Devuelve la sesión más reciente para este ID de reunión Zoom (la última vez que iniciaron bots)."""
    if not meeting_id:
        return None
    # normalizar: solo dígitos
    mid = re.sub(r"\D", "", str(meeting_id))
    if not mid:
        return None
    candidates = [s for s in _sessions.values() if s.meeting_id == mid]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.created_at)


def get_session_by_bot_id(bot_id: str) -> Session | None:
    sid = _bot_to_session.get(bot_id)
    return _sessions.get(sid) if sid else None


def register_room_bot(session_id: str, bot_id: str, room_id: str, room_name: str) -> None:
    s = _sessions.get(session_id)
    if not s:
        return
    s.room_bots.append(RoomBot(bot_id=bot_id, room_id=room_id, room_name=room_name))
    _bot_to_session[bot_id] = session_id


def set_main_transcript(session_id: str, text: str | None) -> None:
    s = _sessions.get(session_id)
    if s:
        s.main_transcript = text or ""


def set_room_transcript(session_id: str, bot_id: str, text: str | None) -> None:
    s = _sessions.get(session_id)
    if not s:
        return
    for r in s.room_bots:
        if r.bot_id == bot_id:
            r.transcript = text if text else ""
            break


def append_realtime_transcript(bot_id: str, text: str) -> None:
    """Acumula texto de transcripción en tiempo real (evento transcript.data)."""
    if not text or not text.strip():
        return
    s = get_session_by_bot_id(bot_id)
    if not s:
        return
    segment = text.strip()
    if s.main_bot_id == bot_id:
        s.main_realtime_transcript = (s.main_realtime_transcript + " " + segment).strip()
    else:
        for r in s.room_bots:
            if r.bot_id == bot_id:
                r.realtime_transcript = (r.realtime_transcript + " " + segment).strip()
                break


def mark_processing(session_id: str) -> None:
    s = _sessions.get(session_id)
    if s:
        s.status = "processing"


def mark_done(session_id: str, summary: str | None = None, error: str | None = None) -> None:
    s = _sessions.get(session_id)
    if s:
        s.status = "done"
        if summary is not None:
            s.summary = summary
        if error:
            s.error = error
