// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One-time licence notice for a model whose licence allows non-commercial use only (OmniVoice
// and XTTS-v2 voice cloning, NLLB-200 translation). The text comes from ccgen/config/licences.py.
// It opens with keyboard focus on the terms, which scroll with the arrow keys, Page Up and Page
// Down, Home, and End, so "I agree" is never pressed before they are read. Accepting is saved in
// preferences; `accepted()` lets the caller continue what it started.
AppDialog {
    id: dialog

    // Which model's licence to show: "omnivoice", "xtts", or "nllb".
    property string model: "omnivoice"
    readonly property var terms: prefsController.modelTerms(dialog.model)
    // The terms box grows with its text up to this height, then scrolls.
    readonly property real _termsMaxHeight: Math.max(96, (dialog.parent ? dialog.parent.height : 560) - 260)

    signal accepted()

    title: dialog.terms.title
    width: Math.min(520, parent ? parent.width - 48 : 520)
    standardButtons: Dialog.Cancel

    onOpened: {
        termsView.contentY = 0
        termsView.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spaceMd

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(termsColumn.implicitHeight, dialog._termsMaxHeight) + 2 * Theme.spaceSm
            radius: Theme.radius
            color: Theme.surfaceAlt
            border.width: termsView.activeFocus ? 2 : 1
            border.color: termsView.activeFocus ? Theme.focusRing : Theme.border

            Flickable {
                id: termsView
                anchors.fill: parent
                anchors.margins: Theme.spaceSm
                contentWidth: width
                contentHeight: termsColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                activeFocusOnTab: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Accessible.role: Accessible.StaticText
                Accessible.name: dialog.terms.title
                Accessible.description: dialog.terms.body + " " + dialog.terms.note

                Keys.onPressed: event => {
                    var line = 40
                    var page = Math.max(line, termsView.height - line)
                    var last = Math.max(0, termsView.contentHeight - termsView.height)
                    var y = termsView.contentY
                    switch (event.key) {
                    case Qt.Key_Down: y += line; break
                    case Qt.Key_Up: y -= line; break
                    case Qt.Key_PageDown: y += page; break
                    case Qt.Key_PageUp: y -= page; break
                    case Qt.Key_Home: y = 0; break
                    case Qt.Key_End: y = last; break
                    default: return
                    }
                    termsView.contentY = Math.max(0, Math.min(last, y))
                    event.accepted = true
                }

                ColumnLayout {
                    id: termsColumn
                    // Room on the right for the scroll bar, which draws over the text's edge.
                    width: termsView.width - Theme.spaceMd
                    spacing: Theme.spaceSm

                    Text {
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: dialog.terms.body
                        wrapMode: Text.WordWrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontBody
                        color: Theme.text
                        Accessible.ignored: true
                    }
                    Text {
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: dialog.terms.note
                        wrapMode: Text.WordWrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.textMuted
                        Accessible.ignored: true
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            AppButton {
                kind: "ghost"
                text: "Read the licence"
                iconName: "openExternal"
                toolTipText: "Open " + dialog.terms.site + " in your browser"
                onClicked: Qt.openUrlExternally(dialog.terms.url)
            }
            Item { Layout.fillWidth: true }
            AppButton {
                kind: "primary"
                text: "I agree"
                toolTipText: "Accept the licence and continue"
                onClicked: {
                    var values = {}
                    values[dialog.terms.setting] = true
                    prefsController.saveSettings(values)
                    dialog.close()
                    dialog.accepted()
                }
            }
        }
    }
}
