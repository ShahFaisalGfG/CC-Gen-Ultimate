// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "components"

AppWindow {
    id: prefsWin

    width: 820
    height: 600
    minimumWidth: 640
    minimumHeight: 480
    title: "Preferences"
    showMaximize: false
    modality: Qt.ApplicationModal

    property bool dirty: false
    property bool _loading: false
    property var _values: ({})

    readonly property var sections: [
        { name: "Appearance", icon: "settings" },
        { name: "Transcription", icon: "mic" },
        { name: "Translation", icon: "globe" },
        { name: "Transliteration", icon: "characters" },
        { name: "Dubbing", icon: "speaker" },
        { name: "Subtitles", icon: "captions" },
        { name: "Advanced", icon: "info" }
    ]

    Component.onCompleted: prefsWin.loadValues()
    onClosing: prefsWin.destroy()

    Connections {
        target: prefsController
        function onSettingsChanged() { prefsWin.loadValues() }
        function onSaveFinished(success, error) {
            if (success) {
                prefsWin.dirty = false
                prefsWin.close()
            } else {
                saveError.text = "Couldn't save: " + error
            }
        }
    }

    Shortcut { sequences: [StandardKey.Save]; onActivated: prefsWin.save() }
    Shortcut { sequence: "Escape"; onActivated: prefsWin.close() }

    // ── Value plumbing ─────────────────────────────────────────────────────

    // Read a dotted key from the saved settings.
    function saved(key, fallback) {
        var node = prefsController.settings
        var parts = key.split(".")
        for (var i = 0; i < parts.length; i++) {
            if (node === undefined || node === null) return fallback
            node = node[parts[i]]
        }
        return node === undefined || node === null ? fallback : node
    }

    // Record an edited value; controls call this from their change handlers.
    function set(key, value) {
        if (prefsWin._loading) return
        prefsWin._values[key] = value
        prefsWin.dirty = true
    }

    function value(key, fallback) {
        return key in prefsWin._values ? prefsWin._values[key] : prefsWin.saved(key, fallback)
    }

    function loadValues() {
        prefsWin._loading = true
        prefsWin._values = {}
        themeCombo.selectCode(saved("ui.theme", "system"))
        modelCombo.selectCode(saved("model.name", "base"))
        languageCombo.selectCode(saved("transcription.language", "") || "")
        deviceCombo.selectCode(saved("model.device", "auto"))
        vadSwitch.checked = saved("transcription.vad_filter", true)
        translationEngineCombo.selectCode(saved("translation.engine", "opus_mt"))
        meaningCheckSwitch.checked = saved("translation.meaning_check", true)
        sourceCombo.selectCode(saved("translation.source_lang", "auto"))
        targetCombo.selectCode(saved("translation.target_lang", "en"))
        translitSourceCombo.selectCode(saved("transliteration.source", "roman"))
        translitTargetCombo.selectCode(saved("transliteration.target", "ur"))
        translitEngineCombo.selectCode(saved("transliteration.engine", "rule"))
        dubModeCombo.selectCode(saved("dubbing.mode", "xtts"))
        speakersCombo.selectCode(saved("dubbing.speakers", "auto"))
        speedupSpin.value = Math.round(saved("dubbing.max_speedup", 1.35) * 100)
        dubOutputCombo.selectCode(saved("dubbing.output", "track"))
        defaultTrackSwitch.checked = saved("dubbing.default_track", false)
        scriptBridgeSwitch.checked = saved("dubbing.script_bridge", true)
        dubDeviceCombo.selectCode(saved("dubbing.device", "auto"))
        lineLengthSpin.value = saved("output.max_line_length", 42)
        maxLinesSpin.value = saved("output.max_lines", 2)
        outputDirText.text = saved("output.directory", "") || ""
        logsSwitch.checked = saved("logging.enable_logs", true)
        logLevelCombo.selectCode(saved("logging.log_level", "critical"))
        formatRepeater.model = prefsWin.formatModel()
        prefsWin._loading = false
        prefsWin.dirty = false
        saveError.text = ""
    }

    function formatModel() {
        return [
            { code: "srt", label: "SRT", on: saved("output.srt", true) },
            { code: "vtt", label: "VTT", on: saved("output.vtt", false) },
            { code: "ass", label: "ASS", on: saved("output.ass", false) },
            { code: "sbv", label: "SBV", on: saved("output.sbv", false) },
            { code: "lrc", label: "LRC", on: saved("output.lrc", false) }
        ]
    }

    function save() {
        var anyFormat = ["srt", "vtt", "ass", "sbv", "lrc"].some(f => prefsWin.value("output." + f, false))
        if (!anyFormat) {
            saveError.text = "Select at least one default subtitle format."
            nav.currentIndex = prefsWin.sections.findIndex(section => section.name === "Subtitles")
            return
        }
        if (!prefsWin.dirty) { prefsWin.close(); return }
        if ("ui.theme" in prefsWin._values) appController.applyTheme(prefsWin._values["ui.theme"])
        prefsController.saveSettings(prefsWin._values)
    }

    FolderDialog {
        id: outputFolderPicker
        title: "Default folder for subtitle files"
        onAccepted: {
            var path = appController.localPath(selectedFolder.toString())
            outputDirText.text = path
            prefsWin.set("output.directory", path)
        }
    }

    Dialog {
        id: resetDialog
        title: "Reset all preferences?"
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Reset | Dialog.Cancel
        Text {
            width: 340
            text: "Every preference returns to its default. Downloaded models are not affected."
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
        }
        onReset: {
            prefsController.resetDefaults()
            appController.applyTheme("system")
            resetDialog.close()
        }
    }

    // ── Layout ─────────────────────────────────────────────────────────────

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Section navigation (Up/Down to move, Tab to the content)
            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 200
                color: Theme.surfaceAlt

                ListView {
                    id: nav
                    objectName: "prefsNav"
                    anchors.fill: parent
                    anchors.margins: Theme.spaceSm
                    model: prefsWin.sections
                    spacing: 2
                    focus: true
                    activeFocusOnTab: true
                    keyNavigationEnabled: true
                    Accessible.role: Accessible.List
                    Accessible.name: "Preference sections"

                    delegate: ItemDelegate {
                        id: navItem
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        height: 38
                        highlighted: ListView.isCurrentItem
                        onClicked: nav.currentIndex = navItem.index
                        Accessible.name: navItem.modelData.name

                        contentItem: RowLayout {
                            spacing: Theme.spaceSm
                            Icon {
                                name: navItem.modelData.icon
                                size: 14
                                color: navItem.highlighted ? Theme.accent : Theme.textMuted
                            }
                            Text {
                                Layout.fillWidth: true
                                text: navItem.modelData.name
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontBody
                                font.weight: navItem.highlighted ? Font.DemiBold : Font.Normal
                                color: Theme.text
                            }
                        }
                        background: Rectangle {
                            radius: Theme.radius
                            color: navItem.highlighted ? Theme.accentSoft : (navItem.hovered ? Theme.surfaceHover : "transparent")
                            border.width: nav.activeFocus && navItem.highlighted ? 2 : 0
                            border.color: Theme.focusRing
                        }
                    }
                }
            }

            Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: Theme.border }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: nav.currentIndex

                // Appearance
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Theme"
                        description: "System follows your Windows light or dark mode setting."
                        FormRow {
                            label: "App theme"
                            StyledComboBox {
                                id: themeCombo
                                Layout.fillWidth: true
                                accessibleName: "App theme"
                                toolTipText: "Light, dark, or follow the Windows setting."
                                model: prefsController.themeOptions
                                onActivated: prefsWin.set("ui.theme", currentValue)
                            }
                        }
                    }
                }

                // Transcription
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Default transcription settings"
                        description: "Used by the Generate tab and new workflow steps; you can still change them there."
                        FormRow {
                            label: "Model"
                            StyledComboBox {
                                id: modelCombo
                                Layout.fillWidth: true
                                accessibleName: "Default model"
                                toolTipText: "Model selected on the main window when the app starts."
                                model: prefsController.modelOptions
                                onActivated: prefsWin.set("model.name", currentValue)
                            }
                        }
                        FormRow {
                            label: "Spoken language"
                            StyledComboBox {
                                id: languageCombo
                                Layout.fillWidth: true
                                accessibleName: "Default spoken language"
                                toolTipText: "Spoken language selected on the main window when the app starts."
                                model: prefsController.languageOptions
                                onActivated: prefsWin.set("transcription.language", currentValue || null)
                            }
                        }
                    }
                    Card {
                        Layout.fillWidth: true
                        title: "Performance"
                        FormRow {
                            label: "Run on"
                            hint: "Automatic uses an NVIDIA GPU when its CUDA libraries are installed, otherwise the CPU."
                            StyledComboBox {
                                id: deviceCombo
                                Layout.fillWidth: true
                                accessibleName: "Compute device"
                                toolTipText: "Where speech recognition runs. Automatic tries an NVIDIA GPU and falls back to the CPU."
                                model: prefsController.deviceOptions
                                onActivated: prefsWin.set("model.device", currentValue)
                            }
                        }
                        FormRow {
                            label: "Skip silence and music"
                            hint: "Faster, and avoids made-up text in long silent parts. Turn off if quiet speech is missed."
                            AppSwitch {
                                id: vadSwitch
                                onToggled: prefsWin.set("transcription.vad_filter", checked)
                                accessibleName: "Skip silence and music"
                                toolTipText: "Voice activity detection: skips non-speech audio. Faster and prevents made-up text in silent parts."
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                // Translation
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Default translation"
                        description: "Used by the Translate tab and new workflow steps. Models download the first time a pair is used."
                        FormRow {
                            label: "Translation model"
                            hint: (prefsController.translationEngineOptions[translationEngineCombo.currentIndex] || { hint: "" }).hint
                            StyledComboBox {
                                id: translationEngineCombo
                                Layout.fillWidth: true
                                accessibleName: "Default translation model"
                                toolTipText: "Which offline model translates subtitles."
                                model: prefsController.translationEngineOptions
                                onActivated: prefsWin.set("translation.engine", currentValue)
                            }
                        }
                        FormRow {
                            label: "Translate from"
                            hint: "Detect reads the language from names like movie_en.srt, or from the tab a file came from."
                            StyledComboBox {
                                id: sourceCombo
                                Layout.fillWidth: true
                                accessibleName: "Default source language"
                                toolTipText: "Language the subtitles are written in."
                                model: prefsController.sourceOptions
                                onActivated: prefsWin.set("translation.source_lang", currentValue)
                            }
                        }
                        FormRow {
                            label: "Translate to"
                            StyledComboBox {
                                id: targetCombo
                                Layout.fillWidth: true
                                accessibleName: "Default translation language"
                                toolTipText: "Language subtitles are translated into."
                                model: prefsController.targetOptions
                                onActivated: prefsWin.set("translation.target_lang", currentValue)
                            }
                        }
                        FormRow {
                            label: "Meaning check"
                            hint: "Picks the translation that keeps the original's meaning best and notes lines that may drift. Adds a 120 MB model."
                            AppSwitch {
                                id: meaningCheckSwitch
                                onToggled: prefsWin.set("translation.meaning_check", checked)
                                accessibleName: "Meaning check"
                                toolTipText: "Compare each translation with the original sentence."
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                // Transliteration
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Default transliteration"
                        description: "Used by the Transliterate tab and new workflow steps."
                        FormRow {
                            label: "From"
                            StyledComboBox {
                                id: translitSourceCombo
                                Layout.fillWidth: true
                                accessibleName: "Default source script"
                                toolTipText: "Script the subtitles are written in."
                                model: prefsController.translitSchemeOptions
                                onActivated: prefsWin.set("transliteration.source", currentValue)
                            }
                        }
                        FormRow {
                            label: "To"
                            StyledComboBox {
                                id: translitTargetCombo
                                Layout.fillWidth: true
                                accessibleName: "Default target script"
                                toolTipText: "Script to rewrite the subtitles in."
                                model: prefsController.translitSchemeOptions
                                onActivated: prefsWin.set("transliteration.target", currentValue)
                            }
                        }
                        FormRow {
                            label: "Engine"
                            hint: "Neural gives more natural results but downloads a larger model on first use."
                            StyledComboBox {
                                id: translitEngineCombo
                                Layout.fillWidth: true
                                accessibleName: "Default transliteration engine"
                                toolTipText: "Rule-based is instant; neural is more natural but downloads a model."
                                model: prefsController.translitEngineOptions
                                onActivated: prefsWin.set("transliteration.engine", currentValue)
                            }
                        }
                    }
                }

                // Dubbing
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Default dubbing"
                        description: "Used by the Dub tab and new workflow steps."
                        FormRow {
                            label: "Voices"
                            hint: dubModeCombo.currentIndex >= 0 ? prefsController.dubModeOptions[dubModeCombo.currentIndex].hint : ""
                            StyledComboBox {
                                id: dubModeCombo
                                Layout.fillWidth: true
                                accessibleName: "Default dubbing voices"
                                toolTipText: "Clone each original speaker, or use natural or light stock voices."
                                model: prefsController.dubModeOptions
                                onActivated: prefsWin.set("dubbing.mode", currentValue)
                            }
                        }
                        FormRow {
                            label: "Speakers"
                            hint: "For voice cloning: give each detected speaker their own voice, or use one voice for everyone."
                            StyledComboBox {
                                id: speakersCombo
                                Layout.fillWidth: true
                                accessibleName: "Speakers"
                                toolTipText: "How voice cloning treats several people talking."
                                model: prefsController.speakerOptions
                                onActivated: prefsWin.set("dubbing.speakers", currentValue)
                            }
                        }
                        FormRow {
                            label: "Urdu in Hindi script"
                            hint: "Voice cloning can't speak Urdu directly. On, it reads Urdu lines in Hindi script with the cloned voices; a few words may sound Hindi-accented. Off, Urdu uses a Piper voice."
                            AppSwitch {
                                id: scriptBridgeSwitch
                                onToggled: prefsWin.set("dubbing.script_bridge", checked)
                                accessibleName: "Read Urdu in Hindi script"
                                toolTipText: "Keep the cloned voices for Urdu by reading the lines in Hindi script."
                            }
                            Item { Layout.fillWidth: true }
                        }
                        FormRow {
                            label: "Fastest speech"
                            hint: "Lines that don't fit their time are spoken faster up to this speed, then cut short."
                            SpinBox {
                                id: speedupSpin
                                from: Math.round(prefsController.speedupRange[0] * 100)
                                to: Math.round(prefsController.speedupRange[1] * 100)
                                stepSize: 5
                                editable: true
                                textFromValue: (value, locale) => (value / 100).toFixed(2) + "x"
                                valueFromText: (text, locale) => Math.round(parseFloat(text) * 100)
                                onValueModified: prefsWin.set("dubbing.max_speedup", value / 100)
                                Accessible.name: "Fastest speech"
                                ToolTip.visible: hovered
                                ToolTip.text: "1.00x never speeds speech up; 1.35x is barely noticeable."
                                ToolTip.delay: 600
                            }
                            Item { Layout.fillWidth: true }
                        }
                        FormRow {
                            label: "Save the dub as"
                            StyledComboBox {
                                id: dubOutputCombo
                                Layout.fillWidth: true
                                accessibleName: "Save the dub as"
                                toolTipText: "A new audio track in a copy of the video (.mkv), or a separate WAV file."
                                model: prefsController.dubOutputOptions
                                onActivated: prefsWin.set("dubbing.output", currentValue)
                            }
                        }
                        FormRow {
                            label: "Play the dub by default"
                            hint: "Players start with the dubbed track; the original stays selectable."
                            AppSwitch {
                                id: defaultTrackSwitch
                                onToggled: prefsWin.set("dubbing.default_track", checked)
                                accessibleName: "Play the dub by default"
                                toolTipText: "Mark the dubbed track as the default audio track."
                            }
                            Item { Layout.fillWidth: true }
                        }
                        FormRow {
                            label: "Run on"
                            hint: "Automatic times Kokoro and Piper voices on each supported GPU (NVIDIA, AMD, Intel, or Apple) and the CPU and keeps the fastest until the app closes. Voice cloning uses the first GPU that works, or the CPU."
                            StyledComboBox {
                                id: dubDeviceCombo
                                Layout.fillWidth: true
                                accessibleName: "Dubbing device"
                                toolTipText: "Where speech is generated."
                                model: prefsController.dubDeviceOptions
                                onActivated: prefsWin.set("dubbing.device", currentValue)
                            }
                        }
                    }
                }

                // Subtitles
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Default formats"
                        Flow {
                            Layout.fillWidth: true
                            spacing: Theme.spaceSm
                            Repeater {
                                id: formatRepeater
                                delegate: FormatChip {
                                    required property var modelData
                                    text: modelData.label
                                    checked: modelData.on
                                    onToggled: prefsWin.set("output." + modelData.code, checked)
                                }
                            }
                        }
                    }
                    Card {
                        Layout.fillWidth: true
                        title: "Line layout"
                        description: "Cues are split at sentence ends and pauses to fit these limits. Chinese and Japanese use shorter lines."
                        FormRow {
                            label: "Characters per line"
                            hint: "42 is the broadcast standard."
                            SpinBox {
                                id: lineLengthSpin
                                from: prefsController.lineLengthRange[0]
                                to: prefsController.lineLengthRange[1]
                                editable: true
                                onValueModified: prefsWin.set("output.max_line_length", value)
                                Accessible.name: "Characters per line"
                                ToolTip.visible: hovered
                                ToolTip.text: "Longest line a subtitle may have before it wraps."
                                ToolTip.delay: 600
                            }
                            Item { Layout.fillWidth: true }
                        }
                        FormRow {
                            label: "Lines per subtitle"
                            SpinBox {
                                id: maxLinesSpin
                                from: prefsController.maxLinesRange[0]
                                to: prefsController.maxLinesRange[1]
                                onValueModified: prefsWin.set("output.max_lines", value)
                                Accessible.name: "Lines per subtitle"
                                ToolTip.visible: hovered
                                ToolTip.text: "Most lines shown on screen at once. Longer speech is split into more subtitles."
                                ToolTip.delay: 600
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                    Card {
                        Layout.fillWidth: true
                        title: "Save location"
                        FormRow {
                            label: "Default folder"
                            Text {
                                id: outputDirText
                                Layout.fillWidth: true
                                text: ""
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontBody
                                color: text ? Theme.text : Theme.textMuted
                                elide: Text.ElideMiddle
                                Accessible.name: "Default folder: " + (text || "same folder as each source file")
                            }
                            AppButton {
                                text: "Browse..."
                                toolTipText: "Choose a default folder for all subtitle files"
                                onClicked: outputFolderPicker.open()
                            }
                            AppButton {
                                kind: "ghost"
                                text: "Use source folder"
                                visible: outputDirText.text.length > 0
                                onClicked: { outputDirText.text = ""; prefsWin.set("output.directory", "") }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: outputDirText.text.length === 0
                            text: "Subtitles are saved next to each source file."
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                        }
                    }
                }

                // Advanced
                Page {
                    Card {
                        Layout.fillWidth: true
                        title: "Logging"
                        description: "Logs stay on this computer. Attach them when reporting a problem."
                        trailing: AppSwitch {
                            id: logsSwitch
                            onToggled: prefsWin.set("logging.enable_logs", checked)
                            accessibleName: "Write log files"
                            toolTipText: "Keep a log file to help diagnose problems."
                        }
                        FormRow {
                            label: "Detail"
                            enabled: logsSwitch.checked
                            StyledComboBox {
                                id: logLevelCombo
                                Layout.fillWidth: true
                                accessibleName: "Log detail"
                                toolTipText: "How much is written to the log file."
                                model: prefsController.logLevelOptions
                                onActivated: prefsWin.set("logging.log_level", currentValue)
                            }
                        }
                        RowLayout {
                            spacing: Theme.spaceSm
                            AppButton {
                                text: "Open logs folder"
                                iconName: "folderOpen"
                                toolTipText: "Show the log files in File Explorer"
                                onClicked: appController.openLogsFolder()
                            }
                            AppButton {
                                kind: "danger"
                                text: "Clear logs"
                                iconName: "delete"
                                toolTipText: "Delete the contents of the log files"
                                onClicked: clearedText.text = appController.clearLogs() ? "Logs cleared." : "Couldn't clear the logs."
                            }
                            Text {
                                id: clearedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontCaption
                                color: Theme.textMuted
                            }
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        // Footer
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.spaceMd
            Layout.leftMargin: Theme.spaceLg
            Layout.rightMargin: Theme.spaceLg
            spacing: Theme.spaceSm

            AppButton {
                kind: "ghost"
                text: "Reset to defaults"
                toolTipText: "Restore every preference to its original value"
                onClicked: resetDialog.open()
            }
            Text {
                id: saveError
                Layout.fillWidth: true
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.danger
                wrapMode: Text.WordWrap
            }
            Text {
                visible: prefsWin.dirty && saveError.text.length === 0
                text: "Unsaved changes"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
            }
            AppButton {
                text: "Cancel"
                toolTipText: "Close without saving (Esc)"
                onClicked: prefsWin.close()
            }
            AppButton {
                kind: "primary"
                text: "Save"
                toolTipText: "Save and close (Ctrl+S)"
                onClicked: prefsWin.save()
            }
        }
    }

    // A scrollable column of cards for one preferences section.
    component Page: ScrollView {
        id: page
        default property alias cards: column.data
        contentWidth: availableWidth
        contentHeight: column.implicitHeight + 2 * Theme.spaceLg
        clip: true

        ColumnLayout {
            id: column
            x: Theme.spaceXl
            y: Theme.spaceLg
            width: page.availableWidth - 2 * Theme.spaceXl
            spacing: Theme.spaceLg
        }
    }
}
