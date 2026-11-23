import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

// The layout every task tab shares: its queue on the left, its settings and live results on
// the right, and its run bar along the bottom. The settings cards are the page's children.
Item {
    id: page

    required property var controller
    property var firstRunSteps: []
    property var sendTargets: []
    property bool allowCompanion: false
    property string emptyResultsText: "Lines appear here as each file is processed."
    default property alias settingsContent: settingsColumn.data

    signal sendRequested(string target, string path, var outputs)
    signal notice(string message)
    // "Change" beside what the tab relies on: open the Preferences.
    signal preferencesRequested()

    function openFiles() { queuePanel.openFiles() }
    function openFolder() { queuePanel.openFolder() }
    function showSettings() { innerTabs.currentIndex = 0 }

    Connections {
        target: page.controller
        function onNotice(message) { page.notice(message) }
        function onExistingFound(count, example) {
            existingDialog.count = count
            existingDialog.example = example
            existingDialog.open()
        }
    }

    // Asked once per run when results are already there; nothing is replaced without an answer.
    AppDialog {
        id: existingDialog
        property int count: 0
        property string example: ""
        parent: Overlay.overlay
        title: existingDialog.count === 1 ? "Its results are already there" : "Some results are already there"
        width: Math.min(460, page.width - 48)
        standardButtons: Dialog.Cancel

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: (existingDialog.count === 1
                       ? existingDialog.example + " already has its results, such as its subtitle file."
                       : existingDialog.count + " files, such as " + existingDialog.example + ", already have results.")
                    + " What should happen to them?"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceSm
                AppButton {
                    kind: "primary"
                    text: "Keep both"
                    toolTipText: "Keep the old files; the new ones get \" (2)\" in their names"
                    onClicked: { existingDialog.close(); page.controller.startWith("keep_both") }
                }
                AppButton {
                    text: "Skip them"
                    toolTipText: "Leave those files out of this run"
                    onClicked: { existingDialog.close(); page.controller.startWith("skip") }
                }
                AppButton {
                    kind: "danger"
                    text: "Replace"
                    toolTipText: "Write the new files over the old ones"
                    onClicked: { existingDialog.close(); page.controller.startWith("replace") }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Rectangle {
                implicitWidth: 5
                color: SplitHandle.pressed || SplitHandle.hovered ? Theme.accentSoft : Theme.background
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 1
                    height: parent.height
                    color: Theme.border
                }
            }

            QueuePanel {
                id: queuePanel
                SplitView.preferredWidth: 380
                SplitView.minimumWidth: 280
                SplitView.maximumWidth: 600
                controller: page.controller
                firstRunSteps: page.firstRunSteps
                sendTargets: page.sendTargets
                allowCompanion: page.allowCompanion
                onSendRequested: (target, path, outputs) => page.sendRequested(target, path, outputs)
            }

            ColumnLayout {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                spacing: 0

                TabBar {
                    id: innerTabs
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.spaceLg
                    Layout.topMargin: Theme.spaceSm
                    background: Item {}

                    TabButton {
                        text: page.controller.busy ? "Settings (locked)" : "Settings"
                        width: implicitWidth + 24
                        font.pixelSize: Theme.fontBody
                        ToolTip.visible: hovered
                        ToolTip.text: "Options for the next run"
                        ToolTip.delay: 600
                    }
                    TabButton {
                        text: results.count > 0 ? "Results (" + results.count + ")" : "Results"
                        width: implicitWidth + 24
                        font.pixelSize: Theme.fontBody
                        ToolTip.visible: hovered
                        ToolTip.text: "Live lines of the file being processed"
                        ToolTip.delay: 600
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: innerTabs.currentIndex

                    ScrollView {
                        id: settingsPage
                        contentWidth: availableWidth
                        clip: true

                        FocusScroll { flickable: settingsPage.contentItem as Flickable }

                        ColumnLayout {
                            // Settings read best in a column; maximized, the rest stays empty.
                            width: Math.min(settingsPage.availableWidth, 760 + 2 * Theme.spaceXl)
                            spacing: Theme.spaceLg

                            Item { Layout.preferredHeight: Theme.spaceXs }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.leftMargin: Theme.spaceXl
                                Layout.rightMargin: Theme.spaceXl
                                Layout.preferredHeight: lockedText.implicitHeight + 2 * Theme.spaceMd
                                radius: Theme.radius
                                color: Theme.accentSoft
                                visible: page.controller.busy

                                Text {
                                    id: lockedText
                                    anchors.fill: parent
                                    anchors.margins: Theme.spaceMd
                                    textFormat: Text.PlainText
                                    text: "Settings are locked while files are processing. Changes apply to the next run."
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontCaption
                                    color: Theme.text
                                    wrapMode: Text.WordWrap
                                }
                            }

                            // What the tab runs with besides its own options (the saved Generate model, and
                            // for dubbing the translation model), so nothing it relies on is hidden.
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.leftMargin: Theme.spaceXl
                                Layout.rightMargin: Theme.spaceXl
                                visible: page.controller.reliesOn.length > 0
                                spacing: Theme.spaceSm

                                Icon {
                                    name: "info"
                                    size: Theme.iconMd
                                    color: Theme.textMuted
                                }
                                Text {
                                    Layout.fillWidth: true
                                    textFormat: Text.PlainText
                                    text: page.controller.reliesOn
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontCaption
                                    color: Theme.textMuted
                                    wrapMode: Text.WordWrap
                                }
                                AppButton {
                                    kind: "ghost"
                                    compact: true
                                    text: "Change"
                                    toolTipText: "Choose these in Preferences (Ctrl+,)"
                                    onClicked: page.preferencesRequested()
                                }
                            }

                            ColumnLayout {
                                id: settingsColumn
                                Layout.fillWidth: true
                                Layout.leftMargin: Theme.spaceXl
                                Layout.rightMargin: Theme.spaceXl
                                spacing: Theme.spaceLg
                                enabled: !page.controller.busy
                            }

                            Item { Layout.preferredHeight: Theme.spaceLg }
                        }
                    }

                    ResultsView {
                        id: results
                        controller: page.controller
                        emptyText: page.emptyResultsText
                        onFirstFileStarted: innerTabs.currentIndex = 1
                    }
                }
            }
        }

        RunBar {
            Layout.fillWidth: true
            controller: page.controller
            updates: updateController  // qmllint disable unqualified
            models: modelsController  // qmllint disable unqualified
            onLanguageRequested: path => queuePanel.showRow(path)
        }
    }
}
