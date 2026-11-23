import QtQuick

// Keeps the keyboard's focus in sight in a scrolling Flickable: when Tab moves to a control scrolled
// out of view, the Flickable scrolls just enough to show it. Put one in the Flickable (or anywhere in
// its window) and point `flickable` at it; focus outside the Flickable (a menu, another pane) is left
// alone. For a ScrollView, point it at the ScrollView's contentItem.
Item {
    id: follower

    required property Flickable flickable
    property real margin: Theme.spaceLg

    function _show(item) {
        var flick = follower.flickable
        if (!item || !flick.visible || flick.contentHeight <= flick.height)
            return
        var inside = item
        while (inside && inside !== flick.contentItem)
            inside = inside.parent
        if (!inside)
            return
        var top = item.mapToItem(flick.contentItem, 0, 0).y
        var bottom = top + item.height
        if (top - follower.margin < flick.contentY)
            flick.contentY = Math.max(0, top - follower.margin)
        else if (bottom + follower.margin > flick.contentY + flick.height)
            flick.contentY = Math.min(flick.contentHeight - flick.height, bottom + follower.margin - flick.height)
    }

    Connections {
        target: follower.flickable.Window.window
        function onActiveFocusItemChanged() { follower._show(follower.flickable.Window.activeFocusItem) }
    }
}
