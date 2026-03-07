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
    create_bot_auto_accept,
    get_bot,
    get_transcript_text,
)
from sessions import (
    create_session,
    get_session,
    get_latest_session_by_meeting_id,
    get_session_by_bot_id,
    register_room_bot,
    set_main_transcript,
    set_room_transcript,
    mark_processing,
    mark_done,
    append_realtime_transcript,
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
    num_breakout_rooms: int | None = Field(
        None,
        description="Cantidad de salas de trabajo. Si lo indicás, se crean N bots que VOS asignás a cada sala en Zoom (asignación manual). Así nadie elige sala y no hay riesgo de que un ISP entre a la sala de otro.",
    )


class ResumenParcialBody(BaseModel):
    meeting_id: str = Field(..., description="ID de la reunión Zoom (solo números)")


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
    Inicia una reunión automática.
    - Sin num_breakout_rooms: envía un bot a la sala principal; si en Zoom usás
      "Dejar que los participantes elijan sala", se crean bots por sala vía webhook.
    - Con num_breakout_rooms (ej. 4): envía 1 bot a la sala principal + 4 bots que
      aceptan asignación. Vos, como host, asignás cada bot a una sala al abrir los
      breakouts. Así nadie elige sala (ideal para confidencialidad entre ISPs).
    """
    try:
        meeting_url = (body.meeting_url or "").strip()
        if not meeting_url:
            raise HTTPException(status_code=400, detail="La URL de la reunión no puede estar vacía.")
        bot = create_bot_main_room(meeting_url)
        bot_id = bot.get("id")
        meeting_url_from_bot = bot.get("meeting_url") or meeting_url
        if isinstance(meeting_url_from_bot, dict):
            meeting_url_from_bot = meeting_url_from_bot.get("url") or meeting_url_from_bot.get("meeting_url") or meeting_url
        if not isinstance(meeting_url_from_bot, str):
            meeting_url_from_bot = meeting_url
        if not bot_id:
            raise HTTPException(status_code=502, detail="Recall no devolvió ID del bot")
        session = create_session(meeting_url_from_bot, bot_id)

        room_bot_ids = []
        if body.num_breakout_rooms and body.num_breakout_rooms > 0:
            n = min(body.num_breakout_rooms, 20)  # límite razonable
            for i in range(1, n + 1):
                try:
                    rb = create_bot_auto_accept(
                        meeting_url_from_bot,
                        bot_name=f"ResumenZoom-Sala{i}",
                    )
                    rid = rb.get("id")
                    if rid:
                        register_room_bot(
                            session.session_id, rid, room_id="", room_name=f"Sala {i}"
                        )
                        room_bot_ids.append((i, rid))
                except Exception:
                    break

            return {
                "session_id": session.session_id,
                "main_bot_id": bot_id,
                "room_bots": [{"sala": f"Sala {i}", "bot_id": rid} for i, rid in room_bot_ids],
                "message": (
                    f"Listo: 1 bot en sala principal + {len(room_bot_ids)} bots para salas de trabajo. "
                    "Al abrir los breakouts en Zoom, ASIGNÁ cada participante 'ResumenZoom-Sala1', "
                    "'ResumenZoom-Sala2', etc. a la sala que corresponda. Nadie elige sala; solo vos asignás."
                ),
            }

        return {
            "session_id": session.session_id,
            "main_bot_id": bot_id,
            "message": "Bot en sala principal. Al abrir breakout rooms (con 'Dejar que participantes elijan sala'), se crearán bots por sala. Configurá la URL de webhook en Recall.ai: POST a tu servidor /webhooks/recall",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al enviar bot: {str(e)}")


@app.get("/reuniones/{session_id}")
def reuniones_estado(session_id: str):
    """Devuelve el estado de la sesión y el resumen cuando esté listo."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return _session_response(session)


@app.get("/reuniones")
def reuniones_por_meeting_id(meeting_id: str):
    """
    Devuelve la sesión más reciente para este ID de reunión Zoom.
    Así podés usar siempre tu mismo meeting ID y solo hacer clic en "Ver resumen".
    """
    session = get_latest_session_by_meeting_id(meeting_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna sesión para este ID de reunión. Iniciá una reunión con bots primero.",
        )
    return _session_response(session)


@app.post("/reuniones/resumen-parcial")
def resumen_parcial(body: ResumenParcialBody):
    """
    Genera un resumen con la transcripción en tiempo real acumulada hasta ahora
    (sin necesidad de que la reunión haya terminado). Requiere BASE_PUBLIC_URL configurada
    y que los bots estén creados con transcripción en vivo.
    """
    import re
    mid = re.sub(r"\D", "", str(body.meeting_id or ""))
    if not mid:
        raise HTTPException(status_code=400, detail="ID de reunión inválido.")
    session = get_latest_session_by_meeting_id(mid)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="No hay sesión para este ID. Iniciá una reunión con bots primero.",
        )
    sala_principal = session.main_realtime_transcript or session.main_transcript or ""
    salas = []
    for r in session.room_bots:
        trans = r.realtime_transcript or r.transcript or ""
        name = r.room_name or f"Sala {r.room_id[:8]}"
        if trans or name:
            salas.append({"nombre": name, "transcripcion": trans})
    if not sala_principal.strip() and not any((s.get("transcripcion") or "").strip() for s in salas):
        raise HTTPException(
            status_code=404,
            detail="Aún no hay transcripción en tiempo real. Esperá unos minutos mientras hablan en la reunión.",
        )
    try:
        resumen = generar_resumen(sala_principal=sala_principal or None, salas_breakout=salas)
        return {"summary": resumen}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al generar resumen: {str(e)}")


def _session_response(session):
    return {
        "session_id": session.session_id,
        "meeting_url": session.meeting_url,
        "meeting_id": session.meeting_id,
        "status": session.status,
        "main_bot_id": session.main_bot_id,
        "main_transcript_ready": session.main_transcript is not None,
        "realtime_available": bool(
            session.main_realtime_transcript
            or any(getattr(r, "realtime_transcript", "") for r in session.room_bots)
        ),
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
    # Algunos proveedores (Svix) pueden enviar el payload envuelto en "data"
    if isinstance(body, dict) and "data" in body and "event" not in body:
        body = body.get("data") or body
    if isinstance(body, dict) and isinstance(body.get("data"), dict) and "event" in body.get("data", {}):
        body = body["data"]
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
        meeting_url = (session.meeting_url or "").strip()
        if not meeting_url:
            return {"ok": True}
        try:
            new_bot = create_bot_breakout_room(meeting_url, room_id, room_name)
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


@app.post("/webhooks/recall/realtime")
async def webhook_recall_realtime(request: Request):
    """
    Webhook de Recall para transcripción en tiempo real (transcript.data / transcript.partial_data).
    Acumulamos solo transcript.data para el resumen parcial (evitar duplicados con partial).
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}
    event = body.get("event") or ""
    if event not in ("transcript.data", "transcript.partial_data"):
        return {"ok": True}
    data = body.get("data") or {}
    inner = data.get("data") or {}
    words = inner.get("words") or []
    text = " ".join((w.get("text") or "").strip() for w in words).strip()
    if not text:
        return {"ok": True}
    bot = data.get("bot") or {}
    bot_id = bot.get("id") if isinstance(bot, dict) else None
    if not bot_id:
        return {"ok": True}
    # Solo acumulamos los finales (transcript.data) para el resumen parcial
    if event == "transcript.data":
        append_realtime_transcript(bot_id, text)
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
