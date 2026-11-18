// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Status, progress, and Start / Cancel for one tab's queue. Progress counts every step of the
// current file, so it never jumps backwards when a new step begins.
Rectangle {
    id: bar

    required property var controller
    // The app's UpdateController, whose notice shows below the status while no run is going.
    property var updates: null
    readonly property var queue: bar.controller.fileModel
    readonly property bool busy: bar.controller.busy

    implicitHeight: 72
    color: Theme.surface

    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceXl
        anchors.rightMargin: Theme.spaceXl
        spacing: Theme.spaceLg

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceXs

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceSm

                Text {
                    Layout.fillWidth: true
                    text: {
                        if (bar.busy) {
                            var stage = bar.controller.stage || "Working..."
                            return "File " + bar.controller.runPosition + " of " + bar.controller.runTotal + "  ·  " + stage
                        }
                        if (bar.controller.scanning) return "Scanning folder... " + bar.controller.scanFound + " files found so far."
                        // A reason Start is unavailable matters more than how the last run went.
                        if (bar.controller.blocker && bar.queue.count > 0) return bar.controller.blocker
                        if (bar.controller.summary) return bar.controller.summary
                        return bar.controller.blocker
                            || ("Ready to process " + bar.queue.runnableCount + (bar.queue.runnableCount === 1 ? " file." : " files."))
                    }
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                    color: !bar.busy && !bar.controller.scanning && bar.controller.blocker && bar.queue.count > 0
                        ? Theme.warning : Theme.text
                    elide: Text.ElideRight
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
                Text {
                    visible: bar.busy
                    text: Math.round(bar.controller.overallProgress * 100) + "%"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                }
            }

            ProgressBar {
                Layout.fillWidth: true
                visible: bar.busy
                from: 0
                to: 1
                value: bar.controller.overallProgress
                Accessible.role: Accessible.ProgressBar
                Accessible.name: "Overall progress"
            }

            Text {
                Layout.fillWidth: true
                visible: bar.busy && bar.controller.currentFile.length > 0
                text: bar.controller.currentFile
                    + (bar.controller.stageProgress >= 0
                       ? "  ·  " + Math.round(bar.controller.stageProgress * 100) + "% of this step" : "")
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                elide: Text.ElideMiddle
            }

            UpdateNotice {
                Layout.fillWidth: true
                controller: bar.updates
                visible: !bar.busy && bar.updates !== null && bar.updates.bannerVisible
            }
        }

        AppButton {
            visible: !bar.busy && bar.controller.lastOutputFolder.length > 0
            text: "Open output folder"
            iconName: "folderOpen"
            toolTipText: bar.controller.lastOutputFolder
            onClicked: appController.openFolder(bar.controller.lastOutputFolder)
        }

        AppButton {
            visible: bar.busy
            kind: "danger"
            text: "Cancel"
            iconName: "stop"
            toolTipText: "Stop after the current step; remaining files stay queued (Esc)"
            onClicked: bar.controller.cancelQueue()
        }

        AppButton {
            visible: !bar.busy
            kind: "primary"
            text: bar.queue.runnableCount > 0 ? "Start (" + bar.queue.runnableCount + ")" : "Start"
            iconName: "play"
            enabled: bar.controller.blocker.length === 0
            toolTipText: enabled ? "Process the queue (Ctrl+Enter)" : bar.controller.blocker
            onClicked: bar.controller.startQueue()
        }
    }
}
