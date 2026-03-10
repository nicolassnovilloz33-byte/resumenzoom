"""
Persistencia de sesiones en PostgreSQL.
Si DATABASE_URL está definida, sessions.py usa estas funciones en lugar de memoria.
"""
from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


def _extract_meeting_id(meeting_url: str | None) -> str | None:
    if not meeting_url or not isinstance(meeting_url, str):
        return None
    m = re.search(r"zoom\.us/j/(\d+)", meeting_url)
    return m.group(1) if m else None


def _get_conn():
    from config import DATABASE_URL
    if not DATABASE_URL or not psycopg2:
        raise RuntimeError("DATABASE_URL no configurada o psycopg2 no instalado")
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def _cursor():
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """Crea tablas si no existen. Llamar al arrancar la app."""
    with _cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                meeting_url TEXT NOT NULL,
                meeting_id TEXT,
                main_bot_id TEXT NOT NULL,
                main_transcript TEXT,
                main_realtime_transcript TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'recording',
                summary TEXT,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS room_bots (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                bot_id TEXT NOT NULL,
                room_id TEXT NOT NULL,
                room_name TEXT NOT NULL,
                transcript TEXT,
                realtime_transcript TEXT NOT NULL DEFAULT ''
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_meeting_id ON sessions(meeting_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_room_bots_session_id ON room_bots(session_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_room_bots_bot_id ON room_bots(bot_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_main_bot_id ON sessions(main_bot_id);")


def _row_to_session(row: dict, room_rows: list[dict]) -> dict[str, Any]:
    """Convierte filas de DB a dict para que sessions.py construya Session/RoomBot."""
    room_bots_data = [
        {
            "bot_id": r["bot_id"],
            "room_id": r["room_id"],
            "room_name": r["room_name"],
            "transcript": r.get("transcript"),
            "realtime_transcript": r.get("realtime_transcript") or "",
        }
        for r in room_rows
    ]
    return {
        "session_id": row["session_id"],
        "meeting_url": row["meeting_url"],
        "meeting_id": row["meeting_id"],
        "main_bot_id": row["main_bot_id"],
        "main_transcript": row.get("main_transcript"),
        "main_realtime_transcript": row.get("main_realtime_transcript") or "",
        "room_bots": room_bots_data,
        "status": row.get("status") or "recording",
        "summary": row.get("summary"),
        "error": row.get("error"),
        "created_at": row["created_at"],
    }


def create_session(meeting_url: str, main_bot_id: str) -> dict[str, Any]:
    if isinstance(meeting_url, dict):
        meeting_url = (meeting_url.get("url") or meeting_url.get("meeting_url")) or ""
    meeting_url = meeting_url if isinstance(meeting_url, str) else ""
    meeting_id = _extract_meeting_id(meeting_url)
    session_id = str(uuid.uuid4())
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (session_id, meeting_url, meeting_id, main_bot_id)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, meeting_url, meeting_id, main_bot_id),
        )
    return {
        "session_id": session_id,
        "meeting_url": meeting_url,
        "meeting_id": meeting_id,
        "main_bot_id": main_bot_id,
        "main_transcript": None,
        "main_realtime_transcript": "",
        "room_bots": [],
        "status": "recording",
        "summary": None,
        "error": None,
        "created_at": datetime.utcnow(),
    }


def get_session(session_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM sessions WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("SELECT bot_id, room_id, room_name, transcript, realtime_transcript FROM room_bots WHERE session_id = %s ORDER BY id", (session_id,))
        room_rows = cur.fetchall()
    return _row_to_session(dict(row), [dict(r) for r in room_rows])


def get_latest_session_by_meeting_id(meeting_id: str) -> dict[str, Any] | None:
    mid = re.sub(r"\D", "", str(meeting_id)) if meeting_id else ""
    if not mid:
        return None
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM sessions WHERE meeting_id = %s ORDER BY created_at DESC LIMIT 1",
            (mid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        sid = row["session_id"]
        cur.execute("SELECT bot_id, room_id, room_name, transcript, realtime_transcript FROM room_bots WHERE session_id = %s ORDER BY id", (sid,))
        room_rows = cur.fetchall()
    return _row_to_session(dict(row), [dict(r) for r in room_rows])


def get_session_by_bot_id(bot_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT session_id FROM sessions WHERE main_bot_id = %s", (bot_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT session_id FROM room_bots WHERE bot_id = %s", (bot_id,))
            row = cur.fetchone()
        if not row:
            return None
        return get_session(row["session_id"])


def register_room_bot(session_id: str, bot_id: str, room_id: str, room_name: str) -> None:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO room_bots (session_id, bot_id, room_id, room_name)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, bot_id, room_id, room_name),
        )


def set_main_transcript(session_id: str, text: str | None) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE sessions SET main_transcript = %s WHERE session_id = %s",
            (text or "", session_id),
        )


def set_room_transcript(session_id: str, bot_id: str, text: str | None) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE room_bots SET transcript = %s WHERE session_id = %s AND bot_id = %s",
            (text or "", session_id, bot_id),
        )


def append_realtime_transcript(bot_id: str, text: str) -> None:
    if not text or not text.strip():
        return
    segment = text.strip()
    with _cursor() as cur:
        cur.execute("SELECT session_id, main_bot_id FROM sessions WHERE main_bot_id = %s", (bot_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE sessions SET main_realtime_transcript = COALESCE(main_realtime_transcript, '') || ' ' || %s WHERE session_id = %s",
                (segment, row["session_id"]),
            )
            return
        cur.execute("SELECT session_id FROM room_bots WHERE bot_id = %s", (bot_id,))
        row = cur.fetchone()
        if not row:
            return
        cur.execute(
            "UPDATE room_bots SET realtime_transcript = COALESCE(realtime_transcript, '') || ' ' || %s WHERE bot_id = %s",
            (segment, bot_id),
        )


def mark_processing(session_id: str) -> None:
    with _cursor() as cur:
        cur.execute("UPDATE sessions SET status = 'processing' WHERE session_id = %s", (session_id,))


def mark_done(session_id: str, summary: str | None = None, error: str | None = None) -> None:
    with _cursor() as cur:
        if summary is not None or error is not None:
            cur.execute(
                "UPDATE sessions SET status = 'done', summary = COALESCE(%s, summary), error = %s WHERE session_id = %s",
                (summary, error, session_id),
            )
        else:
            cur.execute("UPDATE sessions SET status = 'done' WHERE session_id = %s", (session_id,))
