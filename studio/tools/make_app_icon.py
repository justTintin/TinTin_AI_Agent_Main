"""
应用图标生成器 · 螺丝钉-电商智能体矩阵

设计概念（Aurora Icon）：
  - 圆角方形 · 深空渐变底（与暗色主题 #0b0c10 系一致）
  - 中心：螺丝钉头（Indigo→Violet 渐变 + 白色十字槽）＝ 品牌「螺丝钉」
  - 四周：矩阵节点环 + 连接线 + 轨道虚线 ＝ 「智能体矩阵」
  - 星光点缀 ＝ AI

输出：
  studio/assets/app_icon.png      （512，窗口/托盘）
  studio/assets/app_icon.ico      （16~256 多尺寸，PyInstaller exe 图标）
  studio/assets/icons/icon_16~256.png

用法：
  python studio/tools/make_app_icon.py
"""
import math
import os

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

SIZE = 512
OUT_PNG = os.path.join(os.path.dirname(__file__), "..", "assets", "app_icon.png")
OUT_ICO = os.path.join(os.path.dirname(__file__), "..", "assets", "app_icon.ico")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
ICON_SIZES = [16, 32, 48, 64, 128, 256]


def _star_points(cx, cy, outer, inner, n=4, rotation=-math.pi / 2):
    """生成 n 角星的顶点序列。"""
    pts = []
    for i in range(n * 2):
        radius = outer if i % 2 == 0 else inner
        angle = rotation + math.pi * i / n
        pts.append(QPointF(cx + radius * math.cos(angle),
                          cy + radius * math.sin(angle)))
    return pts


