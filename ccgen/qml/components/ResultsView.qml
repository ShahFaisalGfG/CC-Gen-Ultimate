import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Live lines of the file being processed: the source text with its translation and
// transliteration underneath as the steps that make them reach each line.
ColumnLayout {
    id: view

    required property var controller
    property string emptyText: "Lines appear here as each file is processed."
    property string fileName: ""
    readonly property int count: lines.count
    property var _rowOfLine: ({})

    signal firstFileStarted()

    spacing: 0

    ListModel { id: lines }

    Connections {
        target: view.controller

        function onFileStarted(path, name) {
            lines.clear()
            view._rowOfLine = {}
            view.fileName = name
            if (view.controller.runPosition <= 1) view.firstFileStarted()
        }

        function onSegmentAdded(id, start, end, text, kind, step) {
            // Every step keeps its source line's id, so a translation or transliteration fills
            // the line it came from (a later step of the same kind shows its newer text).
            var row = view._rowOfLine[id]
            var role = kind === "translation" ? "segTranslation"
                : kind === "transliteration" ? "segTransliteration" : "segText"
            if (row === undefined) {
                view._rowOfLine[id] = lines.count
                lines.append({
                    segStart: start, segEnd: end,
                    segText: role === "segText" ? text : "",
                    segTranslation: role === "segTranslation" ? text : "",
                    segTransliteration: role === "segTransliteration" ? text : ""
                })
                return
            }
            lines.setProperty(row, role, text)
            if (role === "segText") {
                // A re-streamed transcript line carries its final timing.
                lines.setProperty(row, "segStart", start)
                lines.setProperty(row, "segEnd", end)
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Theme.spaceLg
        Layout.leftMargin: Theme.spaceXl
        Layout.rightMargin: Theme.spaceXl
        visible: view.fileName.length > 0

        Icon { name: "captions"; color: Theme.accent }
        Text {
            Layout.fillWidth: true
            text: view.fileName
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSubtitle
            font.weight: Font.DemiBold
            color: Theme.text
            elide: Text.ElideMiddle
            Accessible.role: Accessible.Heading
            Accessible.name: "Lines of " + text
        }
        Text {
            text: lines.count + " lines"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
        }
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.leftMargin: Theme.spaceLg
        Layout.rightMargin: Theme.spaceLg
        visible: lines.count > 0
        model: lines
        clip: true
        spacing: 2
        activeFocusOnTab: true
        boundsBehavior: Flickable.StopAtBounds
        Accessible.role: Accessible.List
        Accessible.name: "Lines"

        // Keep following new lines only while the user is already at the bottom.
        property bool follow: true
        onMovementEnded: follow = atYEnd
        onCountChanged: if (follow) Qt.callLater(positionViewAtEnd)

        delegate: SegmentItem {
            width: ListView.view.width
        }

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Keys.onUpPressed: flick(0, 800)
        Keys.onDownPressed: flick(0, -800)

        // Keyboard focus is shown, as on every other focusable part of the window.
        Rectangle {
            anchors.fill: parent
            z: 10
            color: "transparent"
            radius: Theme.radius
            border.width: 2
            border.color: Theme.focusRing
            visible: list.activeFocus
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: lines.count === 0
        spacing: Theme.spaceSm

        Item { Layout.fillHeight: true }
        Icon {
            Layout.alignment: Qt.AlignHCenter
            name: "captions"
            size: 32
            color: Theme.textMuted
        }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spaceXl
            Layout.rightMargin: Theme.spaceXl
            horizontalAlignment: Text.AlignHCenter
            text: view.controller.busy ? "Waiting for the first lines..." : view.emptyText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }
        Item { Layout.fillHeight: true }
    }
}
