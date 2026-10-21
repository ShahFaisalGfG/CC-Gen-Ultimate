"""Draw every CC-Gen-Ultimate icon from code: the window, taskbar and About sizes, the splash logo, the
readme logo, and CCGenUltimate.ico for the exe, the installers, and the Explorer menu.

gfgLock and CC-Gen-Ultimate share one icon family: a rounded tile with a diagonal gradient and a
bold white symbol, no text, so the icon stays recognisable at 16 px. Each app has its own colours and
symbol; gfgLock's scripts/make_icons.py draws the same tile.

Run from the repository root:  python scripts/make_icons.py
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QImageWriter, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402

ICON_DIR = os.path.join("ccgen", "assets", "icons")
TOP, BOTTOM = "#ec5aa6", "#6b5cf0"  # pink to violet, as in the earlier outline logo
PNGS = {
    "Square44x44Logo.targetsize-16.png": 16,
    "Square44x44Logo.targetsize-20.png": 20,
    "Square44x44Logo.targetsize-24.png": 24,
    "Square44x44Logo.targetsize-32.png": 32,
    "Square44x44Logo.targetsize-48.png": 48,
    "Square44x44Logo.targetsize-256.png": 256,
    "Square71x71Logo.scale-100.png": 71,
    "Square150x150Logo.scale-100.png": 150,
    "Square310x310Logo.scale-100.png": 310,
    "StoreLogo.scale-150.png": 150,
}
ICO_NAME = "CCGenUltimate.ico"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def draw_tile(p: QPainter, size: float, top: str, bottom: str) -> None:
    """The shared shape: a rounded square with a diagonal gradient and a thin transparent margin."""
    grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    grad.setColorAt(0, QColor(top))
    grad.setColorAt(1, QColor(bottom))
    inset = size * 0.04
    path = QPainterPath()
    path.addRoundedRect(QRectF(inset, inset, size - 2 * inset, size - 2 * inset), size * 0.22, size * 0.22)
    p.fillPath(path, grad)


def draw_captions(p: QPainter, s: float) -> None:
    """Two bold white C's, the closed-captions mark, drawn as round-capped arcs (no font needed)."""
    p.setPen(QPen(QColor("white"), s * 0.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    radius = s * 0.125
    for centre_x in (s * 0.33, s * 0.67):
        box = QRectF(centre_x - radius, s * 0.5 - radius, 2 * radius, 2 * radius)
        p.drawArc(box, 50 * 16, 260 * 16)  # opens to the right, like a C


def render(size: int) -> QImage:
    """The icon at one exact size, drawn as vectors so small sizes stay sharp."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_tile(p, size, TOP, BOTTOM)
    draw_captions(p, size)
    p.end()
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    QImageWriter(buffer, QByteArray(b"png")).write(img)
    buffer.close()
    return bytes(data.data())


def write_ico(path: str, sizes: tuple[int, ...]) -> None:
    """A Windows .ico with one PNG-compressed image per size (supported since Windows Vista)."""
    images = [png_bytes(render(size)) for size in sizes]
    offset = 6 + 16 * len(sizes)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    for size, data in zip(sizes, images):
        dim = 0 if size >= 256 else size  # 0 means 256 in the directory entry
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(header + entries + b"".join(images))


def main() -> None:
    QGuiApplication(sys.argv[:1])
    for name, size in PNGS.items():
        render(size).save(os.path.join(ICON_DIR, name))  # PNG, from the file name
    write_ico(os.path.join(ICON_DIR, ICO_NAME), ICO_SIZES)
    print(f"Wrote {len(PNGS)} PNGs and {ICO_NAME} to {ICON_DIR}")


if __name__ == "__main__":
    main()
