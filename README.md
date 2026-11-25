# Asistente para abuela
**Un compañero de voz con un solo botón, para que mi abuela charle, pregunte y pida ayuda sin tocar un celular.**

Se llama Beto. Es un parlantito con un anillo de luces, un botón y una ruedita de volumen. Adentro tiene una Raspberry Pi que conversa con ella usando Gemini, le recuerda cosas, le cuenta el clima y, si algo pasa, me avisa por Telegram.

> *Pronto: foto del aparato y un video de una charla.*

---

## Un día con Beto

**A la mañana** el anillo respira despacito en rosa: está prendido y esperando.
A las 9 se pone **lila** y dice: *"Acordate de tomar la pastilla de la presión."* Ella toca el botón para avisar que ya la tomó, y Beto le contesta *"¡Muy bien! Gracias por avisarme."*. Si no lo toca, lo repite un par de veces y, si sigue sin respuesta, me llega un mensaje.

**Al mediodía** toca el botón y se pone **azul**: la está escuchando.
— *"Beto, ¿cómo está el día?"*
**Verde** mientras contesta: *"Hay 26 grados y está algo nublado. Puede que llueva un poco a la tarde."* (Ella les tiene miedo a las tormentas, así que Beto las nombra al pasar y con calma.)

**A la siesta** pregunta *"¿Qué pasó hoy en el pueblo?"* y Beto le cuenta dos o tres noticias de los diarios de su ciudad: el festival, el partido, quién viene a tocar. Las policiales y las tragedias se quedan afuera, salvo que ella pregunte justo por eso.

**Si quiere música** le pide *"poneme la radio"* o *"la de folklore"*, y Beto pone una de las emisoras de su ciudad. Un toque del botón la apaga y la deja hablar; si suena un recordatorio, la radio se pausa y vuelve sola.

**Por la tarde** tiene ganas de charlar. Beto sabe quién es la familia, cuándo cumplen años y qué le gusta. Si le hace una pregunta, se queda escuchando solo unos segundos, sin que tenga que tocar nada, porque ella tarda un poquito en arrancar a hablar. Y no la apura: espera a que termine, aunque haga pausas.

**Si habla bajito o le cuesta oír**, se gira la ruedita (o se le pide *"hablá más fuerte"*) y el anillo muestra una barrita blanca con el volumen.

**Si pasa algo**, mantiene apretado el botón dos segundos:
1. *"¿Es una emergencia? Si apretaste sin querer, tocá el botón. Si no, en diez segundos le aviso a tu familia."*
2. El anillo rojo se achica de a un segundo. Un toque lo cancela.
3. Si nadie lo cancela (por ejemplo, si se cayó y no puede contestar), **me llega un aviso por Telegram**.
4. Le ofrece grabar un mensaje: si toca el botón, la escucha 10 segundos y me manda el audio.

Las frases de emergencia están grabadas en el aparato: funcionan aunque Gemini no responda. Si no hay internet, lo dice, se pone naranja y sigue reintentando.

---

## Cómo lo cuido desde lejos

Beto vive en la casa de mi abuela y yo en la mía. Las dos computadoras están en una red privada con **Tailscale**: desde mi compu entro a la Pi como si estuviera al lado, sin abrir puertos en el router de nadie.

```mermaid
flowchart LR
    subgraph casa_abuela["Casa de la abuela"]
        beto["Beto<br/>Raspberry Pi + parlante + botón"]
        wifi1["WiFi de la casa"]
        beto --- wifi1
    end
    subgraph mi_casa["Mi casa (o donde esté)"]
        compu["Mi compu<br/>código, panel, ssh"]
    end
    subgraph nube["Internet"]
        gemini["Gemini Live<br/>la charla"]
        telegram["Telegram<br/>avisos y audios"]
        clima["Open-Meteo<br/>el clima"]
    end
    celu["Mi celular"]

    compu <-. "Tailscale<br/>(red privada)" .-> beto
    beto -- "voz" --> gemini
    beto -- "emergencias,<br/>recordatorios" --> telegram
    beto --> clima
    telegram --> celu
```

- **Telegram** me avisa en el celular: emergencias, recordatorios que no confirmó, y más adelante, audios de ida y vuelta con la familia.
- **Desde la compu** cambio recordatorios, ajusto cómo habla o actualizo el código, y lo copio a la Pi con un comando.
- *Pronto: captura del panel de control en el escritorio.*

**La privacidad, en serio:** las claves y los datos de la familia viven solo en la Pi, con permisos que solo puede leer su usuario. A la Pi se entra únicamente con una llave. Lo que se habla queda en el registro del aparato una semana y después se borra solo. Nada de eso está en este repositorio.

---

## Lo que tiene adentro

| Parte | Para qué |
|---|---|
| Raspberry Pi Zero 2 W | La computadora (Linux) |
| ReSpeaker 2-Mics Pi HAT v2.0 | Dos micrófonos y la salida al parlante |
| Parlante chico | La voz de Beto |
| 16 LEDs WS2812 en anillo | Los colores de cada estado |
| Un botón | Hablar, confirmar y emergencia |
| Encoder rotativo | El volumen |
| Carcasa impresa en 3D | Para que quede lindo en la mesa de luz |

**Cuánto cuesta por mes:** Telegram, Tailscale (uso personal) y Open-Meteo son gratis. Gemini se paga por uso: con unas tres charlas por día, alrededor de **USD 4 al mes**. El aparato anota lo que gasta cada charla.

### Los colores

| Luz | Qué está haciendo |
|---|---|
| 🩷 Rosa respirando | Esperando |
| 🔵 Azul | Escuchando |
| 🔵 Azul girando | Pensando (consulta el clima o las noticias, cambia el volumen) |
| 🟢 Verde | Hablando |
| ⚪ Barra blanca | Volumen |
| 🟣 Lila | Recordatorio |
| 🩷 Punto rosa girando | Suena la radio |
| 🟠 Naranja | Sin internet o algo falló |
| 🔴 Rojo | Emergencia |

---

## Para quien lo quiera armar

El paso a paso técnico está en [docs/como-funciona.md](docs/como-funciona.md). En corto:

- `asistente/`: el programa que corre en la Pi (charla, luces, emergencia, recordatorios, clima, volumen).
- `asistente/prompt/base.md`: cómo habla y qué puede hacer. Se edita como texto, sin tocar código.
- `ejemplos/`: plantillas de la configuración privada (claves, perfil, familia, recordatorios).
- `pruebas/`: los programitas de las primeras etapas (botón, Telegram, voces).
- `desplegar.sh`: copia el código de la compu a la Pi y reinicia.
- `widget-plasma/`: un widget para el escritorio KDE Plasma que muestra cómo está Beto y deja cambiar el volumen y los recordatorios. Se instala con `kpackagetool6 -t Plasma/Applet -i widget-plasma/local.betopanel`.

Lo construí de a una etapa por vez: primero que suene y que el botón ande, después Telegram, la charla, las luces, la emergencia y que arranque solo. Cada etapa se podía probar antes de pasar a la siguiente.
