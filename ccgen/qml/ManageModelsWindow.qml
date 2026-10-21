// qmllint disable unqualified
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

AppWindow {
    id: manageWin

    width: 860
    height: 700
    minimumWidth: 680
    minimumHeight: 520
    title: "Manage Models"
    modality: Qt.ApplicationModal

    // Per-asset-id live download state (queued/downloading + progress), kept outside the flat
    // catalog snapshot so a refresh triggered by ONE finished download doesn't wipe the
    // "Queued" indicator off every OTHER item still waiting in the backend's FIFO queue.
    property var pendingState: ({})
    // Flat, merged (catalog + pendingState) snapshot rebuilt on every relevant event; every
    // tab/engine-group view below is a filtered read of this one list.
    property var catalog: []
    property real totalBytes: 0

    readonly property var categories: [
        { key: "whisper", label: "Transcription", hint: "Whisper speech recognition models. Larger models are more accurate and slower." },
        { key: "translation", label: "Translation", hint: "Offline translation models, grouped by the model chosen under Preferences > Translation. OPUS-MT and Argos have one model per direction, with English bridging other pairs; NLLB and MADLAD cover every pair. The meaning check compares each translation with the original." },
        { key: "transliteration", label: "Transliteration", hint: "Optional neural models for more natural script conversion. The rule-based engine needs no download." },
        { key: "voices", label: "Voices", hint: "Dubbing voices. XTTS-v2 clones the original speakers; Kokoro and Piper are ready-made voices. Each downloads once." }
    ]

    Component.onCompleted: rebuild()
    onClosing: manageWin.destroy()

    Shortcut { sequence: "Escape"; onActivated: manageWin.close() }

    Connections {
        target: modelsController
        function onAssetsChanged() { manageWin.rebuild() }
        function onAssetQueued(id) {
            manageWin.pendingState[id] = { downloadState: "queued", progressDone: 0, progressTotal: 0, statusMessage: "" }
            manageWin.rebuild()
        }
        function onAssetStatus(id, message) {
            // A status message proves the worker started this asset even when no byte
            // progress arrives (some download paths report late or not at all).
            var pending = manageWin.pendingState[id]
            if (pending) {
                pending.statusMessage = message
                pending.downloadState = "downloading"
            }
            manageWin.rebuild()
        }
        function onAssetProgress(id, done, total) {
            manageWin.pendingState[id] = { downloadState: "downloading", progressDone: done, progressTotal: total, statusMessage: "" }
            manageWin.rebuild()
        }
        function onAssetFinished(id, success, error) {
            delete manageWin.pendingState[id]
            if (!success && error !== "Cancelled")
                banner.text = "Download failed: " + error
            manageWin.rebuild()
        }
        function onRemoveFailed(id, error) {
            banner.text = "Couldn't remove a model: " + error
        }
    }

    function rebuild() {
        var list = modelsController.assets
        var rows = []
        var total = 0
        for (var i = 0; i < list.length; i++) {
            var a = list[i]
            var pending = manageWin.pendingState[a.id]
            rows.push({
                id: a.id, category: a.category, engine: a.engine, label: a.label,
                downloaded: a.downloaded, sizeBytes: a.size_bytes || 0,
                approxSizeMb: a.approx_size_mb || 0,
                downloadState: pending ? pending.downloadState : "idle",
                progressDone: pending ? pending.progressDone : 0,
                progressTotal: pending ? pending.progressTotal : 0,
                statusMessage: pending ? pending.statusMessage : ""
            })
            if (a.downloaded) total += a.size_bytes || 0
        }
        manageWin.catalog = rows
        manageWin.totalBytes = total
    }

    function rowsFor(category, engine) {
        return manageWin.catalog.filter(r => r.category === category && r.engine === engine)
    }

    function enginesIn(category) {
        var seen = []
        for (var i = 0; i < manageWin.catalog.length; i++) {
            var r = manageWin.catalog[i]
            if (r.category === category && seen.indexOf(r.engine) < 0) seen.push(r.engine)
        }
        return seen
    }

    function downloadAllInGroup(category, engine) {
        manageWin.rowsFor(category, engine).forEach(function(row) {
            if (!row.downloaded && row.downloadState === "idle") manageWin.requestDownload(row.id)
        })
    }

    // Models licensed for non-commercial use only ask for their licence once before the
    // first download: OmniVoice and XTTS-v2 voice cloning, and the NLLB-200 translation model.
    readonly property var licensedModels: ({
        "voices:omnivoice": "omnivoice",
        "voices:xtts": "xtts",
        "translation:nllb-1.3b": "nllb"
    })

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

    ModelTermsDialog {
        id: termsDialog
        property string pendingId: ""
        onAccepted: modelsController.downloadAsset(termsDialog.pendingId)
    }

    function cancelDownload(id) {
        modelsController.cancelAsset(id)
        delete manageWin.pendingState[id]
        manageWin.rebuild()
    }

    function formatBytes(bytes) {
        if (!bytes || bytes <= 0) return "-"
        var units = ["B", "KB", "MB", "GB"]
        var value = bytes
        var unit = 0
        while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++ }
        return value.toFixed(value >= 10 || unit === 0 ? 0 : 1) + " " + units[unit]
    }

    // Remove-confirmation for bulk actions: `ids` are removed when the user confirms.
    AppDialog {
        id: confirmRemove
        property var ids: []
        property string message: ""
        title: "Remove downloaded models?"
        standardButtons: Dialog.Yes | Dialog.Cancel
        Text {
            width: 360
            text: confirmRemove.message
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
        }
        onAccepted: confirmRemove.ids.forEach(id => modelsController.removeAsset(id))
    }

    function askRemove(rows, what) {
        var ids = rows.filter(r => r.downloaded).map(r => r.id)
        if (ids.length === 0) return
        confirmRemove.ids = ids
        confirmRemove.message = "Remove " + what + " (" + ids.length + " model" + (ids.length === 1 ? "" : "s")
            + ")? They download again the next time they're needed."
        confirmRemove.open()
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
                    wrapMode: Text.WordWrap
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    color: Theme.danger
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

                delegate: ScrollView {
                    id: tabPage
                    required property var modelData
                    contentWidth: availableWidth
                    contentHeight: tabColumn.implicitHeight + 2 * Theme.spaceLg
                    clip: true

                    ColumnLayout {
                        id: tabColumn
                        x: Theme.spaceXl
                        y: Theme.spaceLg
                        width: tabPage.availableWidth - 2 * Theme.spaceXl
                        spacing: Theme.spaceLg

                        Text {
                            Layout.fillWidth: true
                            text: tabPage.modelData.hint
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                        }

                        Repeater {
                            model: manageWin.enginesIn(tabPage.modelData.key)

                            delegate: Card {
                                id: group
                                required property string modelData
                                readonly property var rows: manageWin.rowsFor(tabPage.modelData.key, group.modelData)
                                readonly property int downloadedCount: group.rows.filter(r => r.downloaded).length

                                Layout.fillWidth: true
                                title: group.modelData
                                description: group.downloadedCount + " of " + group.rows.length + " downloaded"
                                trailing: [
                                    AppButton {
                                        compact: true
                                        text: "Download all"
                                        iconName: "download"
                                        toolTipText: "Download every " + group.modelData + " model not yet on this computer"
                                        enabled: group.downloadedCount < group.rows.length
                                        onClicked: manageWin.downloadAllInGroup(tabPage.modelData.key, group.modelData)
                                    },
                                    AppButton {
                                        compact: true
                                        kind: "danger"
                                        text: "Remove all"
                                        toolTipText: "Delete every downloaded " + group.modelData + " model to free disk space"
                                        enabled: group.downloadedCount > 0
                                        onClicked: manageWin.askRemove(group.rows, "all " + group.modelData + " models")
                                    }
                                ]

                                Repeater {
                                    model: group.rows
                                    delegate: AssetRow {}
                                }
                            }
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
                text: "Disk space used by models: " + manageWin.formatBytes(manageWin.totalBytes)
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
            }
            AppButton {
                kind: "danger"
                text: "Free up space"
                iconName: "delete"
                toolTipText: "Remove every downloaded model"
                enabled: manageWin.totalBytes > 0
                onClicked: manageWin.askRemove(manageWin.catalog, "every downloaded model")
            }
            AppButton {
                kind: "primary"
                text: "Close"
                toolTipText: "Downloads keep running after this window closes"
                onClicked: manageWin.close()
            }
        }
    }

    // One catalog row: name, size, and an action area that matches its download state.
    component AssetRow: Rectangle {
        id: row
        required property var modelData
        required property int index

        readonly property string dlState: row.modelData.downloadState
        readonly property real approxBytes: row.modelData.approxSizeMb * 1024 * 1024
        // The static known size is a stable denominator: a multi-file repo's live total grows as
        // each file starts, which made percentages jump backwards.
        readonly property real totalBytes: row.approxBytes > 0 ? row.approxBytes : row.modelData.progressTotal
        readonly property real fraction: row.totalBytes > 0 ? Math.min(1, row.modelData.progressDone / row.totalBytes) : 0

        Layout.fillWidth: true
        implicitHeight: 52
        radius: Theme.radius
        color: row.index % 2 === 0 ? Theme.surfaceAlt : "transparent"

        Accessible.role: Accessible.ListItem
        Accessible.name: row.modelData.label + ", " + (row.modelData.downloaded ? "downloaded" : row.dlState === "idle" ? "not downloaded" : row.dlState)

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceSm
            spacing: Theme.spaceMd

            Icon {
                name: row.modelData.downloaded ? "completed" : "download"
                color: row.modelData.downloaded ? Theme.success : Theme.textMuted
            }
            Text {
                Layout.fillWidth: true
                text: row.modelData.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: Theme.text
                elide: Text.ElideRight
            }
            Text {
                Layout.preferredWidth: 80
                horizontalAlignment: Text.AlignRight
                text: row.modelData.downloaded ? manageWin.formatBytes(row.modelData.sizeBytes)
                    : (row.approxBytes > 0 ? "about " + manageWin.formatBytes(row.approxBytes) : "-")
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
            }

            // Downloading or queued
            RowLayout {
                Layout.preferredWidth: 240
                visible: row.dlState !== "idle"
                spacing: Theme.spaceSm
                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    value: row.fraction
                    indeterminate: row.dlState === "queued" || row.totalBytes === 0
                    Accessible.name: row.modelData.label + " download progress"
                }
                Text {
                    Layout.preferredWidth: 70
                    text: row.dlState === "queued" ? "Queued" : (row.totalBytes > 0 ? Math.round(row.fraction * 100) + "%" : "Starting")
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                }
                AppButton {
                    kind: "ghost"
                    compact: true
                    iconName: "cancel"
                    toolTipText: "Cancel download of " + row.modelData.label
                    onClicked: manageWin.cancelDownload(row.modelData.id)
                }
            }

            AppButton {
                visible: row.dlState === "idle" && !row.modelData.downloaded
                compact: true
                text: "Download"
                iconName: "download"
                toolTipText: "Download once; works offline afterwards"
                Accessible.name: "Download " + row.modelData.label
                onClicked: manageWin.requestDownload(row.modelData.id)
            }
            AppButton {
                visible: row.dlState === "idle" && row.modelData.downloaded
                compact: true
                kind: "danger"
                text: "Remove"
                toolTipText: "Delete from this computer; it downloads again the next time it is needed"
                Accessible.name: "Remove " + row.modelData.label
                onClicked: modelsController.removeAsset(row.modelData.id)
            }
        }
    }
}
