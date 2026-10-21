// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

// One tab's file queue: header with counts, add buttons, queue menu, and the file list.
// `controller` is that tab's TaskController.
Rectangle {
    id: panel

    required property var controller
    property var firstRunSteps: []
    property var sendTargets: []
    property bool allowCompanion: false

    signal sendRequested(string target, string path, var outputs)

    readonly property var queue: panel.controller.fileModel

    function openFiles() { filePicker.open() }
    function openFolder() { folderPicker.open() }

    color: Theme.surface

    FileDialog {
        id: filePicker
        title: "Add " + panel.controller.fileNoun + "s"
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            "Usable files (" + panel.controller.acceptedExtensions.map(ext => "*." + ext).join(" ") + ")",
            "All files (*)"
        ]
        onAccepted: panel.controller.addFiles(selectedFiles)
    }

    FolderDialog {
        id: folderPicker
        title: "Add every usable file in a folder (including subfolders)"
        onAccepted: panel.controller.addFolder(selectedFolder.toString())
    }

    FileDialog {
        id: companionPicker
        property int row: -1
        title: "Choose the subtitle file to speak"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Subtitle files (*.srt *.vtt *.lrc *.ass *.ssa *.sbv)"]
        onAccepted: panel.queue.setCompanion(companionPicker.row, appController.localPath(selectedFile.toString()))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.spaceLg
            Layout.bottomMargin: Theme.spaceSm
            spacing: Theme.spaceSm

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Queue"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                    color: Theme.text
                    Accessible.role: Accessible.Heading
                    Accessible.name: "Queue"
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: panel.queue.count === 0 ? "" :
                        panel.queue.count + (panel.queue.count === 1 ? " file" : " files") + "  ·  " + panel.queue.totalSize
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceSm

                AppButton {
                    kind: "primary"
                    text: "Add files"
                    iconName: "add"
                    toolTipText: "Add " + panel.controller.fileNoun + "s (Ctrl+O)"
                    onClicked: filePicker.open()
                }
                AppButton {
                    text: "Add folder"
                    iconName: "folder"
                    toolTipText: "Add every usable file in a folder and its subfolders (Ctrl+Shift+O)"
                    onClicked: folderPicker.open()
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    id: queueMenuButton
                    kind: "ghost"
                    iconName: "more"
                    toolTipText: "More queue actions"
                    enabled: panel.queue.count > 0
                    onClicked: queueMenu.popup(queueMenuButton, 0, queueMenuButton.height)

                    Menu {
                        id: queueMenu
                        MenuItem {
                            text: "Select all"
                            onTriggered: panel.queue.selectAll()
                        }
                        MenuItem {
                            text: "Remove selected"
                            enabled: panel.queue.selectedCount > 0
                            onTriggered: panel.queue.removeSelected()
                        }
                        MenuItem {
                            text: "Remove finished"
                            enabled: panel.queue.doneCount > 0
                            onTriggered: panel.queue.removeFinished()
                        }
                        MenuSeparator {}
                        MenuItem {
                            text: "Clear queue"
                            onTriggered: panel.controller.clearQueue()
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        FileList {
            Layout.fillWidth: true
            Layout.fillHeight: true
            fileModel: panel.queue
            scanning: panel.controller.scanning
            scanFound: panel.controller.scanFound
            firstRunSteps: panel.firstRunSteps
            sendTargets: panel.sendTargets
            allowCompanion: panel.allowCompanion
            languageOptions: prefsController.targetOptions
            languageRequired: panel.controller.needsSubtitleLanguage
            onAddFilesRequested: filePicker.open()
            onAddFolderRequested: folderPicker.open()
            onFilesDropped: urls => panel.controller.addFiles(urls)
            onRevealRequested: path => appController.revealFile(path)
            onStopScanRequested: panel.controller.cancelScan()
            onClearRequested: panel.controller.clearQueue()
            onSendRequested: (target, path, outputs) => panel.sendRequested(target, path, outputs)
            onCompanionRequested: row => {
                companionPicker.row = row
                // Start next to the video, where its subtitles usually are.
                companionPicker.currentFolder = appController.folderUrl(panel.queue.rowAt(row).path || "")
                companionPicker.open()
            }
        }
    }
}
