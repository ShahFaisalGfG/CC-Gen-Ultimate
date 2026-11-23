// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Status, progress, and Start / Cancel for one tab's queue. Progress counts every step of the
// current file, so it never jumps backwards when a new step begins. A reason Start can't run wraps
// in full and carries the button that fixes it (review a licence, choose a subtitle's language);
// after a run, failures show in red with Try again.
Rectangle {
    id: bar

    required property var controller
    // The app's UpdateController, whose notice shows below the status while no run is going.
    property var updates: null
    // The app's AssetsController, whose downloads show here while they run.
    property var models: null
    readonly property var queue: bar.controller.fileModel
    readonly property bool busy: bar.controller.busy
    readonly property bool _blocked: !bar.busy && !bar.controller.scanning && bar.controller.blocker.length > 0
        && bar.queue.count > 0
    readonly property bool _failedRun: !bar.busy && bar.controller.failedFiles.length > 0
    readonly property bool _allDone: bar.queue.count > 0 && bar.queue.doneCount === bar.queue.count

    // Ask to choose the language of this subtitle (the "Choose language" action).
    signal languageRequested(string path)

    implicitHeight: Math.max(72, content.implicitHeight + 2 * Theme.spaceMd)
    color: Theme.surface

    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

    ModelTermsDialog {
        id: termsDialog
        parent: Overlay.overlay
        model: bar.controller.pendingLicence || "omnivoice"
        onAccepted: statusText.Accessible.announce(termsDialog.terms.title + " accepted.")
    }

    RowLayout {
        id: content
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceXl
        anchors.rightMargin: Theme.spaceXl
        anchors.topMargin: Theme.spaceMd
        anchors.bottomMargin: Theme.spaceMd
        spacing: Theme.spaceLg

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: Theme.spaceXs

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceSm

                Icon {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 2
                    visible: bar._blocked || bar._failedRun
                    name: bar._failedRun && !bar._blocked ? "error" : "warning"
                    size: Theme.iconMd
                    color: bar._failedRun && !bar._blocked ? Theme.danger : Theme.warning
                }
                Text {
                    id: statusText
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: {
                        if (bar.busy) {
                            var stage = bar.controller.stage || "Working..."
                            return "File " + bar.controller.runPosition + " of " + bar.controller.runTotal + "  ·  " + stage
                        }
                        if (bar.controller.scanning) return "Scanning folder... " + bar.controller.scanFound + " files found so far."
                        // A reason Start is unavailable matters more than how the last run went.
                        if (bar._blocked) return bar.controller.blocker
                        if (bar.controller.summary) return bar.controller.summary
                        if (bar.controller.blocker) return bar.controller.blocker
                        if (bar._allDone) return "Every file is done. Run again to make the results again."
                        return "Ready to process " + bar.queue.runnableCount + (bar.queue.runnableCount === 1 ? " file." : " files.")
                    }
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                    color: bar._blocked ? Theme.warning : bar._failedRun ? Theme.danger : Theme.text
                    // A blocker says what to do, so it wraps instead of being cut short.
                    wrapMode: bar.busy ? Text.NoWrap : Text.WordWrap
                    maximumLineCount: bar.busy ? 1 : 3
                    elide: Text.ElideRight
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
                Text {
                    visible: bar.busy
                    textFormat: Text.PlainText
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
                textFormat: Text.PlainText
                text: bar.controller.currentFile
                    + (bar.controller.stageProgress >= 0
                       ? "  ·  " + Math.round(bar.controller.stageProgress * 100) + "% of this step" : "")
                    + (bar.controller.timeText ? "  ·  " + bar.controller.timeText : "")
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                elide: Text.ElideMiddle
            }

            // What a finished run took, what Start downloads first, or a model download in progress.
            Text {
                Layout.fillWidth: true
                visible: !bar.busy && text.length > 0
                textFormat: Text.PlainText
                text: {
                    if (bar.models && bar.models.busy) return bar.models.busyText
                    if (bar._blocked) return ""
                    if (bar.controller.summary && bar.controller.timeText) return bar.controller.timeText
                    return bar.controller.downloadNote
                }
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }

            UpdateNotice {
                Layout.fillWidth: true
                controller: bar.updates
                visible: !bar.busy && bar.updates !== null && bar.updates.bannerVisible
            }
        }

        AppButton {
            visible: bar._blocked && bar.controller.pendingLicence.length > 0
            text: "Review licence"
            iconName: "page"
            toolTipText: "Read the licence terms and accept them once"
            onClicked: termsDialog.open()
        }

        AppButton {
            visible: bar._blocked && bar.controller.blockingPath.length > 0
            text: "Choose language"
            iconName: "globe"
            toolTipText: "Show the file whose language Start needs"
            onClicked: bar.languageRequested(bar.controller.blockingPath)
        }

        AppButton {
            visible: bar._failedRun && !bar._blocked
            text: "Try again failed"
            iconName: "sync"
            toolTipText: "Run only the files that failed"
            onClicked: bar.controller.retryFailed()
        }

        AppButton {
            visible: !bar.busy && !bar._blocked && bar.controller.lastOutputFolder.length > 0
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
            toolTipText: "Stop now. The file being processed stops at its next safe point; it and the rest stay queued (Esc)"
            onClicked: bar.controller.cancelQueue()
        }

        AppButton {
            visible: !bar.busy
            kind: "primary"
            text: bar._allDone ? "Run again" : bar.queue.runnableCount > 0 ? "Start (" + bar.queue.runnableCount + ")" : "Start"
            iconName: bar._allDone ? "sync" : "play"
            enabled: bar.controller.blocker.length === 0
            toolTipText: enabled ? (bar._allDone ? "Process every file again (Ctrl+Enter)" : "Process the queue (Ctrl+Enter)")
                                 : bar.controller.blocker
            onClicked: bar.controller.startQueue()
        }
    }
}
