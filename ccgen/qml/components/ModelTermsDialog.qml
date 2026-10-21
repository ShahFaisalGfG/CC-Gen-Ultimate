// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One-time licence notice for a model whose licence allows non-commercial use only (OmniVoice
// and XTTS-v2 voice cloning, NLLB-200 translation). The text comes from ccgen/config/licences.py.
// Accepting is saved in preferences; `accepted()` lets the caller continue what it started.
AppDialog {
    id: dialog

    // Which model's licence to show: "omnivoice", "xtts", or "nllb".
    property string model: "omnivoice"
    readonly property var terms: prefsController.modelTerms(dialog.model)

    signal accepted()

    title: dialog.terms.title
    width: Math.min(520, parent ? parent.width - 48 : 520)
    standardButtons: Dialog.Cancel

    onOpened: acceptButton.forceActiveFocus()

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spaceMd

        Text {
            Layout.fillWidth: true
            text: dialog.terms.body
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
        }
        Text {
            Layout.fillWidth: true
            text: dialog.terms.note
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
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
                id: acceptButton
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
