/*
 * Widget de Plasma para Beto, el asistente de la abuela.
 *
 * Todo sale de la Pi: corre `ssh pi asistente/panel.py <orden>` (alias "pi"
 * de ~/.ssh/config, por Tailscale) y lee la respuesta en JSON. Los textos
 * (un recordatorio nuevo) viajan codificados y se decodifican antes de
 * mandarlos por la entrada estándar: nunca se meten crudos en un comando.
 * No usa a Claude ni gasta tokens.
 */
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami
import org.kde.notification
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    readonly property string ssh: "ssh -o BatchMode=yes -o ConnectTimeout=6 pi asistente/panel.py"
    readonly property string statusCmd: ssh + " estado"
    readonly property string repo: "https://github.com/AnaPaulaMach/asistente-para-abuela"
    readonly property url icono: Qt.resolvedUrl("../icons/beto.svg")
    readonly property color rosa: "#f472b6"

    property var d: null              // el último estado que mandó la Pi
    property string updated: ""
    property string statusError: ""
    property string errorText: ""
    property string infoText: ""
    property string busy: ""          // qué se está haciendo ("Subiendo el volumen…")
    property var actions: ({})        // comando -> {que, listo}
    property bool verCharla: false    // la charla del día se muestra solo si se pide
    property var previous: null       // {charla, alcanzable} de la consulta anterior

    Plasmoid.icon: "audio-speakers"
    toolTipMainText: "Beto"
    toolTipSubText: summary()
    switchWidth: Kirigami.Units.gridUnit * 16
    switchHeight: Kirigami.Units.gridUnit * 10
    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar
                             ? fullRepresentation : compactRepresentation

    // ---- utilidades -------------------------------------------------------
    function activo(s) { return s === "active" }
    function overallColor() {
        if (statusError || !d) return Kirigami.Theme.negativeTextColor
        if (!activo(d.servicios.charla)) return Kirigami.Theme.negativeTextColor
        if (!activo(d.servicios.luces)) return Kirigami.Theme.neutralTextColor
        return Kirigami.Theme.positiveTextColor
    }
    function summary() {
        if (statusError) return "No llego a la Pi"
        if (!d) return "Consultando…"
        const charla = activo(d.servicios.charla) ? "charla activa" : "charla DETENIDA"
        return charla + (d.radio ? " · 📻 " + d.radio : "") + " · volumen " + (d.volumen ?? "?") + "/10 · " + d.recordatorios.length + " recordatorios"
    }
    function cuando(dias) {
        return dias === 0 ? "¡hoy!" : dias === 1 ? "mañana" : "en " + dias + " días"
    }
    function plata(n) { return "USD " + Number(n || 0).toFixed(2) }

    // ---- notificaciones ---------------------------------------------------
    Component {
        id: notificationComponent
        Notification {
            componentName: "plasma_workspace"
            eventId: "notification"
            iconName: "audio-speakers"
            autoDelete: true
        }
    }
    function notify(title, text) {
        notificationComponent.createObject(root, { title: title, text: text }).sendEvent()
    }
    function checkChanges() {
        const now = { charla: d ? d.servicios.charla : "", alcanzable: !statusError }
        if (previous !== null) {
            if (previous.alcanzable && !now.alcanzable)
                notify("Beto: no llego a la Pi", "¿Se cortó la luz o el WiFi en la casa de la abuela?")
            if (now.alcanzable && activo(previous.charla) && !activo(now.charla))
                notify("Beto: la charla se detuvo", "El servicio de charla no está activo.")
        }
        previous = now
    }

    // ---- procesos ---------------------------------------------------------
    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source)
            root.handleResult(source, data["exit code"], data["stdout"] || "", data["stderr"] || "")
        }
    }

    Timer {
        interval: 60 * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    function refresh() { exec.connectSource(statusCmd) }

    function ultimaLinea(stdout) {
        const lineas = stdout.trim().split("\n")
        return lineas[lineas.length - 1]
    }

    function handleResult(source, code, stdout, stderr) {
        if (source === statusCmd) {
            let r = null
            try { r = JSON.parse(ultimaLinea(stdout)) } catch (e) { r = null }
            if (!r) statusError = stderr.trim().split("\n").pop() || "la Pi no contestó (código " + code + ")"
            else if (!r.ok) statusError = r.error
            else {
                statusError = ""
                d = r
                updated = new Date().toLocaleTimeString(Qt.locale("es_AR"), "HH:mm:ss")
            }
            checkChanges()
            return
        }
        const act = actions[source]
        if (!act) return
        const a = Object.assign({}, actions); delete a[source]; actions = a
        busy = ""
        let r = null
        try { r = JSON.parse(ultimaLinea(stdout)) } catch (e) { r = null }
        if (r && r.ok) { errorText = ""; infoText = "✓ " + act.listo }
        else { infoText = ""; errorText = (r && r.error) || stderr.trim() || ("código " + code) }
        refresh()
    }

    // Una orden a la Pi. El texto viaja en %XX (encodeURIComponent: solo letras,
    // números y signos que no le importan al shell entre comillas dobles) y se
    // decodifica en la compu antes de entrar por la entrada estándar de ssh.
    function orden(args, texto, que, listo) {
        let cmd = ssh + " " + args
        if (texto !== undefined) {
            cmd = "printf %s \"" + encodeURIComponent(texto) + "\" | python3 -I -c "
                  + "'import sys,urllib.parse;sys.stdout.write(urllib.parse.unquote(sys.stdin.read()))' | " + cmd
        }
        const a = Object.assign({}, actions); a[cmd] = { listo: listo }; actions = a
        busy = que
        errorText = ""
        infoText = ""
        exec.connectSource(cmd)
    }

    function volumen(nivel) {
        nivel = Math.max(1, Math.min(10, nivel))
        orden("volumen " + nivel, undefined, "Cambiando el volumen…", "Volumen " + nivel + "/10")
    }

    // ---- interfaz ---------------------------------------------------------
    compactRepresentation: MouseArea {
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded
        Kirigami.Icon {
            anchors.fill: parent
            source: root.icono
            active: parent.containsMouse
        }
        Rectangle {
            width: Math.max(Kirigami.Units.smallSpacing * 2, Math.round(parent.width * 0.32))
            height: width
            radius: width / 2
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            color: root.overallColor()
            border.color: Kirigami.Theme.backgroundColor
            border.width: 1
        }
    }

    component Tarjeta: Rectangle {
        default property alias contenido: col.data
        property string titulo: ""
        Layout.fillWidth: true
        implicitHeight: col.implicitHeight + Kirigami.Units.smallSpacing * 2
        radius: Kirigami.Units.cornerRadius
        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                       Kirigami.Theme.textColor.b, hover.hovered ? 0.09 : 0.05)
        HoverHandler { id: hover }
        ColumnLayout {
            id: col
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            anchors.leftMargin: Kirigami.Units.largeSpacing
            spacing: 2
            PlasmaComponents3.Label {
                visible: parent.parent.titulo !== ""
                text: parent.parent.titulo
                font.bold: true
            }
        }
    }

    component Chico: PlasmaComponents3.Label {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        font: Kirigami.Theme.smallFont
        opacity: 0.75
        wrapMode: Text.WordWrap
    }

    fullRepresentation: ColumnLayout {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 20
        Layout.preferredWidth: Kirigami.Units.gridUnit * 25
        Layout.minimumHeight: implicitHeight
        Layout.preferredHeight: implicitHeight
        spacing: Kirigami.Units.smallSpacing

        // Encabezado: como el de los runners.
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: root.icono
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Kirigami.Heading {
                    level: 4
                    text: root.d ? root.d.nombre + ", el asistente de la abuela" : "Beto"
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                PlasmaComponents3.Label {
                    text: root.summary()
                    textFormat: Text.PlainText
                    font: Kirigami.Theme.smallFont
                    opacity: 0.8
                }
            }
            PlasmaComponents3.ToolButton {
                icon.name: "view-refresh"
                display: QQC2.AbstractButton.IconOnly
                text: "Actualizar"
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
                onClicked: root.refresh()
            }
            PlasmaComponents3.ToolButton {
                icon.name: "internet-services"
                display: QQC2.AbstractButton.IconOnly
                text: "Abrir el repositorio"
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
                onClicked: Qt.openUrlExternally(root.repo)
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: root.statusError !== ""
            type: Kirigami.MessageType.Error
            text: "No llego a la Pi: " + root.statusError
                  + "\n¿Está prendida y con internet? ¿Tailscale está conectado en esta compu?"
        }

        // Cómo está
        Tarjeta {
            visible: root.d !== null
            RowLayout {
                spacing: Kirigami.Units.largeSpacing
                Repeater {
                    model: root.d ? [["Charla", root.d.servicios.charla], ["Luces", root.d.servicios.luces]] : []
                    delegate: RowLayout {
                        required property var modelData
                        spacing: Kirigami.Units.smallSpacing
                        Rectangle {
                            width: Kirigami.Units.smallSpacing * 2.5
                            height: width
                            radius: width / 2
                            color: root.activo(modelData[1]) ? Kirigami.Theme.positiveTextColor
                                                              : Kirigami.Theme.negativeTextColor
                        }
                        PlasmaComponents3.Label {
                            text: modelData[0] + (root.activo(modelData[1]) ? "" : " (detenida)")
                            font.bold: true
                        }
                    }
                }
            }
            Chico {
                text: root.d ? "📶 " + (root.d.wifi || "sin WiFi") + " · 🌡 " + (root.d.temperatura ?? "?")
                               + " °C · prendida hace " + root.d.encendida_horas + " h" : ""
            }
        }

        // Radio (solo si está sonando)
        Tarjeta {
            visible: root.d !== null && !!root.d.radio
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: "📻 Sonando: " + (root.d ? root.d.radio : "")
                    font.bold: true
                    color: root.rosa
                }
                PlasmaComponents3.Button {
                    text: "Apagar"
                    icon.name: "media-playback-stop"
                    enabled: root.busy === ""
                    onClicked: root.orden("radio-apagar", undefined, "Apagando la radio…", "Radio apagada")
                }
            }
        }

        // Volumen
        Tarjeta {
            titulo: "Volumen"
            visible: root.d !== null
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.ToolButton {
                    icon.name: "audio-volume-low"
                    display: QQC2.AbstractButton.IconOnly
                    text: "Bajar"
                    enabled: root.busy === "" && root.d && root.d.volumen > 1
                    onClicked: root.volumen(root.d.volumen - 1)
                }
                PlasmaComponents3.Slider {
                    id: slider
                    Layout.fillWidth: true
                    from: 1; to: 10; stepSize: 1; snapMode: QQC2.Slider.SnapAlways
                    value: root.d && root.d.volumen ? root.d.volumen : 5
                    enabled: root.busy === ""
                    onPressedChanged: if (!pressed && root.d && value !== root.d.volumen) root.volumen(value)
                }
                PlasmaComponents3.ToolButton {
                    icon.name: "audio-volume-high"
                    display: QQC2.AbstractButton.IconOnly
                    text: "Subir"
                    enabled: root.busy === "" && root.d && root.d.volumen < 10
                    onClicked: root.volumen(root.d.volumen + 1)
                }
                PlasmaComponents3.Label {
                    text: (root.d ? root.d.volumen : "?") + "/10"
                    font.bold: true
                }
            }
        }

        // Recordatorios
        Tarjeta {
            titulo: "Recordatorios"
            visible: root.d !== null
            Chico {
                visible: root.d && root.d.recordatorios.length === 0
                text: "No hay recordatorios."
            }
            Repeater {
                model: root.d ? root.d.recordatorios : []
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    PlasmaComponents3.Label {
                        text: (modelData.fecha ? modelData.fecha + " " : "") + modelData.hora
                        font.family: "monospace"
                        color: root.rosa
                    }
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: modelData.texto
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                    }
                    PlasmaComponents3.ToolButton {
                        icon.name: "edit-delete-remove"
                        display: QQC2.AbstractButton.IconOnly
                        text: "Borrar"
                        enabled: root.busy === ""
                        QQC2.ToolTip.text: "Borrar el de las " + modelData.hora
                        QQC2.ToolTip.visible: hovered
                        onClicked: root.orden("recordatorio-borrar",
                                              (modelData.fecha ? modelData.fecha + " " : "") + modelData.hora + " " + modelData.texto,
                                              "Borrando…", "Borrado el de las " + modelData.hora)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.TextField {
                    id: nuevo
                    Layout.fillWidth: true
                    placeholderText: "09:00 Tomar la pastilla  (o 27/11 17:00 … para una sola vez)"
                    onAccepted: agregar.clicked()
                }
                PlasmaComponents3.Button {
                    id: agregar
                    text: "Agregar"
                    icon.name: "list-add"
                    enabled: root.busy === "" && nuevo.text.trim() !== ""
                    onClicked: {
                        root.orden("recordatorio-agregar", nuevo.text, "Agregando…", "Recordatorio agregado")
                        nuevo.text = ""
                    }
                }
            }
        }

        // Hoy: gasto y (si se pide) la charla
        Tarjeta {
            titulo: "Hoy"
            visible: root.d !== null
            Chico {
                opacity: 1
                text: root.d ? root.d.gasto.charlas_hoy + " charlas · " + root.plata(root.d.gasto.hoy)
                               + " hoy · " + root.plata(root.d.gasto.mes) + " en el mes" : ""
            }
            PlasmaComponents3.ToolButton {
                visible: root.d && root.d.frases.length > 0
                text: root.verCharla ? "Ocultar la charla" : "Ver la charla de hoy (" + (root.d ? root.d.frases.length : 0) + ")"
                icon.name: root.verCharla ? "view-hidden" : "view-visible"
                onClicked: root.verCharla = !root.verCharla
            }
            Repeater {
                model: root.verCharla && root.d ? root.d.frases : []
                delegate: Chico {
                    required property var modelData
                    opacity: modelData.quien === "ella" ? 1 : 0.65
                    text: (modelData.quien === "ella" ? "👵 " : "🤖 ") + modelData.texto
                }
            }
        }

        // Cumpleaños y notas
        Tarjeta {
            titulo: "Próximos cumpleaños"
            visible: root.d !== null && root.d.cumples.length > 0
            Repeater {
                model: root.d ? root.d.cumples : []
                delegate: Chico {
                    required property var modelData
                    opacity: modelData.dias <= 7 ? 1 : 0.75
                    text: "🎂 " + modelData.nombre + " · " + modelData.fecha + " · " + root.cuando(modelData.dias)
                }
            }
        }
        Tarjeta {
            titulo: "Notas de Beto"
            visible: root.d !== null
            Chico {
                visible: root.d && root.d.notas.length === 0
                text: "Todavía no hay notas: la memoria de Beto llega pronto."
            }
            Repeater {
                model: root.d ? root.d.notas : []
                delegate: Chico {
                    required property var modelData
                    opacity: 1
                    text: "• " + modelData
                }
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: root.errorText !== ""
            type: Kirigami.MessageType.Error
            showCloseButton: true
            text: root.errorText
            onVisibleChanged: if (!visible) root.errorText = ""
        }

        RowLayout {
            Layout.fillWidth: true
            PlasmaComponents3.ToolButton {
                text: "Probar luces"
                icon.name: "color-management"
                enabled: root.busy === "" && root.d !== null
                onClicked: root.orden("probar-luces", undefined, "Probando las luces…", "Luces probadas")
            }
            PlasmaComponents3.ToolButton {
                text: "Reiniciar charla"
                icon.name: "view-refresh"
                enabled: root.busy === "" && root.d !== null
                onClicked: root.orden("reiniciar", undefined, "Reiniciando la charla…", "Charla reiniciada")
            }
            Item { Layout.fillWidth: true }
            PlasmaComponents3.Label {
                text: root.busy !== "" ? root.busy : root.updated ? "Actualizado " + root.updated : "Consultando…"
                textFormat: Text.PlainText
                font: Kirigami.Theme.smallFont
                opacity: 0.6
            }
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            visible: root.infoText !== ""
            text: root.infoText
            textFormat: Text.PlainText
            font: Kirigami.Theme.smallFont
            opacity: 0.8
            wrapMode: Text.WordWrap
        }

        Item { Layout.fillHeight: true }
    }
}
