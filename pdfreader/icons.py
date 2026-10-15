"""Inline SVG icon set (24x24, stroke based) tinted for the current theme."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1"/><path d="M3 7v11a1 1 0 0 0 1 1h14.5a1 1 0 0 0 1-.8L21.5 11H7.4a1 1 0 0 0-1 .8L4.2 19"/>',
    "save": '<path d="M5 3h11l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8 3v5h7V3"/><rect x="7" y="13" width="10" height="8"/>',
    "print": '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="1.5"/><path d="M7 14h10v7H7z"/><circle cx="17.5" cy="12" r=".6" fill="currentColor"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/>',
    "prev": '<path d="m6 15 6-6 6 6"/>',
    "next": '<path d="m6 9 6 6 6-6"/>',
    "left": '<path d="m15 6-6 6 6 6"/>',
    "right": '<path d="m9 6 6 6-6 6"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21M10.5 7.5v6M7.5 10.5h6"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21M7.5 10.5h6"/>',
    "fit_width": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M7 12h10M9 9.5 6.5 12 9 14.5M15 9.5l2.5 2.5-2.5 2.5"/>',
    "fit_page": '<rect x="6" y="3" width="12" height="18" rx="1.5"/><path d="M12 7v10M9.5 9 12 6.5 14.5 9M9.5 15l2.5 2.5 2.5-2.5"/>',
    "select": '<path d="M5 3.5 18.5 12l-6.2 1.3L9 19.5z"/>',
    "text_select": '<path d="M9 4h6M9 20h6M12 4v16"/>',
    "hand": '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11.5V4a1.5 1.5 0 0 1 3 0v7.5M14 11.5V6a1.5 1.5 0 0 1 3 0v8a7 7 0 0 1-7 7h-.6a6 6 0 0 1-4.6-2.2L2.9 14.6a1.6 1.6 0 0 1 2.4-2l2.7 2.4"/>',
    "rotate_cw": '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v5h-5"/>',
    "rotate_ccw": '<path d="M4 12a8 8 0 1 0 2.6-5.9"/><path d="M4 4v5h5"/>',
    "highlight": '<path d="m9 11-5 5v4h4l5-5"/><path d="m9 11 6.5-6.5a2.1 2.1 0 0 1 3 3L13 14z"/><path d="M14 21h7" stroke-width="3" stroke="#F8D21C"/>',
    "underline": '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 20h14"/>',
    "strikeout": '<path d="M16 6.5C15 5 13.6 4 12 4c-2.5 0-4.3 1.4-4.3 3.4 0 1.3.8 2.3 2.3 3"/><path d="M4 12h16"/><path d="M8 17c1 1.8 2.4 3 4.3 3 2.6 0 4.4-1.5 4.4-3.5 0-.9-.3-1.6-.9-2.2"/>',
    "note": '<path d="M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-6l-5 4v-4H6a2 2 0 0 1-2-2z"/><path d="M8 8h8M8 12h5"/>',
    "textbox": '<rect x="3" y="4" width="18" height="16" rx="1.5" stroke-dasharray="2 2"/><path d="M8 8h8M12 8v9"/>',
    "ink": '<path d="M3 18c3-1 4-6 6-6s2 6 5 6 4-9 7-9"/>',
    "rect": '<rect x="4" y="5" width="16" height="14" rx="1"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>',
    "eraser": '<path d="m7 21-4.3-4.3a1.5 1.5 0 0 1 0-2.1l10-10a1.5 1.5 0 0 1 2.1 0l5.6 5.6a1.5 1.5 0 0 1 0 2.1L13 21z"/><path d="M22 21H7M5 12l7 7"/>',
    "thumbs": '<rect x="4" y="3" width="6.5" height="8" rx="1"/><rect x="13.5" y="3" width="6.5" height="8" rx="1"/><rect x="4" y="13" width="6.5" height="8" rx="1"/><rect x="13.5" y="13" width="6.5" height="8" rx="1"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4.5L6 21z"/>',
    "comments": '<path d="M21 12a8 8 0 0 1-11.8 7L4 20.5 5.4 16A8 8 0 1 1 21 12z"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M9 4v16"/>',
    "fullscreen": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "read_mode": '<path d="M2 6.5C5 5 8.5 5 12 7c3.5-2 7-2 10-.5V19c-3-1.5-6.5-1.5-10 .5-3.5-2-7-2-10-.5z"/><path d="M12 7v12.5"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "page_single": '<rect x="7" y="3" width="10" height="18" rx="1"/>',
    "page_cont": '<rect x="7" y="2" width="10" height="9" rx="1"/><rect x="7" y="13" width="10" height="9" rx="1"/>',
    "page_two": '<rect x="2.5" y="5" width="9" height="14" rx="1"/><rect x="12.5" y="5" width="9" height="14" rx="1"/>',
    "page_two_cont": '<rect x="2.5" y="2" width="9" height="9" rx="1"/><rect x="12.5" y="2" width="9" height="9" rx="1"/><rect x="2.5" y="13" width="9" height="9" rx="1"/><rect x="12.5" y="13" width="9" height="9" rx="1"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "extract": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M12 11v7M9 15l3 3 3-3"/>',
    "insert": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M12 11v7M9 14h6"/>',
    "merge": '<rect x="3" y="3" width="8" height="11" rx="1"/><rect x="13" y="10" width="8" height="11" rx="1"/><path d="M11 8.5h4.5V10M13 15.5H8.5V14"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r=".7" fill="currentColor"/>',
    "home": '<path d="m3 11 9-8 9 8"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
    "file_pdf": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/><path d="M8.5 17.5c2-3 3.5-6.5 3.5-9 0-1-1-1-1 0 0 3 3 6 5.5 7.5 1 .6.4 1.5-.7 1-2-.8-4.8-.6-7.3.5"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "back": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "forward": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="1.5"/><path d="M16 8V4.5A1.5 1.5 0 0 0 14.5 3h-10A1.5 1.5 0 0 0 3 4.5v10A1.5 1.5 0 0 0 4.5 16H8"/>',
    "autoscroll": '<path d="M12 3v18M7 16l5 5 5-5M7 8l5-5 5 5"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.8 1.8-1.7 0-1.3-1.3-1.6-1.3-2.8 0-.9.7-1.5 1.6-1.5H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="14.5" cy="7" r="1"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "word": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/><path d="M8 12l1.5 6 2.5-5 2.5 5L16 12"/>',
    "convert": '<path d="M4 8h13l-3.5-3.5M20 16H7l3.5 3.5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 1.2 14H1a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 7 2.6 1.7 1.7 0 0 0 8 1.1V1a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 19.4 9"/>',
}

_cache: dict[tuple, QIcon] = {}
_color = QColor("#3b3b3b")
_active_color = QColor("#1473e6")


def set_icon_color(normal: str, active: str = "#1473e6"):
    global _color, _active_color
    _color = QColor(normal)
    _active_color = QColor(active)
    _cache.clear()


def _render(name: str, color: QColor, size: int = 48) -> QPixmap:
    body = _P[name]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color.name()}" color="{color.name()}" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return QPixmap.fromImage(img)


def icon(name: str, color: str | None = None) -> QIcon:
    key = (name, color, _color.name())
    ic = _cache.get(key)
    if ic is None:
        ic = QIcon()
        c = QColor(color) if color else _color
        ic.addPixmap(_render(name, c), QIcon.Mode.Normal, QIcon.State.Off)
        on = c if color else _active_color
        ic.addPixmap(_render(name, on), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(_render(name, c), QIcon.Mode.Selected, QIcon.State.Off)
        dis = QColor(c)
        dis.setAlpha(90)
        ic.addPixmap(_render(name, dis), QIcon.Mode.Disabled, QIcon.State.Off)
        _cache[key] = ic
    return ic


def color_swatch(color: QColor, size: QSize = QSize(16, 16)) -> QIcon:
    pm = QPixmap(size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(color)
    p.setPen(QColor(0, 0, 0, 80))
    p.drawEllipse(2, 2, pm.width() - 4, pm.height() - 4)
    p.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    """The application icon: a red Acrobat-like document badge."""
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(app_icon_pixmap(s))
    return ic


def app_icon_pixmap(s: int) -> QPixmap:
    """Red rounded badge with a white document sheet and a "PDF" label."""
    from PySide6.QtGui import QBrush, QFont, QLinearGradient, QPainterPath

    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0, QColor("#ef4136"))
    grad.setColorAt(1, QColor("#c1121f"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(r, s * 0.2, s * 0.2)
    # document sheet with a folded corner
    x0, y0, x1, y1 = s * 0.27, s * 0.17, s * 0.73, s * 0.83
    fold = s * 0.13
    sheet = QPainterPath()
    sheet.moveTo(x0, y0)
    sheet.lineTo(x1 - fold, y0)
    sheet.lineTo(x1, y0 + fold)
    sheet.lineTo(x1, y1)
    sheet.lineTo(x0, y1)
    sheet.closeSubpath()
    p.setBrush(QColor("white"))
    p.drawPath(sheet)
    corner = QPainterPath()
    corner.moveTo(x1 - fold, y0)
    corner.lineTo(x1 - fold, y0 + fold)
    corner.lineTo(x1, y0 + fold)
    corner.closeSubpath()
    p.setBrush(QColor("#f6b9bd"))
    p.drawPath(corner)
    if s >= 24:
        # text lines
        p.setBrush(QColor("#e7a0a5"))
        for k in range(2):
            ly = y0 + s * (0.2 + k * 0.08)
            p.drawRoundedRect(QRectF(x0 + s * 0.07, ly, (x1 - x0) - s * 0.14, s * 0.035), s * 0.015, s * 0.015)
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(max(6, int(s * 0.17)))
        p.setFont(f)
        p.setPen(QColor("#c1121f"))
        p.drawText(QRectF(x0, y1 - s * 0.3, x1 - x0, s * 0.24), Qt.AlignmentFlag.AlignCenter, "PDF")
    p.end()
    return pm
