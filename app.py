"""
API FastAPI: reuniones Zoom + transcripciones de salas → resumen unificado.
Modo manual (Zoom + texto por sala) o automático (Recall.ai: bots por sala → resumen al terminar).
"""
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY
from resumen import generar_resumen
from recall_client import (
    create_bot_main_room,
    create_bot_breakout_room,
    get_bot,
    get_transcript_text,
)
from sessions import (
    create_session,
    get_session,
    get_session_by_bot_id,
    register_room_bot,
    set_main_transcript,
    set_room_transcript,
    mark_processing,
    mark_done,
)
from zoom_client import (
    get_meeting_recordings,
    get_transcript_from_recordings,
    list_recordings,
)


# --- Modelos ---
class SalaBreakout(BaseModel):
    nombre: str = Field(..., description="Nombre de la sala (ej: Sala 1, Equipo Comercial)")
    transcripcion: str = Field("", description="Texto o transcripción de lo dicho en esa sala")


class PedidoResumen(BaseModel):
    sala_principal: str | None = Field(
        None,
        description="Transcripción de la sala principal (opcional si se obtiene por Zoom)",
    )
    salas_breakout: list[SalaBreakout] = Field(
        default_factory=list,
        description="Lista de transcripciones por sala",
    )
    openai_api_key: str | None = Field(None, description="Override de API key (opcional)")


class IniciarReunionBody(BaseModel):
    meeting_url: str = Field(..., description="URL de la reunión Zoom (ej. https://zoom.us/j/123...)")


# --- App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # cleanup si hiciera falta


