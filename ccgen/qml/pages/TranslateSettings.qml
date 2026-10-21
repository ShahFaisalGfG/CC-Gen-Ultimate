// qmllint disable unqualified
import QtQuick
import QtQuick.Layouts
import "../components"

// Translation options for the Translate tab and translate workflow steps.
ColumnLayout {
    id: root

    property var options: ({})
    // The Translate tab: subtitles carry their own language in the queue, and media is
    // transcribed first in the spoken language. A workflow step picks its source here instead.
    property bool forTab: false
    // In a workflow, "Detect" means the language the input step produced.
    property string detectHint: "Detect reads the language from names like movie_en.srt, or from the tab the file came from."
    signal optionChanged(string key, var value)

    readonly property string engine: root.options.engine || "auto"
    readonly property string source: root.forTab ? (root.options.spoken_language || "auto") : root.options.source_lang
    readonly property var engineInfo: prefsController.translationEngineOptions.find(e => e.code === root.engine) || ({ hint: "" })
    // What Automatic runs on this PC's profile ("" for a model chosen by hand).
    readonly property string automatic: prefsController.automaticChoice("translate", root.options, prefsController.settings)

    spacing: Theme.spaceLg

    // A target is ready when every model the chosen engine needs for it is downloaded.
    function translationReadiness(readiness, source, engine) {
        var result = {}
        var targets = prefsController.targetOptions
        for (var i = 0; i < targets.length; i++) {
            var ids = modelsController.translationAssetIds(source, targets[i].code, engine, prefsController.profile)
            if (ids.length === 0) continue
            result[targets[i].code] = ids.every(id => readiness[id] === true)
        }
        return result
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
            text: root.engineInfo.hint + (root.automatic ? " On this PC: " + root.automatic + "." : "")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }

        LicenceBanner {
            model: prefsController.pendingLicence("translate", root.options, prefsController.settings)
        }

        SpokenLanguageRow {
            visible: root.forTab
            value: root.options.spoken_language || ""
            onChanged: value => root.optionChanged("spoken_language", value)
        }

        FormRow {
            label: "Translate from"
            visible: !root.forTab
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
            hint: root.source !== "auto" && root.source === root.options.target_lang
                ? "Choose a language different from the source." : ""
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Translate to"
                toolTipText: "Language the text is translated into, e.g. movie_ur.srt."
                model: prefsController.targetOptions
                value: root.options.target_lang
                readiness: root.translationReadiness(modelsController.readiness, root.source, root.engine)
                onActivated: root.optionChanged("target_lang", currentValue)
            }
        }
    }
}
