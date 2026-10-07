// qmllint disable unqualified
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "components"
import "pages"

AppWindow {
    id: mainWin

    width: 1180
    height: 760
    minimumWidth: 900
    minimumHeight: 580
    visible: true
    title: appController.appName + " " + appController.appVersion

    property var _prefsWindow: null
    property var _modelsWindow: null

    // Every tab, in order. Shortcuts (Ctrl+1...), "Send to" menus, and the About text all
    // derive from this list, so adding a tab never means updating hard-coded indexes.
    readonly property var tasks: [
        { key: "generate", label: "Generate", icon: "mic", controller: generateController },
        { key: "translate", label: "Translate", icon: "globe", controller: translateController },
        { key: "transliterate", label: "Transliterate", icon: "characters", controller: transliterateController },
        { key: "dub", label: "Dub", icon: "speaker", controller: dubController },
        { key: "workflow", label: "Workflow", icon: "workflow", controller: workflowController }
    ]
    readonly property var currentPage: pages.children[tabs.currentIndex]
    readonly property var currentController: mainWin.tasks[tabs.currentIndex].controller

    // quitOnLastWindowClosed is disabled app-wide (see app.py) since it can misfire while a
    // QML window is still open, so closing the main window quits explicitly.
    onClosing: Qt.quit()

    titleActions: [
        AppButton {
            kind: "ghost"
            compact: true
            text: "Models"
            iconName: "library"
            toolTipText: "Manage downloaded models and voices (Ctrl+M)"
            focusPolicy: Qt.TabFocus
            onClicked: mainWin.openModels()
        },
        AppButton {
            kind: "ghost"
            compact: true
            text: "Preferences"
            iconName: "settings"
            toolTipText: "Default settings, appearance, and logs (Ctrl+,)"
            focusPolicy: Qt.TabFocus
            onClicked: mainWin.openPreferences()
        },
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "info"
            toolTipText: "About " + appController.appName + " (F1)"
            focusPolicy: Qt.TabFocus
            onClicked: aboutDialog.open()
        }
    ]

    // ── Windows ────────────────────────────────────────────────────────────

    function openPreferences() {
        if (!mainWin._prefsWindow) {
            var comp = Qt.createComponent("PreferencesWindow.qml")
            if (comp.status !== Component.Ready) { console.error(comp.errorString()); return }
            mainWin._prefsWindow = comp.createObject(mainWin)
            mainWin._prefsWindow.closing.connect(function() { mainWin._prefsWindow = null })
        }
        mainWin._prefsWindow.show()
        mainWin._prefsWindow.raise()
        mainWin._prefsWindow.requestActivate()
    }

    function openModels() {
        if (!mainWin._modelsWindow) {
            var comp = Qt.createComponent("ManageModelsWindow.qml")
            if (comp.status !== Component.Ready) { console.error(comp.errorString()); return }
            mainWin._modelsWindow = comp.createObject(mainWin)
            mainWin._modelsWindow.closing.connect(function() { mainWin._modelsWindow = null })
        }
        mainWin._modelsWindow.show()
        mainWin._modelsWindow.raise()
        mainWin._modelsWindow.requestActivate()
    }

    // Hand a finished file's results to another tab, each with the language it is in.
    function sendFiles(fromKey, toKey, sourcePath, outputs) {
        var from = mainWin.tasks.findIndex(t => t.key === fromKey)
        var to = mainWin.tasks.findIndex(t => t.key === toKey)
        if (from < 0 || to < 0 || outputs.length === 0) return
        var languages = outputs.map(path => mainWin.tasks[from].controller.outputLanguage(path))
        mainWin.tasks[to].controller.receiveFiles(outputs, sourcePath, languages)
        tabs.currentIndex = to
    }

    function sendTargetsFor(keys) {
        return mainWin.tasks.filter(t => keys.indexOf(t.key) >= 0).map(t => ({ key: t.key, label: t.label + " tab" }))
    }

    // ── Keyboard shortcuts ─────────────────────────────────────────────────

    Shortcut { sequences: [StandardKey.Open]; onActivated: mainWin.currentPage.openFiles() }
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: mainWin.currentPage.openFolder() }
    Shortcut { sequences: ["Ctrl+Return", "Ctrl+Enter", "F5"]; onActivated: mainWin.currentController.startQueue() }
    Shortcut { sequence: "Escape"; enabled: mainWin.currentController.busy; onActivated: mainWin.currentController.cancelQueue() }
    Shortcut { sequence: "Ctrl+,"; onActivated: mainWin.openPreferences() }
    Shortcut { sequence: "Ctrl+M"; onActivated: mainWin.openModels() }
    Shortcut { sequence: "F1"; onActivated: aboutDialog.open() }
    Instantiator {
        model: mainWin.tasks.length
        delegate: Shortcut {
            required property int index
            sequence: "Ctrl+" + (index + 1)
            onActivated: tabs.currentIndex = index
        }
    }

    Connections {
        target: prefsController
        function onSaveFinished(success, error) {
            if (!success) return
            for (var i = 0; i < mainWin.tasks.length; i++) mainWin.tasks[i].controller.reloadDefaults()
        }
    }

    // The detected hardware chose or changed the performance profile.
    Connections {
        target: performanceController
        function onNotice(message) { toast.show(message) }
        function onSettingsSaved() {
            prefsController.loadSettings()
            for (var i = 0; i < mainWin.tasks.length; i++) mainWin.tasks[i].controller.reloadDefaults()
        }
    }

    // ── Layout ─────────────────────────────────────────────────────────────

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: tabs
            objectName: "taskTabs"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spaceLg
            Layout.topMargin: Theme.spaceSm
            background: Item {}

            Repeater {
                model: mainWin.tasks
                delegate: TabButton {
                    id: tabButton
                    required property var modelData
                    required property int index
                    width: implicitWidth + 28
                    font.pixelSize: Theme.fontBody
                    Accessible.name: modelData.label + (modelData.controller.busy ? ", running" : "")
                    ToolTip.visible: hovered
                    ToolTip.text: modelData.label + " (Ctrl+" + (index + 1) + ")"
                    ToolTip.delay: 600

                    contentItem: RowLayout {
                        spacing: Theme.spaceSm
                        Icon {
                            name: tabButton.modelData.icon
                            size: 14
                            color: tabButton.checked ? Theme.accent : Theme.textMuted
                        }
                        Text {
                            text: tabButton.modelData.label
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            font.weight: tabButton.checked ? Font.DemiBold : Font.Normal
                            color: tabButton.checked ? Theme.text : Theme.textMuted
                        }
                        BusyIndicator {
                            visible: tabButton.modelData.controller.busy
                            running: visible
                            Layout.preferredWidth: 14
                            Layout.preferredHeight: 14
                            padding: 0
                            Accessible.ignored: true
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        StackLayout {
            id: pages
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            TaskPage {
                controller: generateController
                firstRunSteps: [
                    "Add the videos or audio you want subtitles for.",
                    "Check the model, language, and formats in Settings.",
                    "Press Start (Ctrl+Enter). Send the results to Translate or Dub from the queue menu."
                ]
                sendTargets: mainWin.sendTargetsFor(["translate", "transliterate", "dub"])
                emptyResultsText: "Subtitles appear here as each file is transcribed."
                onSendRequested: (target, path, outputs) => mainWin.sendFiles("generate", target, path, outputs)
                onNotice: message => toast.show(message)

                GenerateSettings {
                    Layout.fillWidth: true
                    options: generateController.options
                    onOptionChanged: (key, value) => generateController.setOption(key, value)
                }
                OutputSettings {
                    Layout.fillWidth: true
                    options: generateController.options
                    namingExample: "movie.srt"
                    onOptionChanged: (key, value) => generateController.setOption(key, value)
                    onFormatToggled: (code, enabled) => generateController.setFormat(code, enabled)
                }
            }

            TaskPage {
                controller: translateController
                firstRunSteps: [
                    "Add subtitle files, or send them here from the Generate tab.",
                    "Choose the language to translate into.",
                    "Press Start (Ctrl+Enter)."
                ]
                sendTargets: mainWin.sendTargetsFor(["transliterate", "dub"])
                emptyResultsText: "Each line and its translation appear here."
                onSendRequested: (target, path, outputs) => mainWin.sendFiles("translate", target, path, outputs)
                onNotice: message => toast.show(message)

                TranslateSettings {
                    Layout.fillWidth: true
                    options: translateController.options
                    onOptionChanged: (key, value) => translateController.setOption(key, value)
                }
                OutputSettings {
                    Layout.fillWidth: true
                    options: translateController.options
                    namingExample: "movie_ur.srt"
                    onOptionChanged: (key, value) => translateController.setOption(key, value)
                    onFormatToggled: (code, enabled) => translateController.setFormat(code, enabled)
                }
            }

            TaskPage {
                controller: transliterateController
                firstRunSteps: [
                    "Add subtitle files, or send them here from another tab.",
                    "Choose the scripts to convert between.",
                    "Press Start (Ctrl+Enter)."
                ]
                sendTargets: mainWin.sendTargetsFor(["translate", "dub"])
                emptyResultsText: "Each line and its new script appear here."
                onSendRequested: (target, path, outputs) => mainWin.sendFiles("transliterate", target, path, outputs)
                onNotice: message => toast.show(message)

                TransliterateSettings {
                    Layout.fillWidth: true
                    options: transliterateController.options
                    onOptionChanged: (key, value) => transliterateController.setOption(key, value)
                }
                OutputSettings {
                    Layout.fillWidth: true
                    options: transliterateController.options
                    namingExample: "movie_tr_ur_roman.srt"
                    onOptionChanged: (key, value) => transliterateController.setOption(key, value)
                    onFormatToggled: (code, enabled) => transliterateController.setFormat(code, enabled)
                }
            }

            TaskPage {
                controller: dubController
                allowCompanion: true
                firstRunSteps: [
                    "Add a video together with the subtitle to speak (movie.mp4 and movie_es.srt pair up), or send a translation here.",
                    "Choose the voices. Voice cloning keeps each speaker's own voice.",
                    "Press Start (Ctrl+Enter). The dub is added as a new audio track."
                ]
                emptyResultsText: "The lines being spoken appear here."
                onNotice: message => toast.show(message)

                DubSettings {
                    Layout.fillWidth: true
                    options: dubController.options
                    onOptionChanged: (key, value) => dubController.setOption(key, value)
                }
                OutputSettings {
                    Layout.fillWidth: true
                    options: dubController.options
                    showFormats: false
                    namingExample: "movie_dub_es.mkv"
                    onOptionChanged: (key, value) => dubController.setOption(key, value)
                }
            }

            TaskPage {
                controller: workflowController
                firstRunSteps: [
                    "Add videos, audio, or subtitle files.",
                    "Build the steps in Settings, e.g. Generate, Translate, then Dub.",
                    "Press Start (Ctrl+Enter). Every file runs through every step."
                ]
                sendTargets: mainWin.sendTargetsFor(["translate", "transliterate", "dub"])
                emptyResultsText: "Lines from every step appear here as they are made."
                onSendRequested: (target, path, outputs) => mainWin.sendFiles("workflow", target, path, outputs)
                onNotice: message => toast.show(message)

                WorkflowEditor {
                    Layout.fillWidth: true
                }
                OutputSettings {
                    Layout.fillWidth: true
                    options: workflowController.options
                    namingExample: "movie.srt, movie_ur.srt, movie_dub_ur.mkv"
                    onOptionChanged: (key, value) => workflowController.setOption(key, value)
                    onFormatToggled: (code, enabled) => workflowController.setFormat(code, enabled)
                }
            }
        }
    }

    Toast {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 88
        z: 50
    }

    // ── About ──────────────────────────────────────────────────────────────

    AppDialog {
        id: aboutDialog
        title: "About " + appController.appName
        standardButtons: Dialog.Close
        width: Math.min(480, mainWin.width - 48)

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.spaceMd

            RowLayout {
                spacing: Theme.spaceLg
                Image {
                    source: "../assets/icons/Square44x44Logo.targetsize-48.png"
                    Layout.preferredWidth: 48
                    Layout.preferredHeight: 48
                    fillMode: Image.PreserveAspectFit
                    Accessible.ignored: true
                }
                ColumnLayout {
                    spacing: 2
                    Text {
                        text: appController.appName + " " + appController.appVersion
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSubtitle
                        font.weight: Font.DemiBold
                        color: Theme.text
                    }
                    Text {
                        text: "By " + appController.appAuthor
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.textMuted
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: appController.appDescription + ". Everything runs on this computer; nothing is uploaded."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "Shortcuts: Ctrl+O add files, Ctrl+Shift+O add folder, Ctrl+Enter start, Esc cancel, "
                    + "Ctrl+, preferences, Ctrl+M models, Ctrl+1 to Ctrl+" + mainWin.tasks.length + " switch tabs ("
                    + mainWin.tasks.map(t => t.label).join(", ") + ")."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
        }
    }
}