app = FastAPI(
    title="Resumen Zoom - Todas las salas",
    description="Obtiene transcripción de la reunión y genera un resumen unificado de sala principal + breakout rooms.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_BASE = Path(__file__).resolve().parent
_static_dir = _BASE / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
def root():
    index = _BASE / "static" / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {
        "app": "Resumen Zoom - Todas las salas",
        "endpoints": {
            "zoom_grabaciones": "GET /zoom/grabaciones",
            "zoom_transcript": "GET /zoom/reuniones/{meeting_id}/transcript",
            "resumen": "POST /resumen",
            "reunion_iniciar": "POST /reuniones/iniciar (automático con Recall.ai)",
            "reunion_estado": "GET /reuniones/{session_id}",
            "webhooks_recall": "POST /webhooks/recall",
        },
    }


@app.post("/reuniones/iniciar")
def reuniones_iniciar(body: IniciarReunionBody):
    """
    Inicia una reunión automática: envía un bot a la sala principal.
    Cuando en Zoom abras las salas de trabajo con "Dejar que los participantes elijan sala",
    este servidor recibirá webhooks y creará un bot por cada sala. Al terminar todos,
    se generará el resumen sin intervención manual.
    """
    try:
        bot = create_bot_main_room(body.meeting_url)
        bot_id = bot.get("id")
        meeting_url = bot.get("meeting_url") or body.meeting_url
        if not bot_id:
            raise HTTPException(status_code=502, detail="Recall no devolvió ID del bot")
        session = create_session(meeting_url, bot_id)
        return {
            "session_id": session.session_id,
            "main_bot_id": bot_id,
            "message": "Bot en sala principal. Al abrir breakout rooms (con 'Dejar que participantes elijan sala'), se crearán bots por sala. Configurá la URL de webhook en Recall.ai: POST a tu servidor /webhooks/recall",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/reuniones/{session_id}")
def reuniones_estado(session_id: str):
    """Devuelve el estado de la sesión y el resumen cuando esté listo."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {
        "session_id": session.session_id,
        "meeting_url": session.meeting_url,
        "status": session.status,
        "main_bot_id": session.main_bot_id,
        "main_transcript_ready": session.main_transcript is not None,
        "room_bots": [
            {"bot_id": r.bot_id, "room_name": r.room_name, "transcript_ready": r.transcript is not None}
            for r in session.room_bots
        ],
        "summary": session.summary,
        "error": session.error,
    }


def _on_all_bots_done(session_id: str):
    """Genera el resumen cuando todos los bots terminaron."""
    session = get_session(session_id)
    if not session or not session.all_bots_done():
        return
    mark_processing(session_id)
    sala_principal = session.main_transcript or ""
    salas = [
        {"nombre": r.room_name or f"Sala {r.room_id[:8]}", "transcripcion": r.transcript or ""}
        for r in session.room_bots
    ]
    try:
        resumen = generar_resumen(sala_principal=sala_principal, salas_breakout=salas)
        mark_done(session_id, summary=resumen)
    except Exception as e:
        mark_done(session_id, error=str(e))


@app.post("/webhooks/recall")
async def webhook_recall(request: Request):
    """
    Webhooks de Recall.ai: bot.breakout_room_opened (crear bot por sala),
    bot.status_change (done → descargar transcripción; cuando todos listos → resumen).
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}
    event = body.get("event") or ""
    data = body.get("data") or {}

    if event == "bot.breakout_room_opened":
        # Solo lo recibe el bot con mode join_main_room
        bot_id = (data.get("bot") or {}).get("id") or data.get("bot_id")
        inner = data.get("data") or data
        br = inner.get("breakout_room") or {}
        room_id = br.get("id")
        room_name = (br.get("name") or "")[:80]
        if not bot_id or not room_id:
            return {"ok": True}
        session = get_session_by_bot_id(bot_id)
        if not session:
            return {"ok": True}
        try:
            new_bot = create_bot_breakout_room(session.meeting_url, room_id, room_name)
            new_id = new_bot.get("id")
            if new_id:
                register_room_bot(session.session_id, new_id, room_id, room_name)
        except Exception:
            pass
        return {"ok": True}

    if event == "bot.status_change":
        status = data.get("status") or {}
        if status.get("code") != "done":
            return {"ok": True}
        bot_id = data.get("bot_id") or (data.get("bot") or {}).get("id")
        if not bot_id:
            return {"ok": True}
        session = get_session_by_bot_id(bot_id)
        if not session:
            return {"ok": True}
        try:
            text = get_transcript_text(bot_id)
        except Exception:
            text = ""
        if bot_id == session.main_bot_id:
            set_main_transcript(session.session_id, text)
        else:
            set_room_transcript(session.session_id, bot_id, text)
        session = get_session(session.session_id)
        if session and session.all_bots_done():
            _on_all_bots_done(session.session_id)
        return {"ok": True}

    return {"ok": True}


@app.get("/zoom/grabaciones")
def zoom_grabaciones(user_id: str | None = None):
    """Lista las grabaciones recientes en la nube (para elegir meeting_id)."""
    try:
        data = list_recordings(user_id=user_id or "me")
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zoom: {str(e)}")


@app.get("/zoom/reuniones/{meeting_id}/transcript")
def zoom_transcript(meeting_id: str):
    """
    Obtiene la transcripción de la reunión desde la grabación en la nube.
    Solo incluye lo grabado en la sala principal (Zoom no graba cada breakout por separado en la nube).
    """
    try:
        data = get_meeting_recordings(meeting_id)
        transcript = get_transcript_from_recordings(data)
        if transcript is None:
            return {
                "meeting_id": meeting_id,
                "transcript": None,
                "message": "No hay archivo de transcripción en esta grabación. Activa 'Guardar transcripción' en la grabación en la nube.",
                "recording_files": [
                    {
                        "type": f.get("file_type"),
                        "extension": f.get("file_extension"),
                        "status": f.get("status"),
                    }
                    for f in data.get("recording_files") or []
                ],
            }
        return {"meeting_id": meeting_id, "transcript": transcript}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zoom: {str(e)}")


@app.post("/resumen")
def post_resumen(pedido: PedidoResumen):
    """
    Genera un resumen unificado a partir de:
    - Transcripción de la sala principal (opcional)
    - Transcripciones de cada sala de trabajo (breakout rooms).
    """
    try:
        sala_principal = pedido.sala_principal
        salas = [
            {"nombre": s.nombre, "transcripcion": s.transcripcion}
            for s in pedido.salas_breakout
        ]
        texto = generar_resumen(
            sala_principal=sala_principal,
            salas_breakout=salas,
            openai_api_key=pedido.openai_api_key or os.getenv("OPENAI_API_KEY"),
        )
        return {"resumen": texto}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
