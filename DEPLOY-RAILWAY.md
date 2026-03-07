# Desplegar ResumenZoom en Railway (paso a paso)

Así la app corre 24/7 en la nube y no necesitás tener la compu prendida. Cuando termines una reunión en Zoom, Recall enviará el webhook a Railway y el resumen se generará solo.

---

## Paso 1: Cuenta en GitHub

1. Si no tenés: creá una cuenta en **https://github.com**.
2. Instalá **Git** en tu compu si no lo tenés: https://git-scm.com/downloads

---

## Paso 2: Subir el proyecto a GitHub

1. Abrí la terminal y entrá a la carpeta del proyecto:
   ```bash
   cd /Users/nicolasnovillo/Documents/zoom1
   ```

2. Inicializá el repo (si todavía no es un repositorio git):
   ```bash
   git init
   ```

3. Creá un repositorio nuevo en GitHub:
   - Entrá a https://github.com/new
   - Nombre: por ejemplo **resumenzoom**
   - Dejalo vacío (sin README, sin .gitignore). Crear.

4. Conectá tu carpeta con GitHub y subí el código (reemplazá `TU_USUARIO` por tu usuario de GitHub):
   ```bash
   git add .
   git commit -m "App ResumenZoom para Railway"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/resumenzoom.git
   git push -u origin main
   ```
   Te va a pedir usuario y contraseña de GitHub. Para la contraseña usá un **Personal Access Token** (GitHub ya no acepta contraseña normal): en GitHub → Settings → Developer settings → Personal access tokens → Generate new token. Usalo donde pide contraseña.

   **Importante:** El archivo `z.env` no se sube (está en .gitignore) para no exponer tus claves. Las vas a cargar en Railway en el siguiente paso.

---

## Paso 3: Cuenta en Railway

1. Entrá a **https://railway.app**
2. Clic en **Login** y elegí **Sign in with GitHub**.
3. Autorizá Railway para acceder a tu cuenta de GitHub.

---

## Paso 4: Crear el proyecto en Railway

1. En el panel de Railway, clic en **New Project**.
2. Elegí **Deploy from GitHub repo**.
3. Si te pide conectar GitHub, autorizá y elegí el repositorio **resumenzoom** (o el nombre que hayas puesto).
4. Railway va a detectar el proyecto y empezar a desplegar. Si no detecta bien, en el siguiente paso lo configuramos.

---

## Paso 5: Configurar variables de entorno

1. En tu proyecto de Railway, clic en el **servicio** (el cuadro que representa tu app).
2. Entrá a la pestaña **Variables** (Variables o Environment).
3. Clic en **Add Variable** o **Raw Editor** y agregá **una por una** estas variables (usá los valores que tenés en tu `z.env` en la compu):

   | Variable          | Valor (ejemplo)                    |
   |-------------------|------------------------------------|
   | `RECALL_API_KEY`  | tu clave de Recall.ai              |
   | `RECALL_REGION`   | `us-west-2`                        |
   | `OPENAI_API_KEY`  | tu clave de OpenAI                 |
   | `ZOOM_ACCOUNT_ID` | (opcional, si usás Zoom)           |
   | `ZOOM_CLIENT_ID`  | (opcional)                         |
   | `ZOOM_CLIENT_SECRET` | (opcional)                      |

   No subas `z.env` a GitHub; copiá solo los valores y pegálos en Railway.

4. Guardá. Railway va a redesplegar solo con los nuevos valores.

---

## Paso 6: Configurar el comando de inicio (si hace falta)

1. En el mismo servicio, entrá a **Settings**.
2. En **Build Command** podés dejar vacío (Railway usa `pip install -r requirements.txt` por defecto).
3. En **Start Command** (o "Custom start command") poné:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port $PORT
   ```
   Si Railway ya tomó el **Procfile** que está en el repo, no hace falta cambiar nada; el Procfile ya dice eso.

4. Guardá.

---

## Paso 7: Obtener la URL pública

1. En tu servicio, entrá a la pestaña **Settings**.
2. Bajá hasta **Networking** o **Public Networking**.
3. Clic en **Generate Domain** (o "Add public domain"). Railway te va a dar una URL tipo:
   ```
   https://resumenzoom-production-xxxx.up.railway.app
   ```
4. Copiá esa URL. Es la dirección de tu app 24/7.

---

## Paso 8: Configurar el webhook en Recall

1. Entrá al dashboard de **Recall.ai** (donde gestionás los bots).
2. Buscá la sección de **Webhooks** o **Webhook URL**.
3. Pegá la URL de Railway y agregá al final:
   ```
   /webhooks/recall
   ```
   Ejemplo:
   ```
   https://resumenzoom-production-xxxx.up.railway.app/webhooks/recall
   ```
4. Guardá. Desde ahora, cuando una reunión termine, Recall enviará los avisos a esa URL.

---

## Paso 9: Probar

1. Abrí en el navegador la URL de Railway (la que generaste en el paso 7).
2. Deberías ver la pantalla de ResumenZoom (Iniciar reunión, Ver resumen).
3. Probá **Enviar bots a la reunión** con una URL de Zoom y, después de terminar la reunión, **Ver resumen** con el ID. El resumen debería generarse aunque tu compu esté apagada.

---

## Resumen

| Paso | Qué hiciste |
|------|-------------|
| 1–2 | Proyecto en GitHub (sin subir `z.env`) |
| 3–4 | Cuenta Railway y proyecto desde GitHub |
| 5   | Variables de entorno en Railway (claves de Recall, OpenAI, etc.) |
| 6   | Comando de inicio (Procfile o Start Command) |
| 7   | URL pública de Railway |
| 8   | Esa URL + `/webhooks/recall` en Recall.ai |
| 9   | Probar desde el navegador |

Si algo falla (error al desplegar, 502, etc.), revisá en Railway la pestaña **Deployments** y los **logs** del último deploy para ver el mensaje de error.
