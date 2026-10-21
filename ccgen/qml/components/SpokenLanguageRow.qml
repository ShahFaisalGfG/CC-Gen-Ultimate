// qmllint disable unqualified
import QtQuick
import QtQuick.Layouts

// The language spoken in queued videos and audio, which a tab transcribes before its own step.
// Shared by the Translate, Transliterate, and Dub tabs; "" detects it from the speech.
FormRow {
    id: row

    property string value: ""
    signal changed(string value)

    label: "Spoken language"
    hint: "For videos and audio, which are transcribed first. Subtitles use the language shown in the queue."

    StyledComboBox {
        Layout.fillWidth: true
        accessibleName: "Spoken language"
        toolTipText: "Language spoken in the videos and audio files. Auto-detect works it out from the speech."
        model: prefsController.languageOptions
        value: row.value
        onActivated: row.changed(currentValue)
    }
}
