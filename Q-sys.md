# El Q-SYS de la sala i el Magewell NMS

Aquest document recull què fa el sistema Q-SYS instal·lat a la sala, què fa el Magewell NMS i com han de conviure.
Està fet a partir de captures de pantalla del projecte Q-SYS Designer (12/11/2026), sense accés als fitxers del projecte.
Les deduccions que s'han de confirmar estan marcades amb **(per confirmar)**.

---

## 1. El sistema Q-SYS

| Element | Valor |
|---|---|
| Projecte | `UPC Aula Master 1.04` (Q-SYS Designer 10.1.0) |
| Processador | Core 110f, nom `Core-Aulamaster`, IP **192.168.100.38** |
| Panell d'usuari | UCI Viewer en un **iPad** |
| Pàgines del disseny | *Audio*, *Control*, *Tàctil* |

La IP del Core indica que la xarxa de vídeo deu ser **192.168.100.0/24** **(per confirmar)**. Si l'escaneig automàtic
del NMS no troba equips, és la primera subxarxa que cal provar (`MagewellNMS.exe scan --subnet 192.168.100.0/24`).

### 1.1 Pàgina «Control»

| Bloc | Components | Relació amb Magewell |
|---|---|---|
| **Encoders** | 7 plugins *Magewell Pro Convert Encoder*: Ponente 1, 2, 3, 4, 5, 6 i Equipo Aux | Directa |
| **Decoders** | 10 plugins *Magewell Pro Convert Decoder*: Monitor de Referencia 1–6, LED, Sala VIP, Sala Polivalente, Monitor Conf | Directa |
| **Matriu de vídeo** | Plugin de l'integrador **«Ruybesa / Matriz NDI Magewell 12x10»** i un *Text Controller «Preset Monitores»* (`SaveIn 1..10`, `SaveOut 1..10`) connectat a les entrades `guardar_preset_1..10` del plugin | Directa: és el nucli del control de vídeo |
| **Streaming** | Plugin *Magewell Ultra Encode Plus v1.0.2* | Magewell, però un model amb una API diferent (`/api/…`) |
| **Llums** | *Ruybesa / Emisor Art-Net (ArtDMX)* per a un Briteq BT-Theatre 60FCL i un LEDJ Performer 18 Hex MKII (al disseny hi ha anotada la taula de canals DMX) | Cap |
| **Taula de mescles** | *Behringer X32 OSC v1.2* | Cap |
| **Monitors** | 3× *Philips BFL2214 SICP v1.0.3* (encendre, apagar, estat) i un *Text Controller «Preset Monitores»* (Load, Save, MonOn, MonOff) | Cap |
| **Càmeres** | 3× *Canon CR-N300 VISCA IP v1.1.0* (encesa, presets, *tracking*) i un *Text Controller «Preset Cámaras»* | Indirecta: les càmeres també són fonts NDI de la matriu |
| **Macros** | Macros d'encendre i apagar la sala | Orquestren-ho tot |
| **Navegación_Controller** | Navegació de menús del panell tàctil (Comenzar, Apagar, Menu 1–6, SubTab 1–4, Config 1–4…) | Cap |

Al costat del plugin de la matriu hi ha aquesta nota: *«Este fichero se localiza en Documents\QSC\Q-SYS Designer\Plugins;
si se modifica algo hay que reiniciar el Design y actualizar este componente»*. El plugin és, per tant, un fitxer
`.qplug` local fet per l'integrador.

Els plugins d'encoder i decoder no tenen cap cable connectat. Sembla que la matriu parla directament amb els equips
per la xarxa i que aquests plugins només serveixen per veure'n l'estat **(per confirmar)**.

### 1.2 Pàgina «Audio»

Dante RX/TX per software → sortides 7 i 8 de la X32 («Amp Aula L/R») → Router 3x4 (amb generador de soroll rosa) →
2 crossovers i 2 delays → amplificador **CX-Q 8K8** → altaveus AD-S282H (Speaker-13, 14) i AD-S6 (Speaker-15, 16).

