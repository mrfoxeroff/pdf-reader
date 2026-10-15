"""Printing through the standard Windows print dialog."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog


def print_document(parent, document, current_page: int):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(document.title)
    n = document.page_count
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("Печать")
    dlg.setMinMax(1, n)
    dlg.setFromTo(1, n)
    dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)
    dlg.setOption(QPrintDialog.PrintDialogOption.PrintCurrentPage, True)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return
    rng = printer.printRange()
    if rng == QPrinter.PrintRange.PageRange:
        pages = list(range(printer.fromPage() - 1, printer.toPage()))
    elif rng == QPrinter.PrintRange.CurrentPage:
        pages = [current_page]
    else:
        pages = list(range(n))
    if not pages:
        return
    copies = 1  # the driver handles copies itself
    dpi = min(300, max(150, printer.resolution()))

    progress = QProgressDialog("Печать…", "Отмена", 0, len(pages), parent)
    progress.setWindowTitle("Печать")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(300)

    painter = QPainter()
    if not painter.begin(printer):
        QMessageBox.warning(parent, "Печать", "Не удалось начать печать.")
        return
    try:
        for k, page in enumerate(pages * copies):
            if progress.wasCanceled():
                printer.abort()
                break
            progress.setValue(k)
            QApplication.processEvents()
            if k:
                printer.newPage()
            with document.lock:
                pix = document.doc[page].get_pixmap(dpi=dpi, annots=True, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            area = QRectF(printer.pageLayout().paintRectPixels(printer.resolution()))
            area.moveTo(0, 0)
            # rotate landscape pages onto portrait paper (and vice versa)
            if (img.width() > img.height()) != (area.width() > area.height()):
                img = img.transformed(QTransform().rotate(90))
            scale = min(area.width() / img.width(), area.height() / img.height())
            w, h = img.width() * scale, img.height() * scale
            target = QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, img)
        progress.setValue(len(pages))
    finally:
        painter.end()
