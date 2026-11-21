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

    function openFiles() { queuePanel.openFiles() }
    function openFolder() { queuePanel.openFolder() }
    function showSettings() { innerTabs.currentIndex = 0 }

    Connections {
        target: page.controller
        function onNotice(message) { page.notice(message) }
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

                        ColumnLayout {
                            width: settingsPage.availableWidth
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
                                    text: "Settings are locked while files are processing. Changes apply to the next run."
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontCaption
                                    color: Theme.text
                                    wrapMode: Text.WordWrap
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
        }
    }
}