Tot aquest processament es fa dins del Core. Els amplificadors CX-Q són amplificadors de xarxa Q-SYS i necessiten un Core
per funcionar.

### 1.3 Pàgina «Tàctil»: pantalla «Video» de l'iPad

**Matriu de 12 fonts × 10 sortides:**

| Files (fonts) | Columnes (sortides) |
|---|---|
| Ponente 1–5, PC Faristol, Equipo Aux, Cam Escenari, Cam Lateral, Cam Tras Drt, Cam Tras Esq, vMix Output 1 | Monitor Ref. 1–6, LED, Sala VIP, Sala Polivalente, Sala Config. |

- **Cel·la verda**: la font que mostra la sortida. Cada sortida té una sola font.
- **Fila «Sin señal»**: un botó **OFF** per sortida (`btn_off_1..10`). En vermell vol dir que la sortida està apagada.
- **LEDs online**: un per cada entrada (`led_online_entrada_1..12`) i un per cada sortida (`led_online_salida_*`).
- **Presets**: 10 botons «Guardar N», 10 botons «Preset N» i dos indicadors per preset, «Memorizado» i «Activo».
- **Menú lateral**: Video, Sonido, Cámaras, Monitores i Salir.

Estat en el moment de la captura: Ponente 2 surt als Monitors de Referència 1–6, PC Faristol surt a LED i a Sala
Polivalente, i Sala VIP i Sala Config. estan en OFF. Hi ha 3 presets desats.

**Correspondència entre fonts i equips (per confirmar):** hi ha 7 encoders Magewell i 12 fonts. El més probable és:

| Font de la matriu | Origen |
|---|---|
| Ponente 1–5 | Encoders Magewell Ponente 1–5 |
| PC Faristol | Encoder Magewell «Ponente 6» |
| Equipo Aux | Encoder Magewell «Equipo Aux» |
| Cam Escenari, Cam Lateral, Cam Tras Drt, Cam Tras Esq | Càmeres amb NDI propi (les Canon CR-N300 emeten NDI). Al disseny només hi ha 3 Canon; la quarta càmera està per identificar. |
| vMix Output 1 | PC amb vMix (font NDI per software) |

---

## 2. Comparació amb el Magewell NMS (només la part de vídeo Magewell)

| Funcionalitat | Q-SYS | Magewell NMS | Què caldria per tenir-la al NMS |
|---|---|---|---|
| Canviar la font d'un decoder | Sí | Sí (`set-channel`, pestanya *Enrutament*) | Ja hi és |
| Fonts NDI que no són Magewell (càmeres, vMix) | Sí | Sí, les descobreix soles | Ja hi és |
| Noms amigables i ordre fix de les fonts | Sí | Només per als equips Magewell (`devices[].name`) | Àlies de fonts a `config.yaml`. Dificultat baixa. |
| 10 presets per desar i recuperar l'enrutament | Sí | No | Un preset és una llista de parells decoder → font, desada en un fitxer. Recuperar-lo és fer un `set-channel` per decoder. «Actiu» vol dir que l'estat actual coincideix amb el preset. Dificultat baixa. |
| OFF / «Sin señal» per sortida | Sí | No | Encara no sabem quina crida fa el plugin (font buida, font inexistent o una altra ordre). Cal llegir el `.qplug`. |
| Estat online d'entrades i sortides | Sí, un LED | Sí, i més complet: senyal, format, temperatura, frames perduts, receptors | Ja ho supera |
| Alertes, historial, avís sonor, descobriment de la xarxa, resposta crua de l'API | No | Sí | Avantatge del NMS |
| Panell tàctil per a usuaris no tècnics | Sí (iPad) | No: el NMS només escolta a 127.0.0.1 i té una interfície de tècnic | Obrir-lo a la xarxa (`serve --host 0.0.0.0`), afegir una vista tàctil simplificada i un PIN. Dificultat mitjana. |
| Streaming amb Ultra Encode Plus | Sí | No | API diferent (`/api/…`). Cal la documentació i fer una captura a la sala. Dificultat mitjana. |

