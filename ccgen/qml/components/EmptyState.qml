import QtQuick
import QtQuick.Layouts

// The message a list shows while it is empty: an icon, a title, and what to do first.
ColumnLayout {
    id: empty

    property string iconName: "download"
    property string title: ""
    property string text: ""

    spacing: Theme.spaceSm

    Icon {
        Layout.alignment: Qt.AlignHCenter
        name: empty.iconName
        size: Theme.iconXl
        color: Theme.textMuted
    }
    Text {
        textFormat: Text.PlainText
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: 460
        text: empty.title
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSubtitle
        font.weight: Font.DemiBold
        color: Theme.text
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }
    Text {
        textFormat: Text.PlainText
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: 460
        visible: empty.text.length > 0
        text: empty.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: Theme.textMuted
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        lineHeight: 1.2
        Accessible.role: Accessible.StaticText
        Accessible.name: text
    }
}
