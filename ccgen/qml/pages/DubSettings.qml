// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

// Dubbing options for the Dub tab and dub workflow steps.
ColumnLayout {
    id: root

    property var options: ({})
    signal optionChanged(string key, var value)

    readonly property string mode: root.options.mode || "auto"
    // The engine the mode runs with on this PC's profile (Automatic resolves to one).
    readonly property string resolvedMode: prefsController.resolvedDubMode(root.mode, prefsController.settings)
    readonly property bool cloning: root.resolvedMode === "omnivoice" || root.resolvedMode === "xtts"
    readonly property var modeInfo: prefsController.dubModeOptions.find(m => m.code === root.mode) || ({ hint: "" })
    readonly property string automatic: prefsController.automaticChoice("dub", root.options, prefsController.settings)
    readonly property var voiceList: dubController.voiceOptions(root.mode, root.options.language || "auto")

    spacing: Theme.spaceLg

    function voiceReadiness(readiness) {
        var result = {}
        for (var i = 0; i < root.voiceList.length; i++) {
            var id = modelsController.voiceAssetId(root.mode, root.voiceList[i].code, prefsController.profile)
            if (id && readiness[id] !== undefined) result[root.voiceList[i].code] = readiness[id]
        }
        return result
    }

    function modeReadiness(readiness) {
        var result = {}
        var modes = ["auto", "omnivoice", "xtts", "kokoro"]
        for (var i = 0; i < modes.length; i++) {
            var ready = readiness[modelsController.voiceAssetId(modes[i], "", prefsController.profile)]
            if (ready !== undefined) result[modes[i]] = ready
        }
        return result
    }

    Card {
        Layout.fillWidth: true
        title: "Voices"
        description: "Speaks the subtitles and adds the speech to the video as a new audio track."
        iconName: "speaker"

        FormRow {
            label: "Voices"
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Dubbing voices"
                toolTipText: "Clone each original speaker, or use natural or light stock voices."
                model: prefsController.dubModeOptions
                value: root.mode
                readiness: root.modeReadiness(modelsController.readiness)
                onActivated: root.optionChanged("mode", currentValue)
            }
        }

        // The chosen mode's trade-offs, on a full-width line so the long text never squeezes
        // the label column.
        Text {
            Layout.fillWidth: true
            text: root.modeInfo.hint + (root.automatic ? " On this PC: " + root.automatic + "." : "")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }

        LicenceBanner {
            model: prefsController.pendingLicence("dub", root.options, prefsController.settings)
        }

        FormRow {
            label: "Speech language"
            hint: root.options.language === "auto"
                ? "Uses the subtitle's language, read from names like movie_es.srt." : ""
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Speech language"
                toolTipText: "Language the subtitles are written in and spoken in."
                model: prefsController.dubLanguageOptions
                value: root.options.language
                onActivated: root.optionChanged("language", currentValue)
            }
        }

        FormRow {
            label: "Voice"
            visible: !root.cloning
            hint: root.options.language === "auto" ? "Choose the speech language to pick a specific voice." : ""
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Voice"
                toolTipText: "Which stock voice speaks the lines."
                model: root.voiceList
                value: root.options.voice
                readiness: root.voiceReadiness(modelsController.readiness)
                onActivated: root.optionChanged("voice", currentValue)
            }
        }

        FormRow {
            label: "Speakers"
            visible: root.cloning
            hint: "Detecting speakers gives each person in the video their own cloned voice."
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Speakers"
                toolTipText: "Clone each detected speaker, or use one voice for everyone."
                model: prefsController.speakerOptions
                value: root.options.speakers
                onActivated: root.optionChanged("speakers", currentValue)
            }
        }

        FormRow {
            label: "Fastest speech"
            hint: "Lines that don't fit their time are spoken faster up to this speed, then may run up to a second over; only longer ones are cut short."
            SpinBox {
                from: Math.round(prefsController.speedupRange[0] * 100)
                to: Math.round(prefsController.speedupRange[1] * 100)
                stepSize: 5
                editable: true
                value: Math.round((root.options.max_speedup || 1) * 100)
                textFromValue: (value, locale) => (value / 100).toFixed(2) + "x"
                valueFromText: (text, locale) => Math.round(parseFloat(text) * 100)
                onValueModified: root.optionChanged("max_speedup", value / 100)
                Accessible.name: "Fastest speech"
                ToolTip.visible: hovered
                ToolTip.text: "1.00x never speeds speech up; 1.35x is barely noticeable."
                ToolTip.delay: 600
            }
            Item { Layout.fillWidth: true }
        }
    }

    Card {
        Layout.fillWidth: true
        title: "Result"
        iconName: "video"

        FormRow {
            label: "Save the dub as"
            hint: "A subtitle file on its own always becomes a WAV file."
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Save the dub as"
                toolTipText: "A new audio track in a copy of the video (movie_dub_es.mkv), or a separate WAV file."
                model: prefsController.dubOutputOptions
                value: root.options.output
                onActivated: root.optionChanged("output", currentValue)
            }
        }

        FormRow {
            label: "Play the dub by default"
            hint: "Players start with the dubbed track; the original stays selectable."
            visible: root.options.output === "track"
            AppSwitch {
                checked: !!root.options.default_track
                onToggled: root.optionChanged("default_track", checked)
                accessibleName: "Play the dub by default"
                toolTipText: "Mark the dubbed track as the default audio track."
            }
            Item { Layout.fillWidth: true }
        }

        FormRow {
            label: "Run on"
            hint: "Automatic times Kokoro and Piper on each GPU and the CPU and keeps the fastest. OmniVoice uses a strong GPU straight away and times a smaller one against the CPU; XTTS-v2 uses the first GPU that works."
            StyledComboBox {
                Layout.fillWidth: true
                accessibleName: "Dubbing device"
                toolTipText: "Where speech is generated."
                model: prefsController.dubDeviceOptions
                value: root.options.device
                onActivated: root.optionChanged("device", currentValue)
            }
        }
    }
}
