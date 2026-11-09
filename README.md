# Magewell Mini-NMS

Programa per a Windows que **escaneja la xarxa local, troba els equips Magewell Pro Convert**
(encoders i decoders NDI) i en mostra l'estat en una graella al navegador: si tenen senyal,
quin format, quina font NDI reben, temperatura, receptors connectats, alertes…

- No cal instal·lar res: és una carpeta amb `MagewellNMS.exe`.
- No cal internet ni drets d'administrador.
- Fa servir l'API HTTP oficial de Magewell (`/mwapi?method=…`), la mateixa que fa servir la web de l'equip.

---

## 1. Instal·lació a Windows

### Opció A: executable (recomanada)

1. Descarrega `MagewellNMS-windows.zip` (GitHub → *Actions* → *Build Windows* → últim build → *Artifacts*,
   o bé de *Releases* si s'ha creat un tag `v…`).
2. Descomprimeix-lo on vulguis (p. ex. `C:\MagewellNMS`).
3. Doble clic a `MagewellNMS.exe`.
   - Windows SmartScreen pot dir que és una aplicació desconeguda: *Més informació* → *Executa igualment*.
4. S'obre una finestra negra (el log) i el navegador amb el dashboard a `http://127.0.0.1:8000`.
   Per aturar el programa, tanca la finestra negra.

La primera vegada es crea `config.yaml` al costat de l'executable, i la carpeta `data\` amb:
`inventory.json` (equips coneguts), `events.log` (historial d'alertes) i `nms.log` (log tècnic).

### Opció B: des del codi font

Cal Python 3.10 o superior ([python.org](https://www.python.org/downloads/), marcant *Add python.exe to PATH*)
i internet la primera vegada. Doble clic a `Iniciar.bat`.

Per generar l'executable en un PC Windows: `packaging\build_windows.bat`.

---

## 2. Ús

En arrencar, el programa escaneja les xarxes del PC (cada 10 minuts per defecte) i afegeix
tots els Magewell que troba. Un equip descobert **no desapareix** si s'apaga: surt com a OFFLINE.

| Estat | Significat |
|---|---|
| **OK** | Té senyal i tot coincideix amb l'esperat |
| **SENSE SENYAL** | Encoder sense entrada HDMI/SDI, o decoder que no rep vídeo de la font NDI |
| **AVÍS** | Funciona però alguna cosa no és l'esperada: format, temperatura, frames perduts, pantalla desconnectada… |
| **AUTH** | Respon però l'usuari/contrasenya de `config.yaml` no és correcte |
| **OFFLINE** | No respon (cal fallar 2 cops seguits per evitar falses alarmes) |

- Clica una targeta per veure'n tots els detalls i **la resposta crua de l'API**.
- Clica els comptadors de dalt per filtrar per estat.
- Casella **So**: emet un avís sonor quan un equip passa a error.

### Ordres de consola

Obre `cmd` a la carpeta del programa:

```bat
MagewellNMS.exe                    :: dashboard (el mateix que el doble clic)
MagewellNMS.exe scan               :: escaneja i llista el que troba, sense obrir el dashboard
MagewellNMS.exe scan --subnet 10.0.20.0/24
MagewellNMS.exe capture            :: desa les respostes JSON de tots els equips en un .zip (diagnosi)
MagewellNMS.exe capture --ip 192.168.1.50
MagewellNMS.exe serve --host 0.0.0.0 --port 8080   :: accessible des d'altres PCs
```

(Des del codi font: `python -m app …` en lloc de `MagewellNMS.exe …`.)

---

## 3. Configuració (`config.yaml`)

Vegeu [config.example.yaml](config.example.yaml), on cada opció està comentada. El més habitual:

```yaml
credentials:            # es proven en ordre
  - username: Admin
    password: Admin     # valor de fàbrica

discovery:
  subnets: []           # buit = automàtic; o p. ex. ["192.168.1.0/24"]

defaults:
  expected:
    frame_rate: 50      # avisa si algun equip no treballa a 50

devices:                # opcional: noms, ubicacions i estat esperat per equip
  - ip: 192.168.1.101
    name: "Càmera 1 escenari"
    location: "Escenari"
    expected: { width: 1920, height: 1080, ndi_name: "SALA-CAM1" }
  - serial: "B401180706020"      # també per número de sèrie (no canvia si canvia la IP)
    name: "Projector principal"
    expected: { ndi_source: "REGIA (PGM)" }
```

Després d'editar-lo, prem **Recarregar config** al dashboard (no cal reiniciar).

---

## 4. Llista de comprovació per al primer dia a la sala

Fins ara el programa s'ha provat amb un **simulador** construït a partir de la documentació oficial de Magewell,
no amb equips reals. Per això, el primer dia:

1. **Xarxa**: connecta el PC a la mateixa xarxa/VLAN que els Magewell. Comprova amb `ipconfig` que la IP del PC
   és del mateix rang.
2. **Escaneig**: `MagewellNMS.exe scan`. Han de sortir com a `[MAGEWELL]`.
   - Si no en surt cap: posa la subxarxa a mà (`--subnet`) o revisa que els equips tinguin IP (DHCP).
   - Si surten com a `[magewell?]`: és un model amb una altra API (p. ex. sèrie *Pro Convert IP* o *Ultra*). Cal capturar-ne les respostes.
3. **Captura**: `MagewellNMS.exe capture` i guarda el `.zip` que genera (`data\captures\…`).
   **És el més important**: amb això es pot ajustar el programa als equips reals sense tornar a la sala.
   La captura només fa crides de lectura; no modifica cap equip.
4. **Dashboard**: obre `MagewellNMS.exe` i comprova:
   - Desendolla l'HDMI/SDI d'un encoder: ha de passar a SENSE SENYAL en 3-6 segons.
   - Canvia la font d'un decoder o atura l'emissor: el decoder ha de passar a SENSE SENYAL.
   - Clica una targeta i revisa que els valors (resolució, temperatura, nom NDI…) coincideixen amb la web de l'equip.
5. Porta el `.zip` de captures i `data\nms.log` per revisar-ho.

### Coses pendents de confirmar amb equips reals

- Format exacte de `input-state` i de `get-signal-info` quan no hi ha senyal.
- Als decoders: si `ndi.connected` + `video-width` reflecteixen bé que s'està rebent vídeo, i què retorna `get-channel`.
- Quant dura la sessió (el programa torna a fer login automàticament si caduca).
- Si teniu models més nous (*Pro Convert IP to HDMI*, *Ultra Encode*…), usen una API diferent (`/api/…`) i ara no se supervisen.

---

## 5. Proves sense equips (macOS / Linux / Windows)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m simulator              # terminal 1: 10 Magewell simulats a 127.0.0.1:9001-9010
.venv/bin/python -m app --config config.simulator.yaml    # terminal 2: dashboard
.venv/bin/python -m pytest                 # tests
```

El simulador implementa l'API (login MD5, cookie `sid`, codis d'estat) i provoca incidències
aleatòries (pèrdua de senyal, canvi de format, frames perduts, equip penjat).
`python -m simulator --calm` les desactiva.

Les captures reals que es copiïn a `tests/fixtures/captures/*.json` es proven automàticament amb `pytest`.

---

## 6. Estructura

```
app/
  __main__.py      ordres serve / scan / capture
  magewell/api.py  sessió HTTP amb un equip (login, cookie, reintents)
  magewell/parse.py  JSON de Magewell -> model intern (encoder / decoder)
  discovery.py     escaneig de xarxa
  registry.py      equips coneguts (config.yaml + descoberts, data/inventory.json)
  poller.py        sondeig d'un equip
  health.py        càlcul d'estat (OK / AVÍS / SENSE SENYAL…)
  service.py       orquestració (bucles, escaneig, esdeveniments)
  routes/api.py    API REST + Server-Sent Events
static/, templates/  dashboard (sense dependències externes; funciona sense internet)
simulator/       equips Magewell simulats
packaging/       PyInstaller i scripts de Windows
```

### API REST

| Mètode | Ruta | |
|---|---|---|
| GET | `/api/devices`, `/api/devices/{id}` | Estat dels equips |
| GET | `/api/devices/{id}/raw` | Últimes respostes JSON crues |
| DELETE | `/api/devices/{id}` | Oblidar un equip descobert |
| GET | `/api/summary`, `/api/alerts` | Resum i alertes |
| POST | `/api/poll-now`, `/api/discovery/scan`, `/api/reload-config`, `/api/alerts/clear` | Accions |
| GET | `/api/events` | Server-Sent Events per al dashboard |

Documentació de l'API de Magewell:
[encoders](https://www.magewell.com/api-docs/pro-convert-encoder-api/) ·
[decoders](https://www.magewell.com/api-docs/pro-convert-decoder-api/)
