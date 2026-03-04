"""
Genera un resumen unificado a partir de la transcripción de la sala principal
y las transcripciones de cada sala (breakout room).
"""
from openai import OpenAI
from config import OPENAI_API_KEY

SYSTEM_PROMPT = """Eres un asistente que resume reuniones de Zoom.
Te dan la transcripción de la sala principal y, opcionalmente, transcripciones de salas de trabajo (breakout rooms).
Genera UN solo resumen en español que cubra:
1. Resumen de lo tratado en la sala principal.
2. Por cada sala de trabajo: nombre de la sala y resumen de lo discutido ahí.
3. Conclusiones o puntos clave comunes si los hay.
Sé conciso pero completo. Usa viñetas para cada sala. No inventes contenido que no esté en las transcripciones."""


def generar_resumen(
    sala_principal: str | None,
    salas_breakout: list[dict],
    openai_api_key: str | None = None,
) -> str:
    """
    sala_principal: transcripción de la sala principal (puede ser None).
    salas_breakout: lista de { "nombre": "Sala 1", "transcripcion": "..." }.
    """
    key = openai_api_key or OPENAI_API_KEY
    if not key:
        raise ValueError("Falta OPENAI_API_KEY para generar el resumen.")

    parts = []
    if sala_principal and sala_principal.strip():
        parts.append("## Sala principal\n" + sala_principal.strip())
    for s in salas_breakout or []:
        name = s.get("nombre") or s.get("name") or "Sin nombre"
        trans = (s.get("transcripcion") or s.get("transcript") or "").strip()
        if trans:
            parts.append(f"## {name}\n{trans}")

    if not parts:
        return "No se proporcionó ninguna transcripción para resumir."

    user_content = "\n\n---\n\n".join(parts)

    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=2000,
    )
    return (resp.choices[0].message.content or "").strip()