**Conclusió:** el que fa el Q-SYS amb els Magewell (enrutar, presets, OFF i estat online) es pot igualar al NMS.
L'única incògnita tècnica és com funciona l'OFF.

---

## 3. El que no ha de fer el NMS

- **Àudio**: el processament i els amplificadors CX-Q depenen del Core. El Q-SYS es queda a la sala igualment.
- **Llums (Art-Net), X32 (OSC), pantalles Philips (SICP) i càmeres Canon (VISCA IP)**: els protocols són coneguts i es
  podrien implementar, però seria refer el sistema de control de la sala, sense equips per provar-ho i duplicant
  el que ja funciona.
- **Ser el sistema principal de la sala**: el Core és un aparell dedicat i sempre encès; el NMS depèn que un PC
  amb Windows estigui engegat.

---

## 4. Riscos de fer servir les dues eines alhora

1. **Desincronització de la matriu.** Si el NMS canvia la font d'un decoder, la pantalla de l'iPad pot continuar
   mostrant l'enrutament antic, i un preset pot sortir com a «Activo» sense ser-ho. Passarà o no segons si el plugin
   de Ruybesa consulta els equips periòdicament (`get-channel`) o només recorda l'últim botó premut.
2. **Sessions.** Els dos sistemes fan login als equips amb el mateix compte (Admin). Cal comprovar que un login del NMS
   no tanca la sessió del Q-SYS, ni a l'inrevés.
3. **Canvis en ple acte.** Per això la matriu del NMS arrenca bloquejada. Fins que no estigui clar el punt 1, el NMS
   només s'hauria de fer servir per enrutar en cas d'emergència.

---

## 5. Recomanació

1. **Primer, recollir informació (abans de programar res):**
   - Copiar els fitxers `.qplug` de `Documents\QSC\Q-SYS Designer\Plugins` del PC de la sala: el de Ruybesa
     («Matriz NDI Magewell 12x10») i, si hi són, els de Magewell Encoder, Decoder i Ultra Encode. Normalment són Lua
     llegible. Els fem servir per entendre quines crides fan; el codi no el copiem.
   - Copiar el contingut dels *Text Controller* de presets (per conèixer el format dels presets desats).
   - Exportar o fotografiar la pestanya *UCI Script* i la llista de *Named Controls*.
   - Fer `MagewellNMS.exe capture` de tots els equips, com indica el README.
2. **Enfocament:** el NMS és l'eina del tècnic (supervisió, alertes, diagnosi i enrutament d'emergència) i el Q-SYS
   continua sent el control de la sala per als usuaris. Al NMS s'hi poden afegir àlies, presets i OFF.
3. **Si cal que els dos estiguin sincronitzats:** el Q-SYS té un protocol de control remot, **QRC** (JSON-RPC per TCP,
   port 1710). Amb ell el NMS podria llegir l'estat de la matriu o disparar els presets *a través* del Q-SYS, en lloc
   d'anar directament als equips, i no hi hauria desincronització. Caldria que l'integrador publiqués els controls com a
   *Named Controls*.
4. **Ultra Encode Plus:** és l'únic equip nou que té sentit afegir-hi, perquè també és Magewell. Abans cal fer-ne una
   captura a la sala.

---

## 6. Preguntes per a l'integrador (Ruybesa) o per a la UPC

- Què envia el plugin quan es prem **OFF** en una sortida?
- El plugin llegeix periòdicament la font actual de cada decoder, o només recorda l'últim canvi?
- Quines són exactament les 12 fonts NDI (noms NDI complets) i quin equip hi ha darrere de cada una?
- És possible activar QRC i publicar com a *Named Controls* la matriu i els presets?
- Per a què es fan servir els plugins d'encoder i decoder que no tenen cables connectats?
