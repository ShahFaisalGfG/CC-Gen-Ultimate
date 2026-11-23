// qmllint disable unqualified
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

// The Workflow tab's step list: steps run top to bottom on every queued file, and each one
// says which text it uses. Steps can be added, reordered, and removed. The steps are kept for the
// next launch, and a workflow can be saved by name and loaded again (`ccgen workflow --preset`).
ColumnLayout {
    id: editor

    spacing: Theme.spaceLg

    // Saved workflows: load one, save these steps under a name, remove one, or start over.
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceSm

        StyledComboBox {
            id: presetBox
            Layout.fillWidth: true
            Layout.maximumWidth: 320
            accessibleName: "Saved workflows"
            toolTipText: "Load a workflow you saved; it replaces the steps below"
            placeholderText: workflowController.presetNames.length > 0 ? "Load a saved workflow" : "No saved workflows yet"
            enabled: workflowController.presetNames.length > 0
            model: workflowController.presetNames.map(name => ({ label: name, code: name }))
            value: ""
            onActivated: {
                workflowController.loadPreset(currentValue)
                presetBox.currentIndex = -1
            }
        }
        AppButton {
            text: "Save as..."
            iconName: "add"
            toolTipText: "Save these steps under a name, to load again here or run with ccgen workflow --preset"
            enabled: workflowController.steps.count > 0
            onClicked: {
                saveDialog.errorText = ""
                nameField.text = ""
                saveDialog.open()
            }
        }
        AppButton {
            id: moreButton
            kind: "ghost"
            iconName: "more"
            toolTipText: "Remove a saved workflow, or start over"
            onClicked: moreMenu.popup(moreButton, 0, moreButton.height)

            AppMenu {
                id: moreMenu
                AppMenu {
                    title: "Remove a saved workflow"
                    enabled: workflowController.presetNames.length > 0
                    Repeater {
                        model: workflowController.presetNames
                        delegate: AppMenuItem {
                            required property string modelData
                            text: modelData
                            danger: true
                            onTriggered: workflowController.deletePreset(modelData)
                        }
                    }
                }
                AppMenuItem {
                    text: "Start over"
                    onTriggered: workflowController.resetSteps()
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "Steps run in order on every queued file. Each step uses the queued file or the text of an earlier step."
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        color: Theme.textMuted
        wrapMode: Text.WordWrap
    }

    Repeater {
        model: workflowController.steps
        delegate: WorkflowStepCard {
            stepCount: workflowController.steps.count
            onOptionChanged: (key, value) => workflowController.setStepOption(index, key, value)
            onMoveRequested: target => workflowController.moveStep(index, target)
            onRemoveRequested: workflowController.removeStep(index)
        }
    }

    Text {
        Layout.fillWidth: true
        visible: workflowController.steps.count === 0
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: "No steps yet. Add the first one below."
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: Theme.textMuted
    }

    AppButton {
        id: addButton
        kind: "primary"
        text: "Add step"
        iconName: "add"
        toolTipText: "Add a step to the end of the workflow"
        onClicked: addMenu.popup(addButton, 0, addButton.height)

        AppMenu {
            id: addMenu
            Repeater {
                model: workflowController.stepKinds
                delegate: AppMenuItem {
                    required property var modelData
                    text: modelData.label
                    onTriggered: workflowController.addStep(modelData.kind)
                }
            }
        }
    }

    AppDialog {
        id: saveDialog
        property string errorText: ""
        parent: Overlay.overlay
        title: "Save this workflow"
        implicitWidth: Math.min(420, (parent ? parent.width : 420) - 48)
        standardButtons: Dialog.Save | Dialog.Cancel
        defaultButton: Dialog.Save
        onOpened: nameField.selectInput()
        onAccepted: {
            if (!workflowController.savePreset(nameField.text)) {
                saveDialog.errorText = "Type a name of up to 60 characters."
                saveDialog.open()
            }
        }

        StyledTextField {
            id: nameField
            anchors.left: parent.left
            anchors.right: parent.right
            label: "Name"
            placeholderText: "Urdu subtitles and dub"
            helpText: "A workflow with the same name is replaced."
            errorText: saveDialog.errorText
            onAccepted: saveDialog.accept()
        }
    }
}
