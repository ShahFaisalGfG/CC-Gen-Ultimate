// qmllint disable unqualified
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

// Every downloadable model, one tab per kind. The rows come from modelsController's list models,
// which update one row per download event, so keyboard focus and a screen reader's place stay put
// while models download.
AppWindow {
    id: manageWin

    width: 860
    height: 700
    minimumWidth: 680
    minimumHeight: 520
    title: "Manage Models"
    modality: Qt.ApplicationModal

    readonly property var categories: [
        { key: "whisper", label: "Transcription",
          hint: "Whisper speech recognition models, which make the subtitles. Larger models are more accurate and slower; Automatic picks one for this PC's performance profile." },
        { key: "translation", label: "Translation",
          hint: "Offline translation models, grouped as in Preferences > Translation. Automatic uses OPUS-MT for most pairs and Hy-MT2 for Japanese, Korean, and Chinese. OPUS-MT and Argos have one model per direction, with English bridging other pairs; Hy-MT2, NLLB, and MADLAD each cover every pair in one download. The meaning check compares each translation with the original." },
        { key: "transliteration", label: "Transliteration",
          hint: "Neural models for more natural script conversion between Roman, Urdu, Hindi, and Punjabi. The rule-based engine needs no download." },
        { key: "voices", label: "Voices",
          hint: "Dubbing voices, grouped as in the Dub tab. OmniVoice and XTTS-v2 clone the original speakers, and OmniVoice also speaks Urdu; Kokoro and Piper are ready-made voices that run fast on any PC. Each downloads once." }
    ]

    // Models licensed for non-commercial use only ask for their licence once before the
    // first download: OmniVoice and XTTS-v2 voice cloning, and the NLLB-200 translation model.
    readonly property var licensedModels: ({
        "voices:omnivoice": "omnivoice",
        "voices:xtts": "xtts",
        "translation:nllb-1.3b": "nllb"
    })

    onClosing: manageWin.destroy()

    Shortcut { sequence: "Escape"; onActivated: manageWin.close() }
    Shortcut {
        sequences: ["Ctrl+Tab"]
        onActivated: tabBar.currentIndex = (tabBar.currentIndex + 1) % tabBar.count
    }
    Shortcut {
        sequences: ["Ctrl+Shift+Tab", "Ctrl+Backtab"]
        onActivated: tabBar.currentIndex = (tabBar.currentIndex + tabBar.count - 1) % tabBar.count
    }

    Connections {
        target: modelsController
        function onRemoveFailed(id, message) {
            banner.text = message
            banner.Accessible.announce(message)
        }
    }

    // "the meaning check model" becomes "The meaning check model" at the start of a sentence.
    function sentence(text) {
        return text.length > 0 ? text.charAt(0).toUpperCase() + text.slice(1) : text
    }

    function requestDownload(id) {
        var model = manageWin.licensedModels[id]
        if (model) {
            var setting = prefsController.modelTerms(model).setting.split(".")
            var section = prefsController.settings[setting[0]]
            if (!(section && section[setting[1]])) {
                termsDialog.pendingId = id
                termsDialog.model = model
                termsDialog.open()
                return
            }
        }
        modelsController.downloadAsset(id)
    }

    // Remove-confirmation for bulk actions: `ids` are removed when the user confirms.
    function askRemove(ids, what) {
        if (ids.length === 0) return
        confirmRemove.ids = ids
        confirmRemove.message = "Remove " + what + " (" + ids.length + " model" + (ids.length === 1 ? "" : "s")
            + ")? They download again the next time they're needed."
        confirmRemove.open()
    }

    ModelTermsDialog {
        id: termsDialog
        property string pendingId: ""
        onAccepted: modelsController.downloadAsset(termsDialog.pendingId)
    }

    AppDialog {
        id: confirmRemove
        property var ids: []
        property string message: ""
        title: "Remove downloaded models?"
        standardButtons: Dialog.Yes | Dialog.Cancel
        Text {
            width: 360
            textFormat: Text.PlainText
            text: confirmRemove.message
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
        }
        onAccepted: confirmRemove.ids.forEach(id => modelsController.removeAsset(id))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: bannerRow.implicitHeight + 2 * Theme.spaceMd
            visible: banner.text.length > 0
            color: Theme.dangerSoft

            RowLayout {
                id: bannerRow
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                anchors.leftMargin: Theme.spaceXl
                Icon { name: "error"; color: Theme.danger }
                Text {
                    id: banner
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    color: Theme.danger
                    Accessible.role: Accessible.AlertMessage
                    Accessible.name: text
                }
                AppButton {
                    kind: "ghost"
                    compact: true
                    iconName: "cancel"
                    toolTipText: "Dismiss"
                    onClicked: banner.text = ""
                }
            }
        }

        TabBar {
            id: tabBar
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spaceLg
            Layout.topMargin: Theme.spaceSm
            background: Item {}
            Repeater {
                model: manageWin.categories
                delegate: TabButton {
                    required property var modelData
                    text: modelData.label
                    width: implicitWidth + 24
                    font.pixelSize: Theme.fontBody
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            Repeater {
                model: manageWin.categories

                // A Flickable rather than a ScrollView, so the rows' width never depends on
                // whether the scroll bar shows.
                delegate: Flickable {
                    id: tabPage
                    required property var modelData
                    contentWidth: width
                    contentHeight: tabColumn.implicitHeight + 2 * Theme.spaceLg
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    FocusScroll { flickable: tabPage }

                    // Capped in a wide window, so a row's name and its button stay close.
                    ColumnLayout {
                        id: tabColumn
                        x: Theme.spaceXl
                        y: Theme.spaceLg
                        width: Math.min(tabPage.width - 2 * Theme.spaceXl, 960)
                        spacing: Theme.spaceLg

                        Text {
                            Layout.fillWidth: true
                            textFormat: Text.PlainText
                            text: tabPage.modelData.hint
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                        }

                        Repeater {
                            model: modelsController.groups(tabPage.modelData.key)
                            delegate: GroupCard {}
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.spaceMd
            Layout.leftMargin: Theme.spaceXl
            Layout.rightMargin: Theme.spaceLg
            spacing: Theme.spaceSm

            Icon { name: "library"; color: Theme.textMuted }
            Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: "Disk space used by models: " + modelsController.usedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
                elide: Text.ElideRight
            }
            AppButton {
                kind: "danger"
                text: "Free up space"
                iconName: "delete"
                toolTipText: "Remove every downloaded model"
                enabled: modelsController.downloadedIds.length > 0
                onClicked: manageWin.askRemove(modelsController.downloadedIds, "every downloaded model")
            }
            AppButton {
                kind: "primary"
                text: "Close"
                toolTipText: "Downloads keep running after this window closes"
                onClicked: manageWin.close()
            }
        }
    }

    // One group of a tab (an engine, as the app's pickers name it) with its models.
    component GroupCard: Card {
        id: group
        required property string engine
        required property var rows
        required property int total
        required property int downloadedCount
        required property var downloadIds
        required property var removeIds

        Layout.fillWidth: true
        title: group.engine
        description: group.downloadedCount + " of " + group.total + " downloaded"
        trailing: [
            AppButton {
                compact: true
                text: "Download all"
                iconName: "download"
                toolTipText: "Download every " + group.engine + " model not on this computer yet"
                enabled: group.downloadIds.length > 0
                onClicked: group.downloadIds.forEach(id => manageWin.requestDownload(id))
            },
            AppButton {
                compact: true
                kind: "danger"
                text: "Remove all"
                toolTipText: "Delete every downloaded " + group.engine + " model to free disk space"
                enabled: group.removeIds.length > 0
                onClicked: manageWin.askRemove(group.removeIds, "all " + group.engine + " models")
            }
        ]

        Repeater {
            model: group.rows
            delegate: AssetRow {}
        }
    }

    // One model: its name, size, download progress, and one button whose action follows the
    // download state, so keyboard focus stays on it as the download starts, ends, or fails.
    component AssetRow: Rectangle {
        id: row
        required property int index
        required property string assetId
        required property string label
        required property string name
        required property bool downloaded
        required property string downloadState
        required property string sizeText
        required property real fraction
        required property bool indeterminate
        required property string progressText
        required property string error

        readonly property bool running: row.downloadState === "queued" || row.downloadState === "downloading"
        readonly property bool failed: row.downloadState === "failed"
        readonly property string stateText: row.running ? row.progressText
            : row.downloaded ? "downloaded"
            : row.failed ? "download failed"
            : "not downloaded"

        Layout.fillWidth: true
        implicitHeight: Math.max(52, rowColumn.implicitHeight + 2 * Theme.spaceSm)
        radius: Theme.radius
        color: row.index % 2 === 0 ? Theme.surfaceAlt : "transparent"

        Accessible.role: Accessible.ListItem
        Accessible.name: row.label + ", " + row.stateText + (row.sizeText ? ", " + row.sizeText : "")

        onDownloadStateChanged: {
            if (row.failed)
                row.Accessible.announce(manageWin.sentence(row.name) + " couldn't be downloaded. " + row.error)
        }
        onDownloadedChanged: {
            if (row.downloaded)
                row.Accessible.announce(manageWin.sentence(row.name) + " is downloaded.")
        }

        ColumnLayout {
            id: rowColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceSm
            spacing: Theme.spaceXs

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceMd

                Icon {
                    name: row.downloaded ? "completed" : row.failed ? "error" : "download"
                    color: row.downloaded ? Theme.success : row.failed ? Theme.danger : Theme.textMuted
                }
                Text {
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: row.label
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                    color: Theme.text
                    elide: Text.ElideRight
                    Accessible.ignored: true
                }
                Text {
                    Layout.preferredWidth: 96
                    horizontalAlignment: Text.AlignRight
                    textFormat: Text.PlainText
                    text: row.sizeText || "-"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                    Accessible.ignored: true
                }

                RowLayout {
                    // Its own width, not the row's spare room (the progress bar fills only this).
                    Layout.fillWidth: false
                    Layout.preferredWidth: 240
                    visible: row.running
                    spacing: Theme.spaceSm
                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: 1
                        value: row.fraction
                        indeterminate: row.indeterminate
                        Accessible.name: row.label + " download, " + row.progressText
                    }
                    Text {
                        Layout.preferredWidth: 112
                        textFormat: Text.PlainText
                        text: row.progressText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: Theme.textMuted
                        elide: Text.ElideRight
                        Accessible.ignored: true
                    }
                }

                AppButton {
                    compact: true
                    kind: !row.running && row.downloaded ? "danger" : "secondary"
                    text: row.running ? "Cancel" : row.downloaded ? "Remove" : row.failed ? "Try again" : "Download"
                    iconName: row.running ? "cancel" : row.downloaded ? "" : row.failed ? "refresh" : "download"
                    toolTipText: row.running ? "Stop this download"
                        : row.downloaded ? "Delete from this computer; it downloads again the next time it is needed"
                        : row.failed ? "Download it again"
                        : "Download once; works offline afterwards"
                    Accessible.name: text + " " + row.name
                    onClicked: {
                        if (row.running) modelsController.cancelAsset(row.assetId)
                        else if (row.downloaded) modelsController.removeAsset(row.assetId)
                        else manageWin.requestDownload(row.assetId)
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.iconLg + Theme.spaceMd
                visible: row.failed
                textFormat: Text.PlainText
                text: row.error
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.danger
                wrapMode: Text.WordWrap
            }
        }
    }
}
