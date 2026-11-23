import QtQuick
import QtQuick.Layouts

// A short notice near the bottom of the window that fades out by itself (click to dismiss). Screen
// readers announce it; it stays while the pointer is over it, and longer text stays long enough
// to read.
Rectangle {
    id: toast

    // The shortest time a notice stays, in ms. Longer text adds about 60 ms per character (a
    // comfortable reading pace), up to 15 seconds.
    property int duration: 4500
    readonly property int _shownFor: Math.min(15000, Math.max(toast.duration, 1500 + 60 * label.text.length))

    function show(message) {
        if (!message) return
        label.text = message
        toast.opacity = 1
        hideTimer.restart()
        label.Accessible.announce(message)
    }

    implicitWidth: Math.min(row.implicitWidth + 2 * Theme.spaceLg, 560)
    implicitHeight: row.implicitHeight + 2 * Theme.spaceMd
    radius: Theme.radiusLarge
    color: Theme.inverseSurface
    opacity: 0
    visible: opacity > 0

    Behavior on opacity { NumberAnimation { duration: 180 } }

    Timer {
        id: hideTimer
        interval: toast._shownFor
        onTriggered: toast.opacity = 0
    }

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: Theme.spaceMd
        anchors.leftMargin: Theme.spaceLg
        anchors.rightMargin: Theme.spaceLg
        spacing: Theme.spaceSm

        Icon {
            name: "info"
            size: Theme.iconMd
            color: Theme.inverseText
        }
        Text {
            id: label
            textFormat: Text.PlainText
            Layout.fillWidth: true
            Layout.maximumWidth: 500
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.inverseText
            wrapMode: Text.WordWrap
            Accessible.role: Accessible.StaticText
            Accessible.name: label.text
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        onClicked: toast.opacity = 0
        onContainsMouseChanged: if (containsMouse) hideTimer.stop(); else if (toast.opacity > 0) hideTimer.restart()
    }
}
