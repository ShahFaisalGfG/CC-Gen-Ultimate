// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

// Translation options for the Translate tab and translate workflow steps.
ColumnLayout {
    id: root

    property var options: ({})
    // In a workflow, "Detect" means the language the input step produced.
    property string detectHint: "Detect reads the language from names like movie_en.srt, or from the tab the file came from."
    signal optionChanged(string key, var value)

    readonly property string engine: root.options.engine || "opus_mt"
    readonly property var engineInfo: prefsController.translationEngineOptions.find(e => e.code === root.engine) || ({ hint: "" })
    readonly property bool nllbAccepted: !!(prefsController.settings.translation && prefsController.settings.translation.nllb_terms_accepted)

    spacing: Theme.spaceLg

    // A target is ready when every model the chosen engine needs for it is downloaded.
    function translationReadiness(readiness, source, engine) {
        var result = {}
        var targets = prefsController.targetOptions
        for (var i = 0; i < targets.length; i++) {
            var ids = modelsController.translationAssetIds(source, targets[i].code, engine)
            if (ids.length === 0) continue
            result[targets[i].code] = ids.every(id => readiness[id] === true)
        }
        return result
    }

    ModelTermsDialog {
        id: termsDialog
        parent: Overlay.overlay
        model: "nllb"
    }

    Card {
        Layout.fillWidth: true
        title: "Translation"
        description: "Translates whole sentences offline, through English when a model has no direct pair."
        iconName: "globe"

        FormRow {
            label: "Translation model"
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Translation model"
                toolTipText: "Which offline model translates the subtitles."
                model: prefsController.translationEngineOptions
                value: root.engine
                onActivated: root.optionChanged("engine", currentValue)
            }
        }

        // The chosen model's trade-offs, on a full-width line so the long text never squeezes
        // the label column.
        Text {
            Layout.fillWidth: true
            text: root.engineInfo.hint
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: termsRow.implicitHeight + 2 * Theme.spaceMd
            visible: root.engine === "nllb" && !root.nllbAccepted
            radius: Theme.radius
            color: Theme.accentSoft

            RowLayout {
                id: termsRow
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceMd
                Text {
                    Layout.fillWidth: true
                    text: "NLLB-200's licence allows non-commercial use only. Review and accept it once to continue."
                    wrapMode: Text.WordWrap
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.text
                }
                AppButton {
                    text: "Review licence"
                    toolTipText: "Read the NLLB-200 licence terms and accept them"
                    onClicked: termsDialog.open()
                }
            }
        }

        FormRow {
            label: "Translate from"
            hint: root.options.source_lang === "auto" ? root.detectHint : ""
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Translate from"
                toolTipText: "Language the subtitles are written in."
                model: prefsController.sourceOptions
                value: root.options.source_lang
                onActivated: root.optionChanged("source_lang", currentValue)
            }
        }

        FormRow {
            label: "Translate to"
            hint: root.options.source_lang !== "auto" && root.options.source_lang === root.options.target_lang
                ? "Choose a language different from the source." : ""
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Translate to"
                toolTipText: "Language the subtitles are translated into, e.g. movie_ur.srt."
                model: prefsController.targetOptions
                value: root.options.target_lang
                readiness: root.translationReadiness(modelsController.readiness, root.options.source_lang, root.engine)
                onActivated: root.optionChanged("target_lang", currentValue)
            }
        }

        FormRow {
            label: "Meaning check"
            hint: "Picks the translation that keeps the original's meaning best and notes lines that may drift. Adds a 120 MB model."
            AppSwitch {
                checked: root.options.meaning_check !== false
                onToggled: root.optionChanged("meaning_check", checked)
                accessibleName: "Meaning check"
                toolTipText: "Compare each translation with the original sentence."
            }
            Item { Layout.fillWidth: true }
        }
    }
}
