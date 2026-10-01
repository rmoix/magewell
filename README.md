# Magewell Pro Convert Mini-NMS

Mini-NMS local, autònom i d'alta eficiència per a la supervisió contínua i en temps real d'una flota d'unitats Magewell Pro Convert (codificadors i descodificadors NDI/HDMI/SDI).

## Característiques Principals

1. **Sondeig Asíncron Concurrent:**
   - Inspecció en paral·lel de fins a 20+ unitats Magewell mitjançant les seves HTTP APIs natives (`get-summary-info`, `get-signal-info`, `get-device-info`).
   - Bounding de concurrència (`asyncio.Semaphore`) i connexions persistents Keep-Alive per evitar saturar la xarxa LAN o la CPU dels equips.
   - Aïllament total d'errors amb timeouts curts (2 segons).

2. **Auditoria Declarativa d'Estat (Drift Engine):**
   - Comparació contínua entre l'estat en viu i el fitxer `config/devices.yaml` (*Expected State*).
   - Detecció instantània de pèrdua de senyal d'entrada de vídeo HDMI/SDI (*No Signal Lock*).
   - Alerta visual de canvis de resolució (p. ex. esperat 1080p vs real 720p) o framerate (50 fps vs 60 fps).
   - Supervisió de sobreescalfament tèrmic i canvis accidentals de nom de flux NDI.

3. **Dashboard Web en Temps Real (Broadcast Multiviewer):**
   - Transmissió instantània de telemetria mitjançant Server-Sent Events (SSE).
   - Graella visual d'alta densitat (Multiview Grid / List View) amb tema fosc optimitzat per a sales de control i unitats mòbils (OB Van).
   - Filtres ràpids per ubicació (Studio A, Studio B, MCR, OB Van, Descodificadors) i per estat d'alerta.
   - Calaix de registre d'esdeveniments i alertes en viu.

---

## Requisits del Sistema

- Python 3.10 o superior
- Xarxa local (LAN) amb accés HTTP a les IPs dels equips Magewell

---

## Instal·lació

```bash
# 1. Instal·lar dependències
pip install -r requirements.txt
```

---

## Configuració (`config/devices.yaml`)

El fitxer `config/devices.yaml` defineix la política de sondeig i la llista d'equips amb el seu estat esperat:

```yaml
polling:
  interval_seconds: 3.0
  timeout_seconds: 2.0
  concurrency_limit: 5

devices:
  - id: "mw-cam-01"
    name: "Studio A - Cam 1 (Main Wide)"
    ip: "192.168.10.101"
    port: 80
    model: "Pro Convert HDMI Plus"
    role: "Encoder"
    location: "Studio A"
    auth:
      username: "admin"
      password: "password123"
    expected:
      signal_locked: true
      width: 1920
      height: 1080
      frame_rate: 50.0
      color_format: "YUV422"
      max_temperature_c: 65.0
      ndi_name: "STUDIO-A-CAM1"
```

---

## Execució de l'Aplicació

Pots iniciar el servidor local amb Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Obre el navegador a: `http://localhost:8000`

---

## Endpoints de la REST API & SSE

- `GET /`: Panell web Multivisió NMS en viu.
- `GET /api/devices`: Llista l'estat en viu i telemetria de tots els equips.
- `GET /api/devices/{id}`: Detalls d'un dispositiu per ID o IP.
- `GET /api/summary`: Mètriques de resum de la flota (total, online, ok, warnings, no_signal).
- `GET /api/alerts`: Historial d'alertes i transicions d'estat recents.
- `POST /api/alerts/clear`: Neteja el registre d'alertes.
- `POST /api/reload-config`: Recarrega el fitxer `devices.yaml` sense reiniciar el servei.
- `POST /api/poll-now`: Força un cicle de sondeig immediat.
- `GET /api/events`: Canal Server-Sent Events (SSE) per a actualitzacions en viu.

---

## Execució de Tests Automatitzats

```bash
pytest
```
