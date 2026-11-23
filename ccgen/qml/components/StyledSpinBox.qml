import QtQuick
import QtQuick.Controls

// A number box at the kit's control height, bordered like StyledComboBox, with minus and plus
// buttons at its ends. The Material SpinBox is taller than the other controls and has no border.
// Set Accessible.name; `toolTipText` shows on hover or keyboard focus and becomes the description.
SpinBox {
    id: spin

    property string toolTipText: ""

    implicitHeight: Theme.controlHeight
    implicitWidth: 132
    editable: true
    leftPadding: Theme.controlHeight
    rightPadding: Theme.controlHeight
    topPadding: 0
    bottomPadding: 0
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody

    Accessible.description: spin.toolTipText

    ToolTip.visible: spin.toolTipText.length > 0 && (spin.hovered || spin.visualFocus)
    ToolTip.text: spin.toolTipText
    ToolTip.delay: 600
    ToolTip.timeout: spin.hovered ? -1 : Theme.focusTipTimeout

    contentItem: TextInput {
        text: spin.displayText
        font: spin.font
        color: spin.enabled ? Theme.text : Theme.textMuted
        selectionColor: Theme.accentFill
        selectedTextColor: Theme.textOnAccent
        horizontalAlignment: Qt.AlignHCenter
        verticalAlignment: Qt.AlignVCenter
        readOnly: !spin.editable
        validator: spin.validator
        inputMethodHints: Qt.ImhDigitsOnly
        selectByMouse: true
        clip: true
    }

    down.indicator: Rectangle {
        x: spin.mirrored ? spin.width - width : 0
        width: Theme.controlHeight
        height: spin.height
        radius: Theme.radius
        color: spin.down.pressed ? Theme.border : spin.down.hovered ? Theme.surfaceHover : "transparent"
        opacity: spin.value > spin.from ? 1 : 0.4

        Icon {
            anchors.centerIn: parent
            name: "remove"
            size: Theme.iconSm
        }
    }

    up.indicator: Rectangle {
        x: spin.mirrored ? 0 : spin.width - width
        width: Theme.controlHeight
        height: spin.height
        radius: Theme.radius
        color: spin.up.pressed ? Theme.border : spin.up.hovered ? Theme.surfaceHover : "transparent"
        opacity: spin.value < spin.to ? 1 : 0.4

        Icon {
            anchors.centerIn: parent
            name: "add"
            size: Theme.iconSm
        }
    }

    background: Rectangle {
        radius: Theme.radius
        color: spin.enabled ? Theme.surface : Theme.surfaceAlt
        border.width: spin.activeFocus ? 2 : 1
        border.color: spin.activeFocus ? Theme.focusRing : spin.enabled ? Theme.inputBorder : Theme.border
    }
}
