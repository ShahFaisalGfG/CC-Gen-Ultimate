// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A notice that the chosen (or automatically chosen) model's licence must be accepted once,
// with a button that opens the licence. Hidden while `model` is "".
Rectangle {
    id: banner

    // The model whose licence is pending: "omnivoice", "xtts", "nllb", or "" for none.
    property string model: ""
    readonly property var terms: banner.model ? prefsController.modelTerms(banner.model) : ({})

    Layout.fillWidth: true
    Layout.preferredHeight: row.implicitHeight + 2 * Theme.spaceMd
    visible: banner.model !== ""
    radius: Theme.radius
    color: Theme.accentSoft

    ModelTermsDialog {
        id: termsDialog
        parent: Overlay.overlay
        model: banner.model || "omnivoice"
    }

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: Theme.spaceMd
        spacing: Theme.spaceMd
        Text {
            Layout.fillWidth: true
            text: (banner.terms.title || "This model's licence") + " allows non-commercial use only. Review and accept it once to continue."
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.text
        }
        AppButton {
            text: "Review licence"
            toolTipText: "Read the licence terms and accept them"
            onClicked: termsDialog.open()
        }
    }
}
