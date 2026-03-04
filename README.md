# Resumen Zoom – Todas las salas

Herramienta para ISP o equipos que hacen muchas reuniones en Zoom con **salas de trabajo (breakout rooms)**. Al terminar la reunión, obtenés **un solo resumen** de lo que pasó en la sala principal y en cada sala.

Hay **dos modos de uso**:

- **Automático (sin intervención durante/después de la reunión)**: usás [Recall.ai](https://recall.ai) para enviar bots que graban la sala principal y cada breakout. Cuando termina la reunión, el servidor junta todas las transcripciones y genera el resumen solo.
- **Manual**: traés la transcripción de la sala principal (Zoom API o pegando texto) y agregás vos el texto de cada sala; después generás el resumen.

---

## Modo automático (Recall.ai) – sin interacción humana

En este modo **no hace falta** que nadie pegue transcripciones ni tome notas. El flujo es:

1. **Antes de la reunión**: En Recall.ai creás una API key y configurás la **URL de webhook** para que apunte a tu servidor:  
   `https://tu-dominio.com/webhooks/recall`  
   (En desarrollo podés usar [ngrok](https://ngrok.com) para exponer tu localhost.)

2. **Al iniciar la reunión**: Hacés un `POST /reuniones/iniciar` con la URL de la reunión Zoom. Eso envía **un bot a la sala principal** (ese bot no entra a los breakouts).

3. **En Zoom**: Cuando abras las salas de trabajo, tenés que usar la opción **“Dejar que los participantes elijan sala”** (o equivalente). Así Recall puede detectar cada sala y enviar un webhook.

4. **Automático**: Cada vez que se abre una sala, tu servidor recibe un webhook y **crea otro bot** que entra solo a esa sala. Cada bot graba y transcribe su sala.

5. **Al terminar la reunión**: Cuando todos los bots terminan, el servidor **descarga las transcripciones**, las junta y **genera el resumen**. Podés ver el resultado con `GET /reuniones/{session_id}`.

**Requisitos modo automático**:
- Cuenta en [Recall.ai](https://recall.ai) y API key.
- Servidor accesible por internet para recibir webhooks (ej. deploy en Railway, Render, Fly.io, o ngrok en local).
- En Zoom: crear los breakouts con **“Dejar que los participantes elijan sala”** para que Recall reciba `bot.breakout_room_opened` y pueda crear un bot por sala.

**Variables de entorno** (además de `OPENAI_API_KEY`):
- `RECALL_API_KEY`: tu API key de Recall.ai.
- `RECALL_REGION`: región del dashboard (ej. `us-east-1`, `eu-central-1`).

---

## Modo manual (Zoom + texto por sala)

Si no usás Recall.ai, podés seguir usando la app así:

- **Transcripción de la sala principal**: desde la grabación en la nube de Zoom (API) o pegando el texto.
- **Salas de trabajo**: Zoom no graba cada breakout en la nube; tenés que **agregar vos** el texto de cada sala (notas, transcripción de una grabación local, etc.).
- **Resumen**: la app une todo y genera un único resumen.

## Limitación importante de Zoom

- **La grabación en la nube de Zoom solo graba la sala principal.** No existe (hoy) grabación en la nube por cada breakout room.
- En modo manual, para tener contenido de cada sala tenés que grabar localmente y/o tomar notas y cargar el texto en la app.
- En modo automático, Recall.ai pone **un bot por sala** (cada bot graba y transcribe su sala); por eso no hace falta intervención humana para el contenido de las salas.

Esta app combina:
- La **transcripción de la sala principal** (Zoom API o Recall),
- Las **transcripciones de cada sala** (Recall en modo auto, o texto que agregues en modo manual),
y genera **un único resumen** con todo.

## Requisitos

- Python 3.10+
- **OpenAI**: API key para generar el resumen (`OPENAI_API_KEY`).
- **Modo manual**: Cuenta Zoom con grabación en la nube (Pro o superior), transcripción activada, y app en [Zoom Marketplace](https://marketplace.zoom.us/) (Server-to-Server OAuth, scope `recording:read`).
- **Modo automático**: Cuenta [Recall.ai](https://recall.ai), API key, y servidor con URL pública para webhooks.

## Configuración

1. Cloná o copiá el proyecto y creá un entorno virtual:

   ```bash
   cd zoom1
   python3 -m venv .venv
   source .venv/bin/activate   # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copiá `.env.example` a `.env` y completalo según el modo:
   - **OpenAI** (obligatorio): `OPENAI_API_KEY`
   - **Modo manual**: `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`
   - **Modo automático**: `RECALL_API_KEY`, `RECALL_REGION`

3. Arrancá el servidor:

   ```bash
   uvicorn app:app --reload
   ```

4. Abrí en el navegador: **http://127.0.0.1:8000**

## Uso (modo manual)

1. **Sala principal**
   - Podés poner el **ID de la reunión** Zoom y hacer clic en **“Obtener transcripción”** (usa la grabación en la nube de esa reunión).
   - O pegar directamente la transcripción de la sala principal en el cuadro de texto.

2. **Salas de trabajo**
   - Para cada breakout room, hacé clic en **“+ Añadir sala”**, poné un nombre (ej. “Sala 1”, “Equipo Comercial”) y pegá el texto o transcripción de esa sala.

3. **Resumen**
   - Clic en **“Generar resumen de todas las salas”**. La app une sala principal + todas las salas y devuelve un único resumen en español.

## API

- `GET /zoom/grabaciones` – Lista grabaciones recientes (modo manual).
- `GET /zoom/reuniones/{meeting_id}/transcript` – Transcripción de la reunión (sala principal) desde Zoom.
- `POST /resumen` – Genera resumen a partir de `sala_principal` y `salas_breakout` (modo manual).
- **Modo automático**:
  - `POST /reuniones/iniciar` – Body: `{ "meeting_url": "https://zoom.us/j/..." }`. Devuelve `session_id` y envía el bot a la sala principal.
  - `GET /reuniones/{session_id}` – Estado de la sesión y resumen cuando esté listo.
  - `POST /webhooks/recall` – URL que tenés que configurar en Recall.ai como webhook (tu servidor debe ser accesible por internet).

## Resumen de límites de Zoom

| Qué querés | Modo manual | Modo automático (Recall.ai) |
|------------|-------------|-----------------------------|
| Transcripción sala principal | Sí, vía Zoom API (grabación en la nube) o pegando texto | Sí, un bot graba la sala principal |
| Transcripción por cada breakout | No; hay que agregar texto a mano (notas, grabación local transcrita) | Sí; un bot por sala, sin intervención |
| Interacción humana | Sí: cargar transcripciones/notas de las salas | No; todo automático una vez configurado |

Con esta herramienta podés centralizar todo en un solo lugar y obtener un resumen unificado al final de cada reunión.