def draw_icon(painter: QPainter):
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    margin = 10
    rect = QRectF(margin, margin, SIZE - margin * 2, SIZE - margin * 2)
    radius = 104

    # ── 圆角方形底：深空渐变 ──
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
    bg.setColorAt(0.0, QColor("#171b28"))
    bg.setColorAt(0.55, QColor("#11131d"))
    bg.setColorAt(1.0, QColor("#0b0d15"))
    painter.fillPath(path, QBrush(bg))

    # 顶部微光
    sheen = QRadialGradient(QPointF(170, 120), 300)
    sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, QBrush(sheen))

    # 描边
    painter.setPen(QPen(QColor("#2e3448"), 3))
    painter.drawPath(path)

    cx, cy = SIZE / 2, SIZE / 2

    # ── 矩阵：8 节点轨道 + 连接线 ──
    orbit = 166
    nodes = []
    for i in range(8):
        angle = -math.pi / 2 + math.pi * i / 4
        nodes.append((cx + orbit * math.cos(angle), cy + orbit * math.sin(angle)))

    # 轨道虚线环
    painter.setPen(QPen(QColor(129, 140, 248, 42), 3, Qt.DashLine))
    painter.drawEllipse(QPointF(cx, cy), orbit, orbit)

    # 螺丝头 → 节点的连接线
    head_edge = 126
    painter.setPen(QPen(QColor(129, 140, 248, 74), 4, Qt.SolidLine,
                        Qt.RoundCap))
    for nx, ny in nodes:
        dx, dy = nx - cx, ny - cy
        dist = math.hypot(dx, dy)
        painter.drawLine(QPointF(cx + dx / dist * head_edge,
                                 cy + dy / dist * head_edge),
                         QPointF(nx, ny))

    # 节点圆点（带光晕）
    for nx, ny in nodes:
        g = QRadialGradient(QPointF(nx, ny), 22)
        g.setColorAt(0.0, QColor(150, 160, 235, 150))
        g.setColorAt(1.0, QColor(150, 160, 235, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(g))
        painter.drawEllipse(QPointF(nx, ny), 22, 22)
        painter.setBrush(QColor("#a5ade8"))
        painter.drawEllipse(QPointF(nx, ny), 8.5, 8.5)

    # ── 中心螺丝钉头 ──
    head_r = 118

    # 底部阴影（立体感）
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 105))
    painter.drawEllipse(QPointF(cx, cy + 10), head_r + 4, head_r + 4)

    # 头部光晕
    halo = QRadialGradient(QPointF(cx, cy), head_r + 42)
    halo.setColorAt(0.0, QColor(129, 140, 248, 105))
    halo.setColorAt(1.0, QColor(129, 140, 248, 0))
    painter.setBrush(QBrush(halo))
    painter.drawEllipse(QPointF(cx, cy), head_r + 42, head_r + 42)

    # 头部主体（左上受光）
    head = QRadialGradient(QPointF(cx - 46, cy - 54), head_r + 30)
    head.setColorAt(0.0, QColor("#8f8cff"))
    head.setColorAt(0.5, QColor("#6c66f0"))
    head.setColorAt(1.0, QColor("#4f46d6"))
    painter.setBrush(QBrush(head))
    painter.drawEllipse(QPointF(cx, cy), head_r, head_r)

    # 头部内侧细描边
    painter.setPen(QPen(QColor(255, 255, 255, 38), 4))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), head_r - 3, head_r - 3)

    # ── 白色十字槽（螺丝刀槽） ──
    slot_len = 172
    slot_w = 34
    slot = QPainterPath()
    slot.addRoundedRect(QRectF(cx - slot_w / 2, cy - slot_len / 2,
                               slot_w, slot_len), slot_w / 2, slot_w / 2)
    slot.addRoundedRect(QRectF(cx - slot_len / 2, cy - slot_w / 2,
                               slot_len, slot_w), slot_w / 2, slot_w / 2)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 90))
    painter.save()
    painter.translate(0, 5)
    painter.drawPath(slot)
    painter.restore()

    painter.setBrush(QColor("#f6f7ff"))
    painter.drawPath(slot)

    # 十字中心小圆角（槽口交汇处的柔和感）
    painter.setBrush(QColor("#e9ebff"))
    painter.drawEllipse(QPointF(cx, cy), 13, 13)

    # ── AI 星光点缀 ──
    star1 = QPainterPath()
    star1.addPolygon(_star_points(424, 92, 26, 10))
    star1.closeSubpath()
    painter.setBrush(QColor("#cfd3ff"))
    painter.drawPath(star1)

    star2 = QPainterPath()
    star2.addPolygon(_star_points(104, 404, 17, 6.5))
    star2.closeSubpath()
    painter.setBrush(QColor("#b9c0ff"))
    painter.drawPath(star2)

    star3 = QPainterPath()
    star3.addPolygon(_star_points(446, 336, 10, 4))
    star3.closeSubpath()
    painter.setBrush(QColor(207, 211, 255, 190))
    painter.drawPath(star3)


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(size / SIZE, size / SIZE)
    draw_icon(p)
    p.end()
    return img


def qimage_to_pil(img: QImage) -> Image.Image:
    """QImage(ARGB32, 小端 BGRA 内存) → PIL RGBA。"""
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    raw = img.constBits()
    data = raw.tobytes()[: h * bpl] if hasattr(raw, "tobytes") else bytes(raw)
    return Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", bpl, 1)


def main():
    out_png = os.path.normpath(OUT_PNG)
    out_ico = os.path.normpath(OUT_ICO)
    out_dir = os.path.normpath(OUT_DIR)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    by_size = {}
    for s in [SIZE] + ICON_SIZES:
        pil = qimage_to_pil(render(s))
        by_size[s] = pil
        path = os.path.join(out_dir, f"icon_{s}.png") if s != SIZE else out_png
        pil.save(path)
        print(f"  {s:4d}px -> {path}")

    # .ico：多尺寸 PNG 内嵌（Vista+ 支持）
    by_size[256].save(
        out_ico, format="ICO",
        append_images=[by_size[s] for s in ICON_SIZES if s != 256],
        sizes=[(s, s) for s in ICON_SIZES],
    )
    print(f"  ico  -> {out_ico}")
    print("DONE")


if __name__ == "__main__":
    main()
