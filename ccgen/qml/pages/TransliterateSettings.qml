// qmllint disable unqualified
import QtQuick
import QtQuick.Layouts
import "../components"

// Transliteration options for the Transliterate tab and transliterate workflow steps.
ColumnLayout {
    id: root

    property var options: ({})
    signal optionChanged(string key, var value)

    readonly property string neuralAsset: modelsController.neuralAssetId(root.options.source_scheme || "", root.options.target_scheme || "")
    // What Automatic runs on this PC's profile ("" for an engine chosen by hand).
    readonly property string automatic: prefsController.automaticChoice("transliterate", root.options, prefsController.settings)
    readonly property string resolvedEngine: prefsController.resolvedTranslitEngine(root.options, prefsController.settings)

    spacing: Theme.spaceLg

    Card {
        Layout.fillWidth: true
        title: "Transliteration"
        description: "Rewrites the text in another script, e.g. Urdu as natural Roman Urdu."
        iconName: "characters"

        FormRow {
            label: "Scripts"
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Transliterate from script"
                toolTipText: "Script the text is written in."
                model: prefsController.translitSchemeOptions
                value: root.options.source_scheme
                onActivated: root.optionChanged("source_scheme", currentValue)
            }
            Icon { name: "chevronDown"; rotation: -90; size: 10; color: Theme.textMuted }
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Transliterate to script"
                toolTipText: "Script to rewrite the text in."
                model: prefsController.translitSchemeOptions
                value: root.options.target_scheme
                onActivated: root.optionChanged("target_scheme", currentValue)
            }
        }

        FormRow {
            label: "Engine"
            hint: root.automatic ? "On this PC: " + root.automatic + ", from the performance profile."
                : root.options.engine === "neural" && root.neuralAsset.length === 0
                ? "Neural supports Urdu and Roman Urdu both ways, and Hindi or Punjabi to Urdu."
                : "Neural is more natural but downloads a model on first use."
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Transliteration engine"
                toolTipText: "Rule-based is instant and needs no download. Neural sounds more natural but downloads a model."
                model: prefsController.translitEngineOptions
                value: root.options.engine
                readiness: {
                    var result = {}
                    var ready = modelsController.readiness[root.neuralAsset]
                    if (root.neuralAsset && ready !== undefined) result["neural"] = ready
                    if (root.automatic && root.resolvedEngine === "neural" && ready !== undefined) result["auto"] = ready
                    return result
                }
                onActivated: root.optionChanged("engine", currentValue)
            }
        }
    }
}
