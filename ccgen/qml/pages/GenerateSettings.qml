// qmllint disable unqualified
import QtQuick
import QtQuick.Layouts
import "../components"

// Transcription options for the Generate tab and generate workflow steps.
ColumnLayout {
    id: root

    property var options: ({})
    signal optionChanged(string key, var value)

    // What Automatic runs on this PC's profile ("" for a model chosen by hand).
    readonly property string automatic: prefsController.automaticChoice("generate", root.options, prefsController.settings)

    spacing: Theme.spaceLg

    function whisperReadiness(readiness) {
        var result = {}
        var models = prefsController.modelOptions
        for (var i = 0; i < models.length; i++) {
            var ready = readiness[modelsController.whisperAssetId(models[i].code, prefsController.profile)]
            if (ready !== undefined) result[models[i].code] = ready
        }
        return result
    }

    Card {
        Layout.fillWidth: true
        title: "Speech recognition"
        description: "Runs offline with Whisper."
        iconName: "mic"

        FormRow {
            label: "Model"
            hint: root.automatic ? "On this PC: " + root.automatic + ", from the performance profile." : "Larger models are more accurate but slower."
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Transcription model"
                toolTipText: "Whisper model used to recognize speech. Bigger models are more accurate but slower; models download once on first use."
                model: prefsController.modelOptions
                value: root.options.model_name
                readiness: root.whisperReadiness(modelsController.readiness)
                onActivated: root.optionChanged("model_name", currentValue)
            }
        }

        FormRow {
            label: "Spoken language"
            hint: "Auto-detect works for most files; pick the language if detection guesses wrong."
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Spoken language"
                toolTipText: "Language spoken in the files. Auto-detect listens to the opening minutes; choose a language to skip detection."
                model: prefsController.languageOptions
                value: root.options.language || ""
                onActivated: root.optionChanged("language", currentValue)
            }
        }
    }
}
