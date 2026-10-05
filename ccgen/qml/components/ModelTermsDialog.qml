// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One-time licence notice for a model whose licence allows non-commercial use only: XTTS-v2
// voice cloning (Coqui Public Model License) or the NLLB-200 translation model (CC-BY-NC-4.0).
// Accepting is saved in preferences; `accepted()` lets the caller continue what it started.
Dialog {
    id: dialog

    // Which model's licence to show: "xtts" or "nllb".
    property string model: "xtts"
    readonly property var terms: dialog.model === "nllb" ? ({
        title: "NLLB-200 licence",
        body: "The NLLB-200 translation model by Meta is released under the Creative Commons "
            + "Attribution-NonCommercial 4.0 licence. It allows personal, research, and other "
            + "non-commercial use of the model. Commercial use isn't allowed.",
        note: "OPUS-MT, MADLAD-400, and Argos Translate have no such limits.",
        url: "https://creativecommons.org/licenses/by-nc/4.0/",
        site: "creativecommons.org",
        setting: "translation.nllb_terms_accepted"
    }) : ({
        title: "XTTS-v2 licence",
        body: "Voice cloning uses the XTTS-v2 model by Coqui, released under the Coqui Public Model "
            + "License. It allows personal, research, and other non-commercial use of the model and "
            + "of the audio it creates. Commercial use needs a separate licence.",
        note: "Only clone voices you have permission to use. Kokoro and Piper voices have no such limits.",
        url: "https://coqui.ai/cpml",
        site: "coqui.ai/cpml",
        setting: "dubbing.xtts_terms_accepted"
    })

    signal accepted()

    title: dialog.terms.title
    modal: true
    anchors.centerIn: parent
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
