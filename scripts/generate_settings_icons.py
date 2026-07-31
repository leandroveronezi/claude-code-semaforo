"""Gera os ícones usados no QSS da tela de configurações (checkbox e setas de
spinbox). Motivo de existirem como arquivo em vez de data URI embutida no QSS:
o parser de stylesheet do Qt não carrega `url(data:image/svg+xml;base64,...)`
de forma confiável para as sub-controls `::indicator`/`::up-arrow`/`::down-arrow`
— só funciona apontando pra um arquivo real. Rode este script sempre que quiser
ajustar espessura/cor/tamanho dos ícones; não edite os PNGs à mão."""
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

SCALE = 4  # renderiza em resolução maior e deixa o Qt reamostrar ao exibir (fica nítido em telas HiDPI)


def _blank_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size * SCALE, size * SCALE)
    pix.fill(Qt.GlobalColor.transparent)
    return pix


def _painter(pix: QPixmap, color: str, width: float) -> QPainter:
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(width * SCALE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    return p


def make_check(path: Path) -> None:
    pix = _blank_pixmap(16)
    p = _painter(pix, "white", 2.1)
    s = SCALE
    p.drawPolyline(QPointF(3.5 * s, 8.3 * s), QPointF(6.4 * s, 11.2 * s), QPointF(12.7 * s, 4.3 * s))
    p.end()
    pix.save(str(path))


def make_chevron(path: Path, direction: str) -> None:
    pix = _blank_pixmap(10)
    p = _painter(pix, "#d8d8dc", 1.4)
    s = SCALE
    y_top, y_bottom = (6.2, 3.2) if direction == "up" else (3.2, 6.2)
    p.drawPolyline(QPointF(2.0 * s, y_top * s), QPointF(5.0 * s, y_bottom * s), QPointF(8.0 * s, y_top * s))
    p.end()
    pix.save(str(path))


def make_arrow(path: Path, direction: str) -> None:
    """Seta esquerda/direita maior, usada nos botões circulares do carrossel de personagem."""
    pix = _blank_pixmap(14)
    p = _painter(pix, "#e6e6ea", 2.0)
    s = SCALE
    x_far, x_near = (4.2, 9.2) if direction == "left" else (9.8, 4.8)
    p.drawPolyline(QPointF(x_near * s, 3.2 * s), QPointF(x_far * s, 7.0 * s), QPointF(x_near * s, 10.8 * s))
    p.end()
    pix.save(str(path))


def main() -> None:
    app = QApplication.instance() or QApplication([])
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    make_check(ICONS_DIR / "check.png")
    make_chevron(ICONS_DIR / "chevron_up.png", "up")
    make_chevron(ICONS_DIR / "chevron_down.png", "down")
    make_arrow(ICONS_DIR / "arrow_left.png", "left")
    make_arrow(ICONS_DIR / "arrow_right.png", "right")
    print(f"ícones gerados em {ICONS_DIR}")


if __name__ == "__main__":
    main()
