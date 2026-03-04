"""
Estado de sesiones de reunión: un bot en sala principal + N bots en breakout rooms.
Cuando todos terminan, se genera el resumen automáticamente.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# En memoria (para producción usar Redis/DB)
_sessions: dict[str, "Session"] = {}
_bot_to_session: dict[str, str] = {}  # bot_id -> session_id


@dataclass
class RoomBot:
    bot_id: str
    room_id: str
    room_name: str
    transcript: str | None = None  # None = aún no procesado, "" = error o vacío


@dataclass
class Session:
    session_id: str
    meeting_url: str
    main_bot_id: str
    main_transcript: str | None = None
    room_bots: list[RoomBot] = field(default_factory=list)
    status: str = "recording"  # recording | processing | done
    summary: str | None = None
    error: str | None = None

    def all_bots_done(self) -> bool:
        if self.main_transcript is None:
            return False
        return all(r.transcript is not None for r in self.room_bots)


def create_session(meeting_url: str, main_bot_id: str) -> Session:
    sid = str(uuid.uuid4())
    s = Session(session_id=sid, meeting_url=meeting_url, main_bot_id=main_bot_id)
    _sessions[sid] = s
    _bot_to_session[main_bot_id] = sid
    return s


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


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
