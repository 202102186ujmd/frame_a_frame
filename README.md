# frame_a_frame

Servicio Python que captura frames individuales desde streams WebRTC de MediaMTX
(usando Playwright + canvas) y los expone por HTTP, MJPEG y WebSocket con un
visor web integrado.

---

## Arquitectura

```
MediaMTX ─► Playwright (Chromium headless + Xvfb)
                │ canvas.toDataURL()
                ▼
          ChannelStore (buffer JPEG en memoria)
          ┌─────────────────────────────┐
          │  HTTP  GET /{id}/frame.jpg  │
          │  HTTP  GET /{id}/stream.mjpg│
          │  HTTP  GET /status[/{id}]   │
          │  HTTP  GET /health          │
          │  WS    GET /ws              │
          │  HTTP  GET /  (visor web)   │
          └─────────────────────────────┘
```

### Estructura de archivos

```
frame_capture.py          ← punto de entrada (Docker / pm2)
drone_config.py           ← configuración y lista de drones
channel_store.py          ← ChannelStore + registro global
drone_worker.py           ← loop Playwright por drone + watchdog
js_scripts.py             ← snippets JS inyectados en la página
utils.py                  ← configuración de logging
healthcheck.py            ← script de healthcheck para Docker
servers/
  http_server.py          ← handlers HTTP + build_app()
  ws_server.py            ← handler WebSocket
  html_templates.py       ← template HTML del visor web
static/
  index.html              ← visor web (servido en /static/index.html)
```

---

## Drones configurados (por defecto)

| ID      | Canal MediaMTX              |
|---------|-----------------------------|
| DC1001  | …/Castillo001               |
| DC1002  | …/Mjsp002                   |
| DC1003  | …/DCI003                    |

Las URLs completas (con credenciales) están definidas como valores por defecto
en `drone_config.py` y se pueden sobreescribir con variables de entorno
(ver `.env.example`).

---

## Inicio rápido

### Sin Docker

```bash
# 1. Instalar dependencias
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# 2. (Linux) Iniciar display virtual
Xvfb :99 -screen 0 1280x720x24 -ac &
export DISPLAY=:99

# 3. (Opcional) Copiar y editar variables de entorno
cp .env.example .env

# 4. Ejecutar
python frame_capture.py
```

Abre <http://localhost:8080> en tu navegador.

### Con Docker Compose

```bash
# Construir e iniciar
docker compose up -d --build

# Ver logs
docker compose logs -f

# Detener
docker compose down
```

---

## Variables de entorno

Consulta `.env.example` para la lista completa.  Las más importantes:

| Variable           | Por defecto          | Descripción                          |
|--------------------|----------------------|--------------------------------------|
| `DRONE_DC1001_URL` | URL de Castillo001   | URL completa del drone DC1001        |
| `DRONE_DC1002_URL` | URL de Mjsp002       | URL completa del drone DC1002        |
| `DRONE_DC1003_URL` | URL de DCI003        | URL completa del drone DC1003        |
| `HTTP_PORT`        | `8080`               | Puerto de escucha                    |
| `CAPTURE_FPS`      | `1`                  | Frames por segundo a capturar        |
| `STALE_TIMEOUT`    | `10`                 | Segundos sin frame → estado *stale*  |
| `SSL_CERT`         | *(vacío)*            | Ruta al certificado TLS              |
| `SSL_KEY`          | *(vacío)*            | Ruta a la clave privada TLS          |

---

## SSL / HTTPS / WSS

Para habilitar HTTPS y WSS basta con proveer los paths de certificado y clave
mediante las variables `SSL_CERT` (ruta al certificado) y `SSL_KEY` (ruta a la
clave privada).  Los nombres de archivo recomendados son `fullchain.crt` y
`server.key`.

```bash
# .env
SSL_CERT=/ruta/a/fullchain.crt
SSL_KEY=/ruta/a/server.key
```

### Certificado auto-firmado (desarrollo)

```bash
openssl req -x509 -newkey rsa:4096 \
    -keyout server.key -out fullchain.crt \
    -days 365 -nodes \
    -subj "/CN=localhost"

SSL_CERT=$(pwd)/fullchain.crt SSL_KEY=$(pwd)/server.key python frame_capture.py
```

### Let's Encrypt / certbot (producción)

```bash
# Paths típicos de certbot (ajusta según tu dominio)
SSL_CERT=/etc/letsencrypt/live/tu-dominio.com/fullchain.pem
SSL_KEY=/etc/letsencrypt/live/tu-dominio.com/privkey.pem
```

### Con Docker Compose

Monta los archivos de certificado como volumen y agrega las variables al bloque
`environment`:

```yaml
services:
  frame_a_frame:
    volumes:
      - /etc/ssl/drone/fullchain.crt:/certs/fullchain.crt:ro
      - /etc/ssl/drone/server.key:/certs/server.key:ro
    environment:
      - SSL_CERT=/certs/fullchain.crt
      - SSL_KEY=/certs/server.key
```

El visor web detecta automáticamente `https:` y usa `wss://` para el WebSocket.

---

## Endpoints

| Método | Ruta                   | Descripción                               |
|--------|------------------------|-------------------------------------------|
| GET    | `/`                    | Visor web (todos los drones)              |
| GET    | `/{id}/frame.jpg`      | Último JPEG del drone `{id}`              |
| GET    | `/{id}/stream.mjpg`    | Stream MJPEG del drone `{id}`             |
| GET    | `/status`              | Estado JSON de todos los drones           |
| GET    | `/status/{id}`         | Estado JSON del drone `{id}`              |
| GET    | `/health`              | Healthcheck (para Docker / load balancer) |
| WS     | `/ws`                  | WebSocket: frames + estado en tiempo real |

---

## Estados del drone

| Estado       | Significado                                           |
|--------------|-------------------------------------------------------|
| `connecting` | Iniciando conexión / navegando a la URL               |
| `online`     | Frames llegando con normalidad                        |
| `offline`    | MediaMTX reportó *"stream not found"*                 |
| `stale`      | No se recibieron frames en los últimos N segundos     |
| `error`      | Error inesperado (ver campo `msg`)                    |

### Detección de "stream not found"

El worker detecta el mensaje **"stream not found, retrying in some seconds"** de
MediaMTX de dos formas complementarias:
1. **Evaluando el texto de la página** (`document.body.innerText`) antes de cada
   captura de canvas.
2. **Escuchando mensajes de consola** del navegador (`page.on("console", …)`).

Ambos caminos marcan el canal como `offline` inmediatamente.

---

## Visor web

- Muestra los tres drones en un grid responsivo.
- **Mantiene el último frame visible** cuando el drone queda offline, stale o
  en error – el overlay semitransparente aparece *encima* de la imagen, sin
  ocultarla.
- Reconexión automática del WebSocket con back-off exponencial.
- El badge de estado y el ícono de overlay cambian de color/icono según el
  estado actual.
