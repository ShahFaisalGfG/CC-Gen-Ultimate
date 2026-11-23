import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A labeled single-line text box in Theme colors, with an optional error line (from the sister app
// gfgRoyal Media Downloader); the Workflow tab names a saved workflow with it.
ColumnLayout {
    id: field

    property string label: ""
    property string placeholderText: ""
    property string errorText: ""
    property string helpText: ""
    property string toolTipText: ""
    // What a screen reader calls the box when it has no visible label (the row's label beside it).
    property string accessibleName: ""
    property alias text: input.text
    property alias input: input
    // Controls drawn inside the box on its right (a paste button, a chip); the text stops before them.
    property alias trailing: trailingRow.data

    signal accepted()
    signal editingFinished()

    function selectInput() {
        input.selectAll()
        input.forceActiveFocus()
    }

    spacing: Theme.spaceXs

    Text {
        textFormat: Text.PlainText
        visible: field.label.length > 0
        text: field.label
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: field.enabled ? Theme.text : Theme.textMuted
        Accessible.ignored: true
    }

    TextField {
        id: input
        Layout.fillWidth: true
        implicitHeight: Theme.controlHeight
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: input.enabled ? Theme.text : Theme.textMuted
        selectByMouse: true
        leftPadding: 10
        rightPadding: 10 + (trailingRow.implicitWidth > 0 ? trailingRow.implicitWidth + 4 : 0)
        topPadding: 0
        bottomPadding: 0
        verticalAlignment: TextInput.AlignVCenter
        Accessible.name: field.accessibleName || field.label || field.placeholderText
        Accessible.description: field.errorText || field.helpText || field.toolTipText
        onAccepted: field.accepted()
        onEditingFinished: field.editingFinished()

        // Shown on hover, and when Tab brings the keyboard here (not when a page puts the caret in it).
        ToolTip.visible: field.toolTipText.length > 0 && (input.hovered || input.activeFocus
            && (input.focusReason === Qt.TabFocusReason || input.focusReason === Qt.BacktabFocusReason))
        ToolTip.text: field.toolTipText
        ToolTip.delay: 600

        background: Rectangle {
            radius: Theme.radius
            color: input.enabled ? Theme.surface : Theme.surfaceAlt
            border.width: input.activeFocus || field.errorText.length > 0 ? 2 : 1
            border.color: field.errorText.length > 0 ? Theme.danger
                : input.activeFocus ? Theme.focusRing
                : input.enabled ? Theme.inputBorder : Theme.border
        }

        // A plain centred placeholder. The Material style's own placeholder floats up to the top
        // border as a label, which, with no top padding, overlaps the field's edge.
        Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: input.leftPadding
            rightPadding: input.rightPadding
            visible: input.text.length === 0
            text: field.placeholderText
            color: Theme.textMuted
            font: input.font
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            Accessible.ignored: true
        }

        Row {
            id: trailingRow
            anchors.right: parent.right
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
        }
    }

    Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        visible: text.length > 0
        text: field.errorText || field.helpText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        color: field.errorText.length > 0 ? Theme.danger : Theme.textMuted
        wrapMode: Text.WordWrap
        Accessible.role: Accessible.StaticText
        Accessible.name: text
    }
}
