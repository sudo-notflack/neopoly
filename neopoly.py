#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""neopoly v1.2 — Универсальный визуальный конфигуратор Polybar"""

import sys
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout,
    QHBoxLayout, QPushButton, QFileDialog, QMessageBox,
    QSpinBox, QStatusBar, QSizePolicy, QDialog, QDialogButtonBox,
    QRadioButton, QButtonGroup, QScrollArea, QTabWidget,
    QAction, QPlainTextEdit, QTreeWidget, QTreeWidgetItem,
    QSplitter, QLineEdit, QFormLayout, QFrame, QGroupBox,
    QListWidget, QListWidgetItem, QCheckBox, QComboBox,
    QColorDialog, QInputDialog
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QGuiApplication
)


PALETTE = {
    "base":     "#1e1e2e",
    "mantle":   "#181825",
    "crust":    "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "overlay0": "#6c7086",
    "overlay1": "#7f849c",
    "text":     "#cdd6f4",
    "subtext":  "#a6adc8",
    "blue":     "#89b4fa",
    "green":    "#a6e3a1",
    "teal":     "#94e2d5",
    "yellow":   "#f9e2af",
    "peach":    "#fab387",
    "red":      "#f38ba8",
    "mauve":    "#cba6f7",
    "lavender": "#b4befe",
}


def get_screen_resolution() -> tuple:
    try:
        output = subprocess.check_output(
            ["xrandr", "--current"], stderr=subprocess.DEVNULL
        ).decode()
        match = re.search(r"(\d+)x(\d+)\+0\+0", output)
        if match:
            return int(match.group(1)), int(match.group(2))
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    app = QApplication.instance()
    if app:
        desktop = app.desktop()
        geom = desktop.screenGeometry()
        if geom.width() > 0:
            return geom.width(), geom.height()
    return 1920, 1080


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------

class PolybarConfig:
    RE_BAR_SECTION = re.compile(r"^\[bar/(.+)\]$")
    RE_MOD_SECTION = re.compile(r"^\[module/(.+)\]$")
    RE_VALUE_WITH_UNIT = re.compile(r"^([\d.]+)(%|px)?$")

    def __init__(self, screen_w: int, screen_h: int):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.filepath: Optional[str] = None
        self.bars: dict = {}
        self.modules: dict = {}
        self.colors: dict = {}
        self._raw_lines: list = []
        self._section_lines: dict = {}

    def load(self, filepath: str) -> bool:
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Файл не найден: {filepath}")
        self.filepath = filepath
        self._raw_lines = []
        self.bars = {}
        self.modules = {}
        self.colors = {}
        self._section_lines = {}
        with open(filepath, "r", encoding="utf-8") as f:
            self._raw_lines = f.readlines()
        self._parse()
        return True

    def _parse(self):
        current_section: Optional[str] = None
        current_bar: Optional[str] = None
        current_mod: Optional[str] = None
        bar_data: dict = {}
        mod_data: dict = {}

        for line in self._raw_lines:
            stripped = line.strip()

            if stripped.startswith("[") and stripped.endswith("]"):
                # flush previous bar / module
                if current_bar and self._has_position_data(bar_data):
                    self.bars[current_bar] = self._finalize_bar(bar_data)
                if current_mod is not None:
                    self.modules[current_mod] = dict(mod_data)
                current_bar = None
                current_mod = None
                bar_data = {}
                mod_data = {}

                section_name = stripped[1:-1]
                current_section = section_name
                self._section_lines.setdefault(section_name, []).append(line)

                m = self.RE_BAR_SECTION.match(stripped)
                if m:
                    current_bar = m.group(1)
                    bar_data = {"_name": current_bar}
                else:
                    mm = self.RE_MOD_SECTION.match(stripped)
                    if mm:
                        current_mod = mm.group(1)
                continue

            if current_section:
                self._section_lines.setdefault(current_section, []).append(line)

            if not stripped or stripped.startswith(";") or stripped.startswith("#"):
                continue

            if "=" in stripped:
                key, _, val = stripped.partition("=")
                key = key.strip()
                val = val.strip()
                if current_section == "colors":
                    color = self._extract_color(val)
                    if color:
                        self.colors[key] = color
                elif current_bar is not None:
                    bar_data[key] = val
                elif current_mod is not None:
                    mod_data[key] = val

        # flush last sections
        if current_bar and self._has_position_data(bar_data):
            self.bars[current_bar] = self._finalize_bar(bar_data)
        if current_mod is not None:
            self.modules[current_mod] = dict(mod_data)

    def _has_position_data(self, data: dict) -> bool:
        return any(k in data for k in ("width", "offset-x", "height"))

    def _finalize_bar(self, data: dict) -> dict:
        result = {"_name": data.get("_name", "?")}
        # offset-x
        raw_ox = data.get("offset-x", "0")
        result["offset_x_raw"] = raw_ox
        result["offset_x"] = self._to_px(raw_ox, self.screen_w)
        # offset-y  (NEW: parsed and saved)
        raw_oy = data.get("offset-y", "0")
        result["offset_y_raw"] = raw_oy
        result["offset_y"] = self._to_px(raw_oy, self.screen_h)
        # width
        raw_w = data.get("width", "100%")
        result["width_raw"] = raw_w
        result["width"] = self._to_px(raw_w, self.screen_w)
        # height
        raw_h = data.get("height", "30")
        result["height"] = self._to_px(raw_h, self.screen_h)
        # misc
        result["monitor"] = data.get("monitor", "")
        result["modules_left"]   = data.get("modules-left", "")
        result["modules_center"] = data.get("modules-center", "")
        result["modules_right"]  = data.get("modules-right", "")
        return result

    def _to_px(self, value: str, reference: int) -> int:
        m = self.RE_VALUE_WITH_UNIT.match(value.strip())
        if not m:
            return 0
        num = float(m.group(1))
        unit = m.group(2) or ""
        if unit == "%":
            return int(round(num / 100.0 * reference))
        return int(round(num))

    def _extract_color(self, value: str) -> Optional[str]:
        m = re.search(r"#([0-9A-Fa-f]{3,8})", value)
        return ("#" + m.group(1)) if m else None

    def get_section_text(self, section_name: str) -> str:
        return "".join(self._section_lines.get(section_name, []))

    def get_all_sections(self) -> list:
        return list(self._section_lines.keys())

    def get_raw_text(self) -> str:
        return "".join(self._raw_lines)

    def save(self, filepath: str, save_as_percent: bool = False) -> bool:
        """
        Save config, writing back ALL fields that were changed via the UI
        (offset-x, offset-y, width, height, monitor, modules-*).
        BUG FIX: original only saved offset-x.
        """
        if not self._raw_lines:
            raise ValueError("Нечего сохранять — конфиг не загружен")
        current_bar: Optional[str] = None
        new_lines = []
        for line in self._raw_lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                m = self.RE_BAR_SECTION.match(stripped)
                current_bar = m.group(1) if m else None
                new_lines.append(line)
                continue
            if current_bar and current_bar in self.bars:
                key_part = stripped.split("=")[0].strip() if "=" in stripped else ""
                bar = self.bars[current_bar]
                indent = " " * (len(line) - len(line.lstrip()))

                def pct_or_px(px_val, ref):
                    if save_as_percent:
                        return f"{round(px_val / ref * 100, 2)}%"
                    return str(px_val)

                if key_part == "offset-x":
                    new_lines.append(f"{indent}offset-x = {pct_or_px(bar['offset_x'], self.screen_w)}\n")
                    continue
                elif key_part == "offset-y":
                    new_lines.append(f"{indent}offset-y = {pct_or_px(bar['offset_y'], self.screen_h)}\n")
                    continue
                elif key_part == "width":
                    new_lines.append(f"{indent}width = {pct_or_px(bar['width'], self.screen_w)}\n")
                    continue
                elif key_part == "height":
                    new_lines.append(f"{indent}height = {bar['height']}\n")
                    continue
                elif key_part == "monitor":
                    new_lines.append(f"{indent}monitor = {bar['monitor']}\n")
                    continue
                elif key_part == "modules-left":
                    new_lines.append(f"{indent}modules-left = {bar['modules_left']}\n")
                    continue
                elif key_part == "modules-center":
                    new_lines.append(f"{indent}modules-center = {bar['modules_center']}\n")
                    continue
                elif key_part == "modules-right":
                    new_lines.append(f"{indent}modules-right = {bar['modules_right']}\n")
                    continue
            new_lines.append(line)
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True

    def get_color(self, key: str, fallback: str) -> QColor:
        raw = self.colors.get(key, fallback)
        hex_val = raw.lstrip("#")
        if len(hex_val) == 8:
            alpha = int(hex_val[0:2], 16)
            rgb = hex_val[2:]
            c = QColor(f"#{rgb}")
            c.setAlpha(alpha)
            return c
        return QColor(raw)


# ---------------------------------------------------------------------------
# Draggable bar widget — now supports BOTH X and Y drag
# ---------------------------------------------------------------------------

class DraggableBar(QWidget):
    moved = pyqtSignal(str, int, int)   # name, offset_x, offset_y
    bar_clicked = pyqtSignal(str)

    def __init__(self, name, bar_data, scale, snap_step, min_margin, gap_snap, bg_color, fg_color, parent=None):
        super().__init__(parent)
        self.bar_name = name
        self.bar_data = bar_data
        self.scale = scale
        self.snap_step  = snap_step
        self.min_margin = min_margin
        self.gap_snap   = gap_snap
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.selected = False
        self._drag_active = False
        self._drag_start_mouse: Optional[QPoint] = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setToolTip(
            f"[bar/{name}]  ЛКМ = выбрать\n"
            "Тащи по X и Y для смещения\n"
            "Стрелки = двигать на 1px (Shift = 10px)"
        )
        self._update_geometry()

    def _update_geometry(self):
        x_px = int(self.bar_data["offset_x"] * self.scale)
        y_px = int(self.bar_data["offset_y"] * self.scale)
        w_px = max(30, int(self.bar_data["width"] * self.scale))
        h_px = max(16, int(self.bar_data["height"] * self.scale))
        self.setGeometry(x_px, y_px, w_px, h_px)

    def set_snap_step(self, step: int):
        self.snap_step = step

    def set_selected(self, selected: bool):
        self.selected = selected
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bg = QColor(self.bg_color)
        if self._drag_active:
            bg = bg.lighter(140)

        painter.setBrush(QBrush(bg))
        if self.selected:
            painter.setPen(QPen(QColor(PALETTE["blue"]), 2))
        else:
            painter.setPen(QPen(self.fg_color.darker(180), 1))

        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)

        if self.selected:
            glow = QColor(PALETTE["blue"])
            glow.setAlpha(25)
            painter.setBrush(QBrush(glow))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)

        # Draw module preview
        self._paint_modules(painter)

        # Bar name at top-left corner (small)
        painter.setPen(QColor(PALETTE["surface2"]))
        painter.setFont(QFont("Monospace", 6))
        painter.drawText(4, 0, self.width() - 8, 12,
                         Qt.AlignLeft | Qt.AlignVCenter,
                         f"[bar/{self.bar_name}]  {self.bar_data['offset_x']},{self.bar_data['offset_y']}")
        painter.end()

    def _paint_modules(self, painter: QPainter):
        """Render left/center/right module names as coloured chips."""
        h = self.height()
        w = self.width()
        top = 13  # below bar name label
        chip_h = max(10, h - top - 2)

        sections = [
            ("left",   self.bar_data.get("modules_left", ""),   Qt.AlignLeft,   PALETTE["green"]),
            ("center", self.bar_data.get("modules_center", ""), Qt.AlignHCenter,PALETTE["blue"]),
            ("right",  self.bar_data.get("modules_right", ""),  Qt.AlignRight,  PALETTE["peach"]),
        ]

        CHIP_W   = 44
        CHIP_PAD = 3
        font = QFont("Monospace", 6)
        painter.setFont(font)

        for _side, raw, align, color in sections:
            if not raw or not raw.strip():
                continue
            names = raw.strip().split()
            if not names:
                continue

            # Position chips
            total_w = min(len(names) * (CHIP_W + CHIP_PAD), w // 3 - 4)
            chip_w  = min(CHIP_W, (total_w - CHIP_PAD * (len(names)-1)) // max(1, len(names)))
            chip_w  = max(chip_w, 20)

            if align == Qt.AlignLeft:
                start_x = 4
            elif align == Qt.AlignHCenter:
                block_w = len(names) * (chip_w + CHIP_PAD)
                start_x = (w - block_w) // 2
            else:
                block_w = len(names) * (chip_w + CHIP_PAD)
                start_x = w - block_w - 4

            for i, mod_name in enumerate(names):
                cx = start_x + i * (chip_w + CHIP_PAD)
                cy = top
                c = QColor(color)
                c.setAlpha(60)
                painter.setBrush(QBrush(c))
                border_c = QColor(color)
                border_c.setAlpha(140)
                painter.setPen(QPen(border_c, 1))
                painter.drawRoundedRect(cx, cy, chip_w, chip_h, 3, 3)

                painter.setPen(QColor(color))
                painter.drawText(cx + 2, cy, chip_w - 4, chip_h,
                                 Qt.AlignVCenter | Qt.AlignLeft,
                                 mod_name[:7])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.bar_clicked.emit(self.bar_name)
            self._drag_active = True
            self._drag_start_mouse = event.globalPos()
            self._drag_start_x = self.bar_data["offset_x"]
            self._drag_start_y = self.bar_data["offset_y"]
            self.setCursor(Qt.ClosedHandCursor)
            self.raise_()
            self.update()

    def mouseMoveEvent(self, event):
        if not self._drag_active:
            return
        canvas = self.parent()
        if canvas is None:
            return

        delta_x_screen = event.globalPos().x() - self._drag_start_mouse.x()
        delta_y_screen = event.globalPos().y() - self._drag_start_mouse.y()
        delta_x_real = int(delta_x_screen / self.scale)
        delta_y_real = int(delta_y_screen / self.scale)

        new_x = self._drag_start_x + delta_x_real
        new_y = self._drag_start_y + delta_y_real

        # Snap to grid first
        if self.snap_step > 1:
            new_x = round(new_x / self.snap_step) * self.snap_step
            new_y = round(new_y / self.snap_step) * self.snap_step

        # Snap to other bars (proximity + gap_snap)
        snap_radius = max(self.snap_step * 2, 8) if self.snap_step > 1 else 8
        gap = self.gap_snap
        for name, other_w in canvas._bar_widgets.items():
            if name == self.bar_name:
                continue
            od = other_w.bar_data
            my_w = self.bar_data["width"]
            my_h = self.bar_data["height"]
            # snap left edge to other's right edge + gap
            if abs(new_x - (od["offset_x"] + od["width"] + gap)) < snap_radius:
                new_x = od["offset_x"] + od["width"] + gap
            # snap right edge to other's left edge - gap
            elif abs((new_x + my_w) - (od["offset_x"] - gap)) < snap_radius:
                new_x = od["offset_x"] - gap - my_w
            # snap left to left
            elif abs(new_x - od["offset_x"]) < snap_radius:
                new_x = od["offset_x"]
            # snap top to bottom + gap
            if abs(new_y - (od["offset_y"] + od["height"] + gap)) < snap_radius:
                new_y = od["offset_y"] + od["height"] + gap
            # snap bottom to top - gap
            elif abs((new_y + my_h) - (od["offset_y"] - gap)) < snap_radius:
                new_y = od["offset_y"] - gap - my_h
            # snap top to top
            elif abs(new_y - od["offset_y"]) < snap_radius:
                new_y = od["offset_y"]

        # Apply min_margin from edges
        mg = self.min_margin
        max_x = max(mg, canvas.real_screen_w - self.bar_data["width"] - mg)
        max_y = max(mg, canvas.real_screen_h - self.bar_data["height"] - mg)
        new_x = max(mg, min(new_x, max_x))
        new_y = max(mg, min(new_y, max_y))

        self.bar_data["offset_x"] = new_x
        self.bar_data["offset_y"] = new_y
        self._update_geometry()
        self.moved.emit(self.bar_name, new_x, new_y)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = False
            self.setCursor(Qt.OpenHandCursor)
            self.update()

    def keyPressEvent(self, event):
        if not self.selected:
            return
        step = 10 if (event.modifiers() & Qt.ShiftModifier) else 1
        canvas = self.parent()
        dx, dy = 0, 0
        if event.key() == Qt.Key_Left:
            dx = -step
        elif event.key() == Qt.Key_Right:
            dx = step
        elif event.key() == Qt.Key_Up:
            dy = -step
        elif event.key() == Qt.Key_Down:
            dy = step
        else:
            super().keyPressEvent(event)
            return

        new_x = self.bar_data["offset_x"] + dx
        new_y = self.bar_data["offset_y"] + dy
        if canvas:
            max_x = max(0, canvas.real_screen_w - self.bar_data["width"])
            max_y = max(0, canvas.real_screen_h - self.bar_data["height"])
            new_x = max(0, min(new_x, max_x))
            new_y = max(0, min(new_y, max_y))
        self.bar_data["offset_x"] = new_x
        self.bar_data["offset_y"] = new_y
        self._update_geometry()
        self.moved.emit(self.bar_name, new_x, new_y)
        self.update()


# ---------------------------------------------------------------------------
# Canvas — scrollable, full height
# ---------------------------------------------------------------------------

class EditorCanvas(QWidget):
    bar_moved = pyqtSignal(str, int, int)
    element_selected = pyqtSignal(str, dict)
    element_deselected = pyqtSignal()

    CANVAS_W = 920

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.real_screen_w = config.screen_w
        self.real_screen_h = config.screen_h
        self.snap_step  = 1
        self.min_margin = 0
        self.gap_snap   = 0
        self.show_grid   = True
        self.show_center = True
        self.show_thirds = False
        self._bar_widgets: dict = {}
        self._selected_name: Optional[str] = None
        self.scale = self.CANVAS_W / max(1, config.screen_w)
        canvas_h = max(300, int(config.screen_h * self.scale))
        self.canvas_h = canvas_h
        self.setFixedSize(self.CANVAS_W, canvas_h)
        self.setObjectName("EditorCanvas")
        self._build_bars()

    def _build_bars(self):
        for w in self._bar_widgets.values():
            w.deleteLater()
        self._bar_widgets.clear()
        self._selected_name = None

        for name, data in self.config.bars.items():
            # per-bar colors from bar data, fallback to global [colors]
            bg_raw = data.get("background") or ""
            fg_raw = data.get("foreground") or ""
            def _parse_color(raw, fallback):
                if raw:
                    import re as _re
                    m = _re.search(r"#([0-9A-Fa-f]{3,8})", raw)
                    if m:
                        return QColor("#" + m.group(1))
                return self.config.get_color(fallback.lstrip("#"), fallback)
            bg_color = _parse_color(bg_raw, "#1e1e2e")
            fg_color = _parse_color(fg_raw, "#cdd6f4")

            bar_w = DraggableBar(
                name=name,
                bar_data=data,
                scale=self.scale,
                snap_step=self.snap_step,
                min_margin=self.min_margin,
                gap_snap=self.gap_snap,
                bg_color=bg_color,
                fg_color=fg_color,
                parent=self,
            )
            bar_w.moved.connect(self.bar_moved)
            bar_w.bar_clicked.connect(self._on_bar_clicked)
            bar_w.show()
            self._bar_widgets[name] = bar_w

    def _on_bar_clicked(self, name: str):
        for n, w in self._bar_widgets.items():
            w.set_selected(n == name)
        self._selected_name = name
        self.element_selected.emit(name, self.config.bars[name])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            for w in self._bar_widgets.values():
                w.set_selected(False)
            self._selected_name = None
            self.element_deselected.emit()

    def set_snap_step(self, step: int):
        self.snap_step = step
        for w in self._bar_widgets.values():
            w.snap_step = step

    def set_min_margin(self, val: int):
        self.min_margin = val
        for w in self._bar_widgets.values():
            w.min_margin = val

    def set_gap_snap(self, val: int):
        self.gap_snap = val
        for w in self._bar_widgets.values():
            w.gap_snap = val

    def apply_grid_settings(self, show_grid, show_center, show_thirds):
        self.show_grid   = show_grid
        self.show_center = show_center
        self.show_thirds = show_thirds
        self.update()

    def refresh(self):
        self._build_bars()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0a0a14"))

        # grid
        if self.show_grid:
            pen = QPen(QColor(50, 50, 80, 50), 1, Qt.DotLine)
            painter.setPen(pen)
            step = max(10, int(50 * self.scale))
            for x in range(0, self.CANVAS_W, step):
                painter.drawLine(x, 0, x, self.canvas_h)
            for y in range(0, self.canvas_h, step):
                painter.drawLine(0, y, self.CANVAS_W, y)

        # center line (vertical)
        if self.show_center:
            cx = self.CANVAS_W // 2
            pen = QPen(QColor(PALETTE["blue"]), 1, Qt.DashLine)
            pen.setDashPattern([4, 6])
            painter.setPen(pen)
            painter.drawLine(cx, 0, cx, self.canvas_h)
            # label
            painter.setPen(QColor(PALETTE["blue"]))
            painter.setFont(QFont("Monospace", 6))
            painter.drawText(cx + 3, 10, "center")

        # thirds
        if self.show_thirds:
            pen = QPen(QColor(PALETTE["mauve"]), 1, Qt.DashLine)
            pen.setDashPattern([3, 8])
            painter.setPen(pen)
            t1 = self.CANVAS_W // 3
            t2 = self.CANVAS_W * 2 // 3
            h1 = self.canvas_h // 3
            h2 = self.canvas_h * 2 // 3
            for x in (t1, t2):
                painter.drawLine(x, 0, x, self.canvas_h)
            for y in (h1, h2):
                painter.drawLine(0, y, self.CANVAS_W, y)

        # border
        painter.setPen(QPen(QColor(PALETTE["surface1"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        # resolution label
        painter.setPen(QColor(PALETTE["surface2"]))
        painter.setFont(QFont("Monospace", 7))
        res_text = f"{self.real_screen_w}×{self.real_screen_h}"
        painter.drawText(
            self.rect().adjusted(6, 0, -6, -4),
            Qt.AlignBottom | Qt.AlignRight,
            res_text
        )
        painter.end()


# ---------------------------------------------------------------------------
# Color picker button
# ---------------------------------------------------------------------------

class ColorButton(QPushButton):
    color_changed = pyqtSignal(str)

    def __init__(self, color: str = "#000000", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(28, 22)
        self._update_style()
        self.clicked.connect(self._pick_color)

    def _update_style(self):
        c = self._color.lstrip("#")
        if len(c) == 8:  # AARRGGBB
            rgb = "#" + c[2:]
        else:
            rgb = self._color
        self.setStyleSheet(
            f"background-color: {rgb}; border: 1px solid {PALETTE['surface1']};"
            " border-radius: 3px;"
        )
        self.setText("")

    def set_color(self, color: str):
        self._color = color
        self._update_style()

    def get_color(self) -> str:
        return self._color

    def _pick_color(self):
        from PyQt5.QtWidgets import QColorDialog
        c = self._color.lstrip("#")
        if len(c) == 8:
            init = QColor(f"#{c[2:]}")
            init.setAlpha(int(c[0:2], 16))
        else:
            init = QColor(self._color)
        dlg = QColorDialog(init, self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)
        if dlg.exec_():
            chosen = dlg.selectedColor()
            alpha = chosen.alpha()
            rgb = chosen.name().lstrip("#")
            if alpha < 255:
                self._color = f"#{alpha:02x}{rgb}"
            else:
                self._color = f"#{rgb}"
            self._update_style()
            self.color_changed.emit(self._color)


# ---------------------------------------------------------------------------
# Properties panel — ALL bar config fields
# ---------------------------------------------------------------------------

class ElementPropertiesPanel(QWidget):
    property_changed = pyqtSignal(str, str, object)

    # All standard bar fields with (label, default, type: spin/line/color/check/combo)
    BAR_FIELDS = [
        # (ini_key, display_label, field_type, default, extra)
        # Geometry
        ("offset-x",   "Offset X",    "spin",  0,      {"min": 0, "max": 9999, "suffix": " px", "key": "offset_x"}),
        ("offset-y",   "Offset Y",    "spin",  0,      {"min": 0, "max": 9999, "suffix": " px", "key": "offset_y"}),
        ("width",      "Ширина",      "spin",  1920,   {"min": 1, "max": 9999, "suffix": " px", "key": "width"}),
        ("height",     "Высота",      "spin",  30,     {"min": 1, "max": 500,  "suffix": " px", "key": "height"}),
        ("monitor",    "Монитор",     "line",  "",     {"placeholder": "eDP-1", "key": "monitor"}),
        # Colors
        ("background", "Фон",         "color", "#1e1e2e", {"key": "background"}),
        ("foreground", "Текст",       "color", "#cdd6f4", {"key": "foreground"}),
        ("line-color", "Линия",       "color", "#89b4fa", {"key": "line-color"}),
        ("overline-color",  "Overline",  "color", "#89b4fa", {"key": "overline-color"}),
        ("underline-color", "Underline", "color", "#89b4fa", {"key": "underline-color"}),
        # Dimensions
        ("line-size",  "Толщина линии","spin", 2,      {"min": 0, "max": 20, "suffix": " px", "key": "line-size"}),
        ("padding-left",  "Padding L", "spin", 0,      {"min": 0, "max": 200, "suffix": " px", "key": "padding-left"}),
        ("padding-right", "Padding R", "spin", 0,      {"min": 0, "max": 200, "suffix": " px", "key": "padding-right"}),
        ("module-margin-left",  "Mod margin L", "spin", 0, {"min": 0, "max": 100, "suffix": " px", "key": "module-margin-left"}),
        ("module-margin-right", "Mod margin R", "spin", 0, {"min": 0, "max": 100, "suffix": " px", "key": "module-margin-right"}),
        # Border
        ("border-size",   "Border",   "spin",  0,      {"min": 0, "max": 50, "suffix": " px", "key": "border-size"}),
        ("border-color",  "Border цвет", "color", "#313244", {"key": "border-color"}),
        ("border-top",    "Border top",  "spin", 0,    {"min": 0, "max": 50, "suffix": " px", "key": "border-top"}),
        ("border-bottom", "Border bot",  "spin", 0,    {"min": 0, "max": 50, "suffix": " px", "key": "border-bottom"}),
        ("border-left",   "Border left", "spin", 0,    {"min": 0, "max": 50, "suffix": " px", "key": "border-left"}),
        ("border-right",  "Border right","spin", 0,    {"min": 0, "max": 50, "suffix": " px", "key": "border-right"}),
        # Radius
        ("radius",        "Радиус",    "spin",  0,      {"min": 0, "max": 100, "suffix": " px", "key": "radius"}),
        ("radius-top-left",  "Radius TL", "spin", 0,   {"min": 0, "max": 100, "suffix": " px", "key": "radius-top-left"}),
        ("radius-top-right", "Radius TR", "spin", 0,   {"min": 0, "max": 100, "suffix": " px", "key": "radius-top-right"}),
        ("radius-bottom-left",  "Radius BL", "spin", 0, {"min": 0, "max": 100, "suffix": " px", "key": "radius-bottom-left"}),
        ("radius-bottom-right", "Radius BR", "spin", 0, {"min": 0, "max": 100, "suffix": " px", "key": "radius-bottom-right"}),
        # Font
        ("font-0",  "Шрифт 0",   "line", "monospace:size=10", {"placeholder": "Ubuntu:size=10", "key": "font-0"}),
        ("font-1",  "Шрифт 1",   "line", "",  {"placeholder": "Noto Sans:size=10", "key": "font-1"}),
        ("font-2",  "Шрифт 2",   "line", "",  {"placeholder": "Font Awesome:size=10", "key": "font-2"}),
        # Position
        ("bottom",  "Снизу",     "check", False, {"key": "bottom"}),
        ("fixed-center", "Fixed center", "check", True, {"key": "fixed-center"}),
        ("override-redirect", "Override redirect", "check", False, {"key": "override-redirect"}),
        # Tray
        ("tray-position", "Tray",   "combo", "none", {"options": ["none", "left", "right", "center"], "key": "tray-position"}),
        ("tray-detached",  "Tray detached", "check", False, {"key": "tray-detached"}),
        # Modules
        ("modules-left",   "Лев. модули",  "line", "", {"placeholder": "cpu mem ...", "key": "modules_left"}),
        ("modules-center", "Центр модули", "line", "", {"placeholder": "date ...", "key": "modules_center"}),
        ("modules-right",  "Прав. модули", "line", "", {"placeholder": "pulseaudio ...", "key": "modules_right"}),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_name: Optional[str] = None
        self._updating = False
        self._widgets: dict = {}   # ini_key -> widget

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._title = QLabel("Свойства")
        self._title.setFont(QFont("Monospace", 9, QFont.Bold))
        self._title.setStyleSheet(f"color: {PALETTE['blue']};")
        root.addWidget(self._title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE['surface0']};")
        root.addWidget(sep)

        self._form_widget = QWidget()
        form = QFormLayout(self._form_widget)
        form.setSpacing(5)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._name_lbl = QLabel("—")
        self._name_lbl.setFont(QFont("Monospace", 8, QFont.Bold))
        self._name_lbl.setStyleSheet(f"color: {PALETTE['green']};")
        form.addRow(self._make_lbl("Имя"), self._name_lbl)

        # Group sections
        groups = [
            ("📐 Геометрия",  ["offset-x","offset-y","width","height","monitor"]),
            ("🎨 Цвета",      ["background","foreground","line-color","overline-color","underline-color","line-size"]),
            ("📏 Отступы",    ["padding-left","padding-right","module-margin-left","module-margin-right"]),
            ("⬛ Рамка",      ["border-size","border-color","border-top","border-bottom","border-left","border-right"]),
            ("⭕ Радиус",     ["radius","radius-top-left","radius-top-right","radius-bottom-left","radius-bottom-right"]),
            ("🔤 Шрифты",     ["font-0","font-1","font-2"]),
            ("⚙ Поведение",   ["bottom","fixed-center","override-redirect","tray-position","tray-detached"]),
            ("📦 Модули",     ["modules-left","modules-center","modules-right"]),
        ]

        field_lookup = {f[0]: f for f in self.BAR_FIELDS}

        for group_name, keys in groups:
            grp_lbl = QLabel(group_name)
            grp_lbl.setFont(QFont("Monospace", 8, QFont.Bold))
            grp_lbl.setStyleSheet(
                f"color: {PALETTE['mauve']}; margin-top: 6px;"
                f" border-top: 1px solid {PALETTE['surface0']}; padding-top: 4px;"
            )
            form.addRow(grp_lbl)

            for key in keys:
                if key not in field_lookup:
                    continue
                _, label, ftype, default, extra = field_lookup[key]
                widget = self._make_field(key, ftype, default, extra)
                form.addRow(self._make_lbl(label), widget)
                self._widgets[key] = widget

        root.addWidget(self._form_widget)
        self._form_widget.hide()

        self._placeholder = QLabel("← Нажмите на\nэлемент в\nконструкторе")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setFont(QFont("Monospace", 8))
        self._placeholder.setStyleSheet(f"color: {PALETTE['surface1']};")
        root.addWidget(self._placeholder)
        root.addStretch()

    def _make_field(self, key: str, ftype: str, default, extra: dict):
        from PyQt5.QtWidgets import QComboBox
        if ftype == "spin":
            w = QSpinBox()
            w.setRange(extra.get("min", 0), extra.get("max", 9999))
            if "suffix" in extra:
                w.setSuffix(extra["suffix"])
            w.setValue(default)
            w.valueChanged.connect(lambda v, k=key, e=extra: self._emit(e.get("key", k), v))
            return w
        elif ftype == "line":
            w = QLineEdit()
            if "placeholder" in extra:
                w.setPlaceholderText(extra["placeholder"])
            w.setText(str(default))
            w.textChanged.connect(lambda v, k=key, e=extra: self._emit(e.get("key", k), v))
            return w
        elif ftype == "color":
            w = ColorButton(default)
            w.color_changed.connect(lambda v, k=key, e=extra: self._emit(e.get("key", k), v))
            return w
        elif ftype == "check":
            w = QCheckBox()
            w.setChecked(bool(default))
            w.stateChanged.connect(lambda v, k=key, e=extra: self._emit(e.get("key", k), bool(v)))
            return w
        elif ftype == "combo":
            from PyQt5.QtWidgets import QComboBox
            w = QComboBox()
            w.setFont(QFont("Monospace", 8))
            w.setStyleSheet(
                f"QComboBox {{ background: {PALETTE['mantle']}; color: {PALETTE['text']};"
                f" border: 1px solid {PALETTE['surface1']}; border-radius: 4px; padding: 2px 6px;"
                f" font-size: 8px; }}"
                f"QComboBox::drop-down {{ border: none; }}"
            )
            for opt in extra.get("options", []):
                w.addItem(opt)
            idx = extra.get("options", []).index(default) if default in extra.get("options", []) else 0
            w.setCurrentIndex(idx)
            w.currentTextChanged.connect(lambda v, k=key, e=extra: self._emit(e.get("key", k), v))
            return w
        return QLabel("?")

    def _make_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text + ":")
        lbl.setFont(QFont("Monospace", 8))
        lbl.setStyleSheet(f"color: {PALETTE['overlay1']};")
        return lbl

    def show_element(self, name: str, data: dict):
        self._updating = True
        self._current_name = name
        self._placeholder.hide()
        self._form_widget.show()
        self._title.setText(f"◈ [bar/{name}]")
        self._name_lbl.setText(f"bar/{name}")

        from PyQt5.QtWidgets import QComboBox
        # Map all fields
        field_lookup = {f[0]: f for f in self.BAR_FIELDS}
        for key, widget in self._widgets.items():
            if key not in field_lookup:
                continue
            _, _, ftype, default, extra = field_lookup[key]
            prop_key = extra.get("key", key)
            val = data.get(prop_key, data.get(key, default))
            if ftype == "spin":
                try:
                    widget.setValue(int(val))
                except (TypeError, ValueError):
                    widget.setValue(int(default))
            elif ftype == "line":
                widget.setText(str(val) if val is not None else "")
            elif ftype == "color":
                widget.set_color(str(val) if val else str(default))
            elif ftype == "check":
                if isinstance(val, bool):
                    widget.setChecked(val)
                elif isinstance(val, str):
                    widget.setChecked(val.lower() in ("true", "1", "yes"))
            elif ftype == "combo" and isinstance(widget, QComboBox):
                idx = widget.findText(str(val))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
        self._updating = False

    def clear(self):
        self._current_name = None
        self._form_widget.hide()
        self._placeholder.show()
        self._title.setText("Свойства")

    def _emit(self, key: str, value):
        if not self._updating and self._current_name:
            self.property_changed.emit(self._current_name, key, value)


# ---------------------------------------------------------------------------
# Element palette (left panel in constructor)
# ---------------------------------------------------------------------------

class GridSettingsPanel(QWidget):
    """Left panel in constructor — grid & snap settings."""
    add_bar_clicked    = pyqtSignal()
    add_module_clicked = pyqtSignal(str)
    settings_changed   = pyqtSignal()   # emitted whenever any grid setting changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snap_step   = 1
        self._min_margin  = 0
        self._gap_snap    = 0
        self._show_thirds = False
        self._show_center = True
        self._show_grid   = True

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(6)

        def _hdr(text, color=PALETTE["blue"]):
            l = QLabel(text)
            l.setFont(QFont("Monospace", 8, QFont.Bold))
            l.setStyleSheet(f"color: {color};")
            return l

        def _sep():
            s = QFrame()
            s.setFrameShape(QFrame.HLine)
            s.setStyleSheet(f"color: {PALETTE['surface0']};")
            return s

        def _lbl(text):
            l = QLabel(text)
            l.setFont(QFont("Monospace", 7))
            l.setStyleSheet(f"color: {PALETTE['overlay1']};")
            l.setWordWrap(True)
            return l

        # ── Добавить ──────────────────────────────────────
        root.addWidget(_hdr("Добавить"))
        root.addWidget(_sep())

        self.btn_add_bar = QPushButton("＋  Новый бар")
        self.btn_add_bar.setEnabled(False)
        self.btn_add_bar.setToolTip("Добавить новый [bar/...] в конфиг")
        self.btn_add_bar.clicked.connect(self.add_bar_clicked)
        root.addWidget(self.btn_add_bar)

        # ── Сетка ─────────────────────────────────────────
        root.addSpacing(4)
        root.addWidget(_hdr("Сетка", PALETTE["mauve"]))
        root.addWidget(_sep())

        # Показывать сетку
        self._cb_grid = QCheckBox("Показывать сетку")
        self._cb_grid.setFont(QFont("Monospace", 7))
        self._cb_grid.setChecked(True)
        self._cb_grid.stateChanged.connect(self._on_changed)
        root.addWidget(self._cb_grid)

        # Центральная линия
        self._cb_center = QCheckBox("Центральная линия")
        self._cb_center.setFont(QFont("Monospace", 7))
        self._cb_center.setChecked(True)
        self._cb_center.stateChanged.connect(self._on_changed)
        root.addWidget(self._cb_center)

        # Трети
        self._cb_thirds = QCheckBox("Линии третей")
        self._cb_thirds.setFont(QFont("Monospace", 7))
        self._cb_thirds.setChecked(False)
        self._cb_thirds.stateChanged.connect(self._on_changed)
        root.addWidget(self._cb_thirds)

        root.addSpacing(4)

        # ── Привязка (Snap) ───────────────────────────────
        root.addWidget(_hdr("Привязка (Snap)", PALETTE["teal"]))
        root.addWidget(_sep())

        # Snap к сетке
        snap_row = QHBoxLayout()
        snap_row.setSpacing(4)
        snap_row.addWidget(_lbl("Сетка:"))
        self._snap_spin = QSpinBox()
        self._snap_spin.setRange(1, 200)
        self._snap_spin.setValue(1)
        self._snap_spin.setSuffix(" px")
        self._snap_spin.setFixedWidth(72)
        self._snap_spin.setFont(QFont("Monospace", 7))
        self._snap_spin.setToolTip("Шаг сетки snap — элемент двигается кратно этому значению")
        self._snap_spin.valueChanged.connect(self._on_changed)
        snap_row.addWidget(self._snap_spin)
        root.addLayout(snap_row)

        # Минимальный отступ от края
        margin_row = QHBoxLayout()
        margin_row.setSpacing(4)
        margin_row.addWidget(_lbl("Мин. от края:"))
        self._margin_spin = QSpinBox()
        self._margin_spin.setRange(0, 500)
        self._margin_spin.setValue(0)
        self._margin_spin.setSuffix(" px")
        self._margin_spin.setFixedWidth(72)
        self._margin_spin.setFont(QFont("Monospace", 7))
        self._margin_spin.setToolTip(
            "Минимальный отступ от края экрана — нельзя сдвинуть бар ближе этого расстояния"
        )
        self._margin_spin.valueChanged.connect(self._on_changed)
        margin_row.addWidget(self._margin_spin)
        root.addLayout(margin_row)
        root.addWidget(_lbl("  ↑ не даёт сдвинуть к краю"), )

        # Snap между элементами (gap snap)
        gap_row = QHBoxLayout()
        gap_row.setSpacing(4)
        gap_row.addWidget(_lbl("Зазор между:"))
        self._gap_spin = QSpinBox()
        self._gap_spin.setRange(0, 200)
        self._gap_spin.setValue(0)
        self._gap_spin.setSuffix(" px")
        self._gap_spin.setFixedWidth(72)
        self._gap_spin.setFont(QFont("Monospace", 7))
        self._gap_spin.setToolTip(
            "Желаемый зазор между барами — при приближении бар прилипает на этом расстоянии от соседа"
        )
        self._gap_spin.valueChanged.connect(self._on_changed)
        gap_row.addWidget(self._gap_spin)
        root.addLayout(gap_row)
        root.addWidget(_lbl("  ↑ зазор при snap к соседу"))

        root.addStretch()

        ver_lbl = QLabel("neopoly v2.0")
        ver_lbl.setFont(QFont("Monospace", 7))
        ver_lbl.setStyleSheet(f"color: {PALETTE['surface0']};")
        ver_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(ver_lbl)

    def _on_changed(self, *_):
        self.settings_changed.emit()

    def enable_buttons(self, enabled: bool):
        self.btn_add_bar.setEnabled(enabled)

    @property
    def snap_step(self) -> int:
        return self._snap_spin.value()

    @property
    def min_margin(self) -> int:
        return self._margin_spin.value()

    @property
    def gap_snap(self) -> int:
        return self._gap_spin.value()

    @property
    def show_grid(self) -> bool:
        return self._cb_grid.isChecked()

    @property
    def show_center(self) -> bool:
        return self._cb_center.isChecked()

    @property
    def show_thirds(self) -> bool:
        return self._cb_thirds.isChecked()


# ---------------------------------------------------------------------------
# Constructor tab — scrollable canvas
# ---------------------------------------------------------------------------

class ConstructorTab(QWidget):
    bar_moved = pyqtSignal(str, int, int)
    status_message = pyqtSignal(str)

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.canvas: Optional[EditorCanvas] = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # Toolbar (simplified — snap is now in left panel)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._hint_lbl = QLabel("Нет конфига  //  Файл → Открыть...")
        self._hint_lbl.setFont(QFont("Monospace", 8))
        self._hint_lbl.setStyleSheet(f"color: {PALETTE['surface2']};")
        toolbar.addStretch()
        toolbar.addWidget(self._hint_lbl)
        root.addLayout(toolbar)

        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._palette = GridSettingsPanel()
        self._palette.setFixedWidth(165)
        self._palette.add_bar_clicked.connect(self._on_add_bar)
        self._palette.settings_changed.connect(self._on_grid_settings_changed)
        splitter.addWidget(self._palette)

        # Center: placeholder OR scroll area with canvas
        self._center = QWidget()
        cl = QVBoxLayout(self._center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._canvas_placeholder = QLabel(
            "Откройте конфиг Polybar\nФайл → Открыть...",
            alignment=Qt.AlignCenter,
        )
        self._canvas_placeholder.setMinimumHeight(300)
        self._canvas_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas_placeholder.setStyleSheet(
            f"color: {PALETTE['surface1']};"
            " border: 2px dashed #313244; border-radius: 8px;"
        )
        cl.addWidget(self._canvas_placeholder)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: #0a0a14; }")
        self._scroll.hide()
        cl.addWidget(self._scroll, 1)

        self._center_layout = cl
        splitter.addWidget(self._center)

        # Right: properties panel wrapped in scroll
        self._props = ElementPropertiesPanel()
        self._props.property_changed.connect(self._on_property_changed)
        props_scroll = QScrollArea()
        props_scroll.setWidget(self._props)
        props_scroll.setWidgetResizable(True)
        props_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        props_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        props_scroll.setStyleSheet("QScrollArea { border: none; }")
        props_scroll.setMinimumWidth(220)
        props_scroll.setObjectName("props_panel")
        splitter.addWidget(props_scroll)

        splitter.setSizes([165, 700, 240])
        root.addWidget(splitter, 1)

    def load_config(self, config: PolybarConfig):
        self.config = config
        self._hint_lbl.setText(
            f"баров: {len(config.bars)}  //  {os.path.basename(config.filepath or '')}"
        )
        self._rebuild_canvas()

    def _rebuild_canvas(self):
        if self.canvas:
            self.canvas.deleteLater()
            self.canvas = None

        self._canvas_placeholder.hide()
        self._scroll.show()

        self.canvas = EditorCanvas(config=self.config)
        self.canvas.bar_moved.connect(self._on_bar_moved)
        self.canvas.element_selected.connect(self._on_element_selected)
        self.canvas.element_deselected.connect(self._props.clear)
        self._scroll.setWidget(self.canvas)
        self._palette.enable_buttons(True)
        self._on_grid_settings_changed()

    def _on_bar_moved(self, name: str, x: int, y: int):
        self.bar_moved.emit(name, x, y)
        self.status_message.emit(f"[bar/{name}]  offset-x={x}px  offset-y={y}px")
        if self._props._current_name == name:
            self._props.show_element(name, self.config.bars[name])

    def _on_element_selected(self, name: str, data: dict):
        self._props.show_element(name, data)

    def _on_property_changed(self, name: str, key: str, value):
        if name in self.config.bars:
            self.config.bars[name][key] = value
            if self.canvas and name in self.canvas._bar_widgets:
                self.canvas._bar_widgets[name]._update_geometry()
                self.canvas._bar_widgets[name].update()
            self.status_message.emit(f"[bar/{name}]  {key} → {value}")

    def _on_grid_settings_changed(self, *_):
        if not self.canvas:
            return
        p = self._palette
        self.canvas.set_snap_step(p.snap_step)
        self.canvas.set_min_margin(p.min_margin)
        self.canvas.set_gap_snap(p.gap_snap)
        self.canvas.apply_grid_settings(p.show_grid, p.show_center, p.show_thirds)

    def _on_add_bar(self):
        """Add a new bar to the config."""
        if not self.config or not self.config.filepath:
            return
        # Ask for name
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Новый бар", "Имя бара (без 'bar/'):",
            text=f"bar{len(self.config.bars) + 1}"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.config.bars:
            QMessageBox.warning(self, "Ошибка", f"Бар '{name}' уже существует!")
            return
        # Create bar data
        sw = self.config.screen_w
        sh = self.config.screen_h
        bar_data = {
            "_name": name,
            "offset_x": 0, "offset_x_raw": "0",
            "offset_y": 0, "offset_y_raw": "0",
            "width": sw, "width_raw": "100%",
            "height": 30,
            "monitor": "",
            "modules_left": "",
            "modules_center": "date",
            "modules_right": "",
        }
        self.config.bars[name] = bar_data
        # Append to raw lines
        new_section = (
            f"\n[bar/{name}]\n"
            f"width = 100%\n"
            f"height = 30\n"
            f"offset-x = 0\n"
            f"offset-y = 0\n"
            f"background = #1e1e2e\n"
            f"foreground = #cdd6f4\n"
            f"modules-left =\n"
            f"modules-center = date\n"
            f"modules-right =\n"
        )
        self.config._raw_lines.append(new_section)
        self._rebuild_canvas()
        self.status_message.emit(f"Добавлен [bar/{name}]")

    def _on_add_module(self, mtype: str):
        """Add a new module of given type to the config."""
        if not self.config or not self.config.filepath:
            return
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, f"Новый модуль ({mtype})", "Имя модуля (без 'module/'):",
            text=f"my{mtype}"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.config.modules:
            QMessageBox.warning(self, "Ошибка", f"Модуль '{name}' уже существует!")
            return
        templates = {
            "label":     {"type": "custom", "exec": "echo 'Hello'", "label": "%output%"},
            "ipc":       {"type": "ipc"},
            "custom":    {"type": "custom", "exec": "echo 'Click me'", "click-left": "echo clicked"},
            "separator": {"type": "custom", "label": "|", "label-foreground": "#585b70"},
        }
        mod_data = templates.get(mtype, {"type": mtype})
        self.config.modules[name] = mod_data
        lines = [f"\n[module/{name}]\n"]
        for k, v in mod_data.items():
            lines.append(f"{k} = {v}\n")
        self.config._raw_lines.extend(lines)
        self.status_message.emit(f"Добавлен [module/{name}] (тип: {mtype})")


# ---------------------------------------------------------------------------
# Modules tab — browse and edit [module/...] sections
# ---------------------------------------------------------------------------

class ModulesTab(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._current_module: Optional[str] = None
        self._field_widgets: list = []   # list of (key, QLineEdit)
        self._setup_ui()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ---- Left: module list ----
        left = QWidget()
        left.setStyleSheet(f"QWidget {{ background: {PALETTE['mantle']}; }}")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 10, 8, 8)
        ll.setSpacing(6)

        list_header = QLabel("Модули")
        list_header.setFont(QFont("Monospace", 9, QFont.Bold))
        list_header.setStyleSheet(f"color: {PALETTE['mauve']};")
        ll.addWidget(list_header)

        self._mod_list = QListWidget()
        self._mod_list.setFont(QFont("Monospace", 8))
        self._mod_list.currentItemChanged.connect(self._on_module_selected)
        ll.addWidget(self._mod_list, 1)

        self._list_placeholder = QLabel("Загрузите конфиг\nдля просмотра\nмодулей")
        self._list_placeholder.setAlignment(Qt.AlignCenter)
        self._list_placeholder.setFont(QFont("Monospace", 8))
        self._list_placeholder.setStyleSheet(f"color: {PALETTE['surface1']};")
        ll.addWidget(self._list_placeholder)
        self._mod_list.hide()

        splitter.addWidget(left)

        # ---- Right: module editor ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 10, 10, 10)
        rl.setSpacing(8)

        hdr_row = QHBoxLayout()
        self._mod_title = QLabel("Выберите модуль")
        self._mod_title.setFont(QFont("Monospace", 9, QFont.Bold))
        self._mod_title.setStyleSheet(f"color: {PALETTE['mauve']};")
        hdr_row.addWidget(self._mod_title)
        hdr_row.addStretch()
        self._save_mod_btn = QPushButton("💾  Применить")
        self._save_mod_btn.setEnabled(False)
        self._save_mod_btn.clicked.connect(self._apply_module_changes)
        hdr_row.addWidget(self._save_mod_btn)
        rl.addLayout(hdr_row)

        self._bar_usage_lbl = QLabel("")
        self._bar_usage_lbl.setFont(QFont("Monospace", 7))
        self._bar_usage_lbl.setStyleSheet(f"color: {PALETTE['overlay0']};")
        self._bar_usage_lbl.setWordWrap(True)
        rl.addWidget(self._bar_usage_lbl)

        # Scroll area for the key=value fields
        self._fields_scroll = QScrollArea()
        self._fields_scroll.setWidgetResizable(True)
        self._fields_scroll.setStyleSheet("QScrollArea { border: none; }")
        rl.addWidget(self._fields_scroll, 1)

        self._editor_placeholder = QLabel(
            "Выберите модуль слева\nдля просмотра и редактирования"
        )
        self._editor_placeholder.setAlignment(Qt.AlignCenter)
        self._editor_placeholder.setFont(QFont("Monospace", 8))
        self._editor_placeholder.setStyleSheet(f"color: {PALETTE['surface1']};")
        rl.addWidget(self._editor_placeholder)
        self._fields_scroll.hide()

        splitter.addWidget(right)
        splitter.setSizes([200, 600])
        root.addWidget(splitter)

    def load_config(self, config: PolybarConfig):
        self.config = config
        self._rebuild_list()

    def _rebuild_list(self):
        self._mod_list.clear()
        self._list_placeholder.hide()
        self._mod_list.show()

        for mod_name in sorted(self.config.modules.keys()):
            item = QListWidgetItem(f"[module/{mod_name}]")
            item.setData(Qt.UserRole, mod_name)
            item.setForeground(QColor(PALETTE["mauve"]))
            self._mod_list.addItem(item)

        if not self.config.modules:
            self._list_placeholder.setText("Секции [module/...]\nне найдены в конфиге")
            self._list_placeholder.show()
            self._mod_list.hide()

    def _on_module_selected(self, item: Optional[QListWidgetItem], _prev):
        if item is None:
            return
        mod_name = item.data(Qt.UserRole)
        self._current_module = mod_name
        mod_data = self.config.modules.get(mod_name, {})

        self._mod_title.setText(f"[module/{mod_name}]")
        self._editor_placeholder.hide()
        self._fields_scroll.show()
        self._save_mod_btn.setEnabled(True)

        # Which bars use this module?
        usages = []
        for bar_name, bd in self.config.bars.items():
            combined = " ".join([
                bd.get("modules_left", ""),
                bd.get("modules_center", ""),
                bd.get("modules_right", ""),
            ])
            if mod_name in combined.split():
                usages.append(f"[bar/{bar_name}]")
        self._bar_usage_lbl.setText(
            ("Используется в: " + "  ".join(usages)) if usages
            else "Не используется ни в одном баре"
        )

        # Rebuild the fields widget
        fields_widget = QWidget()
        form = QFormLayout(fields_widget)
        form.setSpacing(6)
        form.setContentsMargins(4, 4, 4, 4)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._field_widgets = []

        for key, val in mod_data.items():
            edit = QLineEdit(val)
            edit.setFont(QFont("Monospace", 8))
            lbl = QLabel(key + ":")
            lbl.setFont(QFont("Monospace", 8))
            lbl.setStyleSheet(f"color: {PALETTE['overlay1']};")
            form.addRow(lbl, edit)
            self._field_widgets.append((key, edit))

        # "Add parameter" row
        add_row = QHBoxLayout()
        self._new_key_edit = QLineEdit()
        self._new_key_edit.setPlaceholderText("ключ")
        self._new_key_edit.setFixedWidth(110)
        self._new_key_edit.setFont(QFont("Monospace", 8))
        self._new_val_edit = QLineEdit()
        self._new_val_edit.setPlaceholderText("значение")
        self._new_val_edit.setFont(QFont("Monospace", 8))
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(28)
        add_btn.clicked.connect(self._add_new_field)
        add_row.addWidget(self._new_key_edit)
        add_row.addWidget(QLabel("="))
        add_row.addWidget(self._new_val_edit, 1)
        add_row.addWidget(add_btn)
        form.addRow(QLabel(""), QWidget())   # spacer
        add_lbl = QLabel("Новый\nпараметр:")
        add_lbl.setFont(QFont("Monospace", 7))
        add_lbl.setStyleSheet(f"color: {PALETTE['surface2']};")
        add_widget = QWidget()
        add_widget.setLayout(add_row)
        form.addRow(add_lbl, add_widget)

        self._fields_scroll.setWidget(fields_widget)
        self.status_message.emit(f"[module/{mod_name}] — {len(mod_data)} параметров")

    def _add_new_field(self):
        key = self._new_key_edit.text().strip()
        val = self._new_val_edit.text().strip()
        if not key:
            return
        if self._current_module:
            self.config.modules.setdefault(self._current_module, {})[key] = val
            self._new_key_edit.clear()
            self._new_val_edit.clear()
            # refresh the view
            current = self._mod_list.currentItem()
            if current:
                self._on_module_selected(current, None)
            self.status_message.emit(f"[module/{self._current_module}] добавлен: {key}")

    def _apply_module_changes(self):
        if self._current_module is None:
            return
        new_data = {}
        for key, edit in self._field_widgets:
            new_data[key] = edit.text()
        self.config.modules[self._current_module] = new_data
        self.status_message.emit(f"[module/{self._current_module}] обновлён в памяти")
        QMessageBox.information(
            self, "Применено",
            f"[module/{self._current_module}] обновлён.\n"
            "Сохраните через Файл → Сохранить чтобы записать на диск."
        )


# ---------------------------------------------------------------------------
# Backup tab
# ---------------------------------------------------------------------------

class BackupTab(QWidget):
    status_message = pyqtSignal(str)
    open_file_requested = pyqtSignal(str)

    BACKUP_DIR = os.path.expanduser("~/.config/neopoly/backups")

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()
        os.makedirs(self.BACKUP_DIR, exist_ok=True)
        self._refresh_backup_list()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title = QLabel("Бэкапы конфигурации")
        title.setFont(QFont("Monospace", 10, QFont.Bold))
        title.setStyleSheet(f"color: {PALETTE['blue']};")
        root.addWidget(title)

        # ---- Settings group ----
        settings_grp = QGroupBox("Настройки бэкапов")
        settings_grp.setFont(QFont("Monospace", 8))
        sg = QVBoxLayout(settings_grp)
        sg.setSpacing(8)

        auto_row = QHBoxLayout()
        self._auto_cb = QCheckBox("Автоматический бэкап при открытии файла")
        self._auto_cb.setChecked(True)
        self._auto_cb.setFont(QFont("Monospace", 8))
        auto_row.addWidget(self._auto_cb)
        auto_row.addStretch()
        sg.addLayout(auto_row)

        freq_row = QHBoxLayout()
        freq_lbl = QLabel("Хранить последних:")
        freq_lbl.setFont(QFont("Monospace", 8))
        freq_lbl.setStyleSheet(f"color: {PALETTE['overlay1']};")
        self._max_spin = QSpinBox()
        self._max_spin.setRange(1, 100)
        self._max_spin.setValue(10)
        self._max_spin.setSuffix("  бэкапов")
        self._max_spin.setFixedWidth(140)
        freq_row.addWidget(freq_lbl)
        freq_row.addWidget(self._max_spin)
        freq_row.addStretch()
        sg.addLayout(freq_row)

        dir_row = QHBoxLayout()
        dir_lbl = QLabel("Папка:")
        dir_lbl.setFont(QFont("Monospace", 8))
        dir_lbl.setStyleSheet(f"color: {PALETTE['overlay1']};")
        self._dir_display = QLabel(self.BACKUP_DIR)
        self._dir_display.setFont(QFont("Monospace", 7))
        self._dir_display.setStyleSheet(f"color: {PALETTE['surface2']};")
        open_dir_btn = QPushButton("📂")
        open_dir_btn.setFixedWidth(32)
        open_dir_btn.setToolTip("Открыть папку")
        open_dir_btn.clicked.connect(self._open_backup_dir)
        dir_row.addWidget(dir_lbl)
        dir_row.addWidget(self._dir_display, 1)
        dir_row.addWidget(open_dir_btn)
        sg.addLayout(dir_row)

        root.addWidget(settings_grp)

        # ---- Action buttons ----
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        btn_now = QPushButton("💾  Создать бэкап сейчас")
        btn_now.clicked.connect(self._backup_now)
        action_row.addWidget(btn_now)

        self._btn_restore = QPushButton("↩  Восстановить выбранный")
        self._btn_restore.setEnabled(False)
        self._btn_restore.clicked.connect(self._restore_selected)
        action_row.addWidget(self._btn_restore)

        self._btn_del = QPushButton("🗑  Удалить")
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(f"color: {PALETTE['red']};")
        self._btn_del.clicked.connect(self._delete_selected)
        action_row.addWidget(self._btn_del)

        action_row.addStretch()

        btn_open_other = QPushButton("📁  Открыть другой файл")
        btn_open_other.clicked.connect(self._open_other_file)
        action_row.addWidget(btn_open_other)

        root.addLayout(action_row)

        # ---- Backup list ----
        list_lbl = QLabel("Существующие бэкапы:")
        list_lbl.setFont(QFont("Monospace", 8, QFont.Bold))
        list_lbl.setStyleSheet(f"color: {PALETTE['overlay1']};")
        root.addWidget(list_lbl)

        self._backup_list = QListWidget()
        self._backup_list.setFont(QFont("Monospace", 8))
        self._backup_list.currentItemChanged.connect(self._on_backup_selected)
        root.addWidget(self._backup_list, 1)

        self._no_backups_lbl = QLabel("Бэкапов пока нет")
        self._no_backups_lbl.setAlignment(Qt.AlignCenter)
        self._no_backups_lbl.setFont(QFont("Monospace", 8))
        self._no_backups_lbl.setStyleSheet(f"color: {PALETTE['surface1']};")
        root.addWidget(self._no_backups_lbl)

    def _refresh_backup_list(self):
        self._backup_list.clear()
        try:
            files = sorted(
                [f for f in os.listdir(self.BACKUP_DIR) if f.endswith(".bak")],
                reverse=True
            )
        except OSError:
            files = []
        for fname in files:
            fpath = os.path.join(self.BACKUP_DIR, fname)
            try:
                sz = os.path.getsize(fpath)
                size_str = f"{sz // 1024} KB" if sz >= 1024 else f"{sz} B"
            except OSError:
                size_str = "?"
            item = QListWidgetItem(f"{fname}   ({size_str})")
            item.setData(Qt.UserRole, fpath)
            self._backup_list.addItem(item)
        if files:
            self._no_backups_lbl.hide()
            self._backup_list.show()
        else:
            self._no_backups_lbl.show()

    def _on_backup_selected(self, item, _prev):
        has = item is not None
        self._btn_restore.setEnabled(has)
        self._btn_del.setEnabled(has)

    # ---- public API ----

    def auto_backup(self, filepath: str):
        """Called by main window when a config is opened (if auto enabled)."""
        if self._auto_cb.isChecked():
            self._do_backup(filepath, silent=True)

    # ---- private ----

    def _backup_now(self):
        if not self.config.filepath:
            QMessageBox.warning(self, "Нет файла", "Сначала откройте конфиг.")
            return
        self._do_backup(self.config.filepath, silent=False)

    def _do_backup(self, filepath: str, silent: bool = False):
        os.makedirs(self.BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(filepath)
        dest = os.path.join(self.BACKUP_DIR, f"{base}_{ts}.bak")
        try:
            shutil.copy2(filepath, dest)
            self._cleanup_old_backups()
            self._refresh_backup_list()
            self.status_message.emit(f"Бэкап создан: {os.path.basename(dest)}")
            if not silent:
                QMessageBox.information(self, "Готово", f"Бэкап создан:\n{dest}")
        except OSError as e:
            self.status_message.emit(f"Ошибка бэкапа: {e}")
            if not silent:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _cleanup_old_backups(self):
        max_n = self._max_spin.value()
        try:
            files = sorted(
                [os.path.join(self.BACKUP_DIR, f)
                 for f in os.listdir(self.BACKUP_DIR) if f.endswith(".bak")],
                key=os.path.getmtime
            )
        except OSError:
            return
        while len(files) > max_n:
            try:
                os.remove(files.pop(0))
            except OSError:
                break

    def _restore_selected(self):
        item = self._backup_list.currentItem()
        if not item:
            return
        bak_path = item.data(Qt.UserRole)
        if not self.config.filepath:
            QMessageBox.warning(self, "Нет файла", "Неизвестен путь текущего конфига.")
            return
        reply = QMessageBox.question(
            self, "Восстановить бэкап",
            f"Восстановить из:\n{bak_path}\n\nТекущий файл будет перезаписан!",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            shutil.copy2(bak_path, self.config.filepath)
            self.status_message.emit(f"Конфиг восстановлен из {os.path.basename(bak_path)}")
            QMessageBox.information(
                self, "Восстановлено",
                "Конфиг восстановлен.\n"
                "Перезагрузите файл через Файл → Открыть."
            )
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _delete_selected(self):
        item = self._backup_list.currentItem()
        if not item:
            return
        bak_path = item.data(Qt.UserRole)
        reply = QMessageBox.question(
            self, "Удалить бэкап",
            f"Удалить:\n{os.path.basename(bak_path)}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(bak_path)
            self._refresh_backup_list()
            self.status_message.emit(f"Бэкап удалён: {os.path.basename(bak_path)}")
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _open_backup_dir(self):
        try:
            subprocess.Popen(["xdg-open", self.BACKUP_DIR])
        except Exception:
            pass

    def _open_other_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть конфиг Polybar",
            os.path.expanduser("~/.config/polybar"),
            "INI files (*.ini *.conf);;All files (*)"
        )
        if path:
            self.open_file_requested.emit(path)


# ---------------------------------------------------------------------------
# Manual edit tab (unchanged except styling tweaks)
# ---------------------------------------------------------------------------

class ManualEditTab(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left.setStyleSheet(f"QWidget {{ background: {PALETTE['mantle']}; }}")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 10, 8, 8)
        ll.setSpacing(6)

        tree_header = QLabel("Секции конфига")
        tree_header.setFont(QFont("Monospace", 9, QFont.Bold))
        tree_header.setStyleSheet(f"color: {PALETTE['blue']};")
        ll.addWidget(tree_header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFont(QFont("Monospace", 8))
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {PALETTE['crust']};
                border: 1px solid {PALETTE['surface0']};
                border-radius: 6px;
                outline: none;
            }}
            QTreeWidget::item {{ padding: 4px 8px; }}
            QTreeWidget::item:selected {{
                background: {PALETTE['surface0']};
                color: {PALETTE['blue']};
                border-radius: 3px;
            }}
            QTreeWidget::item:hover {{ background: {PALETTE['surface0']}40; }}
        """)
        self._tree.itemClicked.connect(self._on_section_clicked)
        ll.addWidget(self._tree)

        self._tree_placeholder = QLabel("Откройте конфиг\nдля редактирования")
        self._tree_placeholder.setAlignment(Qt.AlignCenter)
        self._tree_placeholder.setFont(QFont("Monospace", 8))
        self._tree_placeholder.setStyleSheet(f"color: {PALETTE['surface1']};")
        ll.addWidget(self._tree_placeholder)
        self._tree.hide()

        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 10, 10, 10)
        rl.setSpacing(6)

        editor_hdr = QHBoxLayout()
        self._editor_title = QLabel("Выберите секцию")
        self._editor_title.setFont(QFont("Monospace", 9, QFont.Bold))
        self._editor_title.setStyleSheet(f"color: {PALETTE['green']};")
        editor_hdr.addWidget(self._editor_title)
        editor_hdr.addStretch()
        rl.addLayout(editor_hdr)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Monospace", 9))
        self._editor.setReadOnly(True)
        self._editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {PALETTE['crust']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['surface0']};
                border-radius: 6px;
                padding: 8px;
                selection-background-color: {PALETTE['surface0']};
            }}
        """)
        self._editor.setPlaceholderText(
            "Выберите секцию слева, чтобы редактировать её содержимое..."
        )
        rl.addWidget(self._editor, 1)

        hints = [
            ("offset-x", "горизонтальное смещение (px или %)"),
            ("offset-y", "вертикальное смещение (px или %)"),
            ("width",    "ширина (px или %)"),
            ("height",   "высота (px)"),
            ("monitor",  "монитор (eDP-1, HDMI-1, ...)"),
            ("background", "цвет фона (#RRGGBB или #AARRGGBB)"),
            ("foreground", "цвет текста"),
            ("modules-left / center / right", "список модулей"),
        ]
        hint_text = "   ".join(f"[{k}]" for k, _ in hints[:4])
        hint_lbl = QLabel(hint_text)
        hint_lbl.setFont(QFont("Monospace", 7))
        hint_lbl.setStyleSheet(f"color: {PALETTE['surface2']}; padding: 2px 0;")
        rl.addWidget(hint_lbl)

        splitter.addWidget(right)
        splitter.setSizes([220, 600])
        root.addWidget(splitter)

    def load_config(self, config: PolybarConfig):
        self.config = config
        self._rebuild_tree()

    def _rebuild_tree(self):
        self._tree.clear()
        self._tree_placeholder.hide()
        self._tree.show()
        for section in self.config.get_all_sections():
            item = QTreeWidgetItem([f"[{section}]"])
            item.setData(0, Qt.UserRole, section)
            if section.startswith("bar/"):
                item.setForeground(0, QColor(PALETTE["green"]))
            elif section == "colors":
                item.setForeground(0, QColor(PALETTE["peach"]))
            elif section in ("settings", "global/wm"):
                item.setForeground(0, QColor(PALETTE["blue"]))
            elif section.startswith("module/"):
                item.setForeground(0, QColor(PALETTE["mauve"]))
            else:
                item.setForeground(0, QColor(PALETTE["text"]))
            self._tree.addTopLevelItem(item)

    def _on_section_clicked(self, item: QTreeWidgetItem, _col: int):
        section = item.data(0, Qt.UserRole)
        self._editor_title.setText(f"[{section}]")
        self._editor.setPlainText(self.config.get_section_text(section))
        self._editor.setReadOnly(False)
        self.status_message.emit(f"Ручная настройка: [{section}]")


# ---------------------------------------------------------------------------
# Config view tab
# ---------------------------------------------------------------------------

class ConfigViewTab(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)

        title = QLabel("Текущий конфиг")
        title.setFont(QFont("Monospace", 9, QFont.Bold))
        title.setStyleSheet(f"color: {PALETTE['blue']};")
        header.addWidget(title)

        self._stats_lbl = QLabel("—")
        self._stats_lbl.setFont(QFont("Monospace", 7))
        self._stats_lbl.setStyleSheet(f"color: {PALETTE['overlay0']};")
        header.addWidget(self._stats_lbl)
        header.addStretch()

        self._btn_refresh = QPushButton("↺  Обновить")
        self._btn_refresh.setFixedWidth(100)
        self._btn_refresh.clicked.connect(self._refresh)
        header.addWidget(self._btn_refresh)

        self._btn_copy = QPushButton("⎘  Копировать")
        self._btn_copy.setFixedWidth(110)
        self._btn_copy.clicked.connect(self._copy_all)
        header.addWidget(self._btn_copy)

        root.addLayout(header)

        self._viewer = QPlainTextEdit()
        self._viewer.setFont(QFont("Monospace", 8))
        self._viewer.setReadOnly(True)
        self._viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._viewer.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {PALETTE['crust']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['surface0']};
                border-radius: 6px;
                padding: 10px;
                selection-background-color: {PALETTE['surface0']};
            }}
        """)
        self._viewer.setPlaceholderText(
            "Загрузите конфиг через Файл → Открыть...\n\n"
            "Здесь будет отображаться полный текст файла конфигурации Polybar."
        )
        root.addWidget(self._viewer, 1)

    def load_config(self, config: PolybarConfig):
        self.config = config
        self._refresh()

    def _refresh(self):
        if not self.config.filepath:
            return
        text = self.config.get_raw_text()
        self._viewer.setPlainText(text)
        lines = text.count("\n")
        sections = len(self.config.get_all_sections())
        bars = len(self.config.bars)
        mods = len(self.config.modules)
        fname = os.path.basename(self.config.filepath or "—")
        self._stats_lbl.setText(
            f"строк: {lines}  //  секций: {sections}  //  баров: {bars}  //  модулей: {mods}  //  {fname}"
        )
        self.status_message.emit("Конфиг обновлён")

    def _copy_all(self):
        text = self._viewer.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status_message.emit("Скопировано в буфер обмена")


# ---------------------------------------------------------------------------
# Launch settings tab
# ---------------------------------------------------------------------------

class LaunchTab(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, config: PolybarConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        title = QLabel("Параметры запуска Polybar")
        title.setFont(QFont("Monospace", 10, QFont.Bold))
        title.setStyleSheet(f"color: {PALETTE['blue']};")
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE['surface0']};")
        root.addWidget(sep)

        # ── Command ──────────────────────────────────────────────────
        cmd_grp = QGroupBox("Команда запуска")
        cmd_grp.setFont(QFont("Monospace", 8))
        cg = QVBoxLayout(cmd_grp)
        cg.setSpacing(8)

        hint = QLabel(
            "По умолчанию генерируется из списка баров в конфиге.\n"
            "Можно переопределить вручную."
        )
        hint.setFont(QFont("Monospace", 7))
        hint.setStyleSheet(f"color: {PALETTE['overlay1']};")
        hint.setWordWrap(True)
        cg.addWidget(hint)

        self._auto_cb = QCheckBox("Генерировать автоматически из конфига")
        self._auto_cb.setFont(QFont("Monospace", 8))
        self._auto_cb.setChecked(True)
        self._auto_cb.stateChanged.connect(self._on_auto_toggled)
        cg.addWidget(self._auto_cb)

        self._cmd_edit = QPlainTextEdit()
        self._cmd_edit.setFont(QFont("Monospace", 9))
        self._cmd_edit.setMinimumHeight(80)
        self._cmd_edit.setMaximumHeight(120)
        self._cmd_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {PALETTE['crust']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['surface0']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        self._cmd_edit.setReadOnly(True)
        cg.addWidget(self._cmd_edit)

        btn_row = QHBoxLayout()
        self._btn_regen = QPushButton("↺  Перегенерировать")
        self._btn_regen.clicked.connect(self._regen_command)
        btn_row.addWidget(self._btn_regen)

        self._btn_copy_cmd = QPushButton("⎘  Копировать")
        self._btn_copy_cmd.clicked.connect(self._copy_command)
        btn_row.addWidget(self._btn_copy_cmd)
        btn_row.addStretch()
        cg.addLayout(btn_row)

        root.addWidget(cmd_grp)

        # ── Kill before launch ────────────────────────────────────────
        opt_grp = QGroupBox("Опции")
        opt_grp.setFont(QFont("Monospace", 8))
        og = QVBoxLayout(opt_grp)
        og.setSpacing(6)

        self._cb_killall = QCheckBox("Убивать polybar перед запуском  (killall polybar)")
        self._cb_killall.setFont(QFont("Monospace", 8))
        self._cb_killall.setChecked(True)
        self._cb_killall.stateChanged.connect(self._regen_command)
        og.addWidget(self._cb_killall)

        self._cb_disown = QCheckBox("Запускать с disown  (продолжает работать после закрытия терминала)")
        self._cb_disown.setFont(QFont("Monospace", 8))
        self._cb_disown.setChecked(False)
        self._cb_disown.stateChanged.connect(self._regen_command)
        og.addWidget(self._cb_disown)

        self._cb_log = QCheckBox("Перенаправить вывод в лог  (~/polybar.log)")
        self._cb_log.setFont(QFont("Monospace", 8))
        self._cb_log.setChecked(False)
        self._cb_log.stateChanged.connect(self._regen_command)
        og.addWidget(self._cb_log)

        # Config path override
        path_row = QHBoxLayout()
        path_lbl = QLabel("Конфиг для polybar:")
        path_lbl.setFont(QFont("Monospace", 8))
        path_lbl.setStyleSheet(f"color: {PALETTE['overlay1']};")
        self._config_path_edit = QLineEdit()
        self._config_path_edit.setFont(QFont("Monospace", 8))
        self._config_path_edit.setPlaceholderText("(оставьте пустым — не передавать -c)")
        self._config_path_edit.textChanged.connect(self._regen_command)
        self._btn_browse_cfg = QPushButton("...")
        self._btn_browse_cfg.setFixedWidth(30)
        self._btn_browse_cfg.clicked.connect(self._browse_config)
        path_row.addWidget(path_lbl)
        path_row.addWidget(self._config_path_edit, 1)
        path_row.addWidget(self._btn_browse_cfg)
        og.addLayout(path_row)

        root.addWidget(opt_grp)

        # ── Save as script ───────────────────────────────────────────
        script_grp = QGroupBox("Сохранить как скрипт запуска")
        script_grp.setFont(QFont("Monospace", 8))
        sg = QVBoxLayout(script_grp)
        sg.setSpacing(6)

        script_hint = QLabel(
            "Сохраняет команду выше как shell-скрипт (~/.config/polybar/launch.sh).\n"
            "Можно указать свой путь. Скрипт будет chmod +x."
        )
        script_hint.setFont(QFont("Monospace", 7))
        script_hint.setStyleSheet(f"color: {PALETTE['overlay1']};")
        script_hint.setWordWrap(True)
        sg.addWidget(script_hint)

        script_path_row = QHBoxLayout()
        self._script_path_edit = QLineEdit()
        self._script_path_edit.setFont(QFont("Monospace", 8))
        self._script_path_edit.setText(os.path.expanduser("~/.config/polybar/launch.sh"))
        script_path_row.addWidget(self._script_path_edit, 1)
        btn_save_script = QPushButton("💾  Сохранить скрипт")
        btn_save_script.clicked.connect(self._save_script)
        script_path_row.addWidget(btn_save_script)
        sg.addLayout(script_path_row)

        root.addWidget(script_grp)

        # ── Launch now ───────────────────────────────────────────────
        launch_row = QHBoxLayout()
        self._btn_launch = QPushButton("▶  Запустить сейчас")
        self._btn_launch.setStyleSheet(
            f"background-color: {PALETTE['blue']}22;"
            f" color: {PALETTE['blue']}; border: 1px solid {PALETTE['blue']};"
            " font-weight: bold; padding: 8px 14px;"
        )
        self._btn_launch.clicked.connect(self._launch_now)
        launch_row.addWidget(self._btn_launch)
        launch_row.addStretch()
        root.addLayout(launch_row)

        root.addStretch()

        # Initial state
        self._on_auto_toggled()

    def load_config(self, config: PolybarConfig):
        self.config = config
        # Auto-fill config path
        if config.filepath:
            self._config_path_edit.setText(config.filepath)
        self._regen_command()

    def _build_command(self) -> str:
        parts = []
        if self._cb_killall.isChecked():
            parts.append("killall polybar 2>/dev/null; sleep 0.2")

        cfg_path = self._config_path_edit.text().strip()
        cfg_flag = f" -c '{cfg_path}'" if cfg_path else ""

        bar_names = list(self.config.bars.keys()) if self.config and self.config.bars else ["main"]
        for i, bar in enumerate(bar_names):
            suffix = " &" if i < len(bar_names) - 1 else ""
            log_part = " >~/polybar.log 2>&1" if self._cb_log.isChecked() else ""
            line = f"polybar{cfg_flag} {bar}{log_part}{suffix}"
            parts.append(line)

        cmd = " && \\\n".join(parts) if parts else "polybar main"

        if self._cb_disown.isChecked():
            cmd += "\ndisown"

        return cmd

    def _regen_command(self, *_):
        if self._auto_cb.isChecked():
            cmd = self._build_command()
            self._cmd_edit.setPlainText(cmd)

    def _on_auto_toggled(self, *_):
        auto = self._auto_cb.isChecked()
        self._cmd_edit.setReadOnly(auto)
        self._btn_regen.setEnabled(auto)
        if auto:
            self._regen_command()

    def _copy_command(self):
        text = self._cmd_edit.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status_message.emit("Команда скопирована в буфер обмена")

    def _browse_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать конфиг Polybar",
            os.path.expanduser("~/.config/polybar"),
            "INI files (*.ini *.conf);;All files (*)"
        )
        if path:
            self._config_path_edit.setText(path)

    def _save_script(self):
        script_path = self._script_path_edit.text().strip()
        if not script_path:
            QMessageBox.warning(self, "Ошибка", "Укажите путь для скрипта.")
            return
        cmd = self._cmd_edit.toPlainText().strip()
        if not cmd:
            QMessageBox.warning(self, "Ошибка", "Команда пустая.")
            return
        content = f"#!/usr/bin/env bash\n# Сгенерировано neopoly v2.0\n\n{cmd}\n"
        try:
            os.makedirs(os.path.dirname(script_path), exist_ok=True)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(script_path, 0o755)
            self.status_message.emit(f"Скрипт сохранён: {script_path}")
            QMessageBox.information(
                self, "Готово",
                f"Скрипт сохранён:\n{script_path}\n\n"
                "Запустите его из ~/.xinitrc, autostart или WM-конфига."
            )
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _launch_now(self):
        cmd = self._cmd_edit.toPlainText().strip()
        if not cmd:
            return
        reply = QMessageBox.question(
            self, "Запустить",
            f"Выполнить:\n{cmd[:200]}{'...' if len(cmd)>200 else ''}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            subprocess.Popen(["bash", "-c", cmd])
            self.status_message.emit("Polybar запущен")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка запуска", str(e))


# ---------------------------------------------------------------------------
# Save options dialog
# ---------------------------------------------------------------------------

class SaveOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры сохранения")
        self.setModal(True)
        self.setFixedSize(320, 160)
        layout = QVBoxLayout(self)
        label = QLabel("Сохранять offset-x / offset-y в формате:")
        label.setFont(QFont("Monospace", 9))
        layout.addWidget(label)
        self._group = QButtonGroup(self)
        self._rb_px = QRadioButton("Пиксели (offset-x = 200)")
        self._rb_pct = QRadioButton("Проценты (offset-x = 10.4%)")
        self._rb_px.setChecked(True)
        self._group.addButton(self._rb_px)
        self._group.addButton(self._rb_pct)
        layout.addWidget(self._rb_px)
        layout.addWidget(self._rb_pct)
        layout.addSpacing(8)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    @property
    def save_as_percent(self) -> bool:
        return self._rb_pct.isChecked()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class NeopolyMainWindow(QMainWindow):
    APP_NAME = "neopoly"
    VERSION  = "2.0.0"

    def __init__(self):
        super().__init__()
        self.config = PolybarConfig(*get_screen_resolution())
        self._config_loaded = False
        self._setup_ui()
        self._apply_theme()
        self.setWindowTitle(f"{self.APP_NAME} v{self.VERSION} — Polybar Visual Configurator")
        self.setMinimumSize(960, 580)
        self.resize(1280, 760)

    def _setup_ui(self):
        self._setup_menubar()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._constructor_tab = ConstructorTab(self.config)
        self._constructor_tab.bar_moved.connect(
            lambda n, x, y: self._set_status(f"[bar/{n}]  offset-x={x}px  offset-y={y}px")
        )
        self._constructor_tab.status_message.connect(self._set_status)

        self._manual_tab = ManualEditTab(self.config)
        self._manual_tab.status_message.connect(self._set_status)

        self._modules_tab = ModulesTab(self.config)
        self._modules_tab.status_message.connect(self._set_status)

        self._config_tab = ConfigViewTab(self.config)
        self._config_tab.status_message.connect(self._set_status)

        self._backup_tab = BackupTab(self.config)
        self._backup_tab.status_message.connect(self._set_status)
        self._backup_tab.open_file_requested.connect(self._load_config)

        self._launch_tab = LaunchTab(self.config)
        self._launch_tab.status_message.connect(self._set_status)

        self._tabs.addTab(self._constructor_tab, "  Конструктор  ")
        self._tabs.addTab(self._manual_tab,       "  Ручная правка  ")
        self._tabs.addTab(self._modules_tab,      "  Модули  ")
        self._tabs.addTab(self._config_tab,       "  Конфиг  ")
        self._tabs.addTab(self._launch_tab,       "  Запуск  ")
        self._tabs.addTab(self._backup_tab,       "  Бэкапы  ")

        root.addWidget(self._tabs, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._set_status("Готов.  Файл → Создать / Открыть...  //  F5 = restart  Shift+F5 = сохранить+restart  //  v2.0")

    def _setup_menubar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("Файл")

        act_new = QAction("Создать конфиг...", self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self._on_new_config)
        file_menu.addAction(act_new)

        act_open = QAction("Открыть...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._on_open)
        file_menu.addAction(act_open)
        file_menu.addSeparator()

        self._act_save = QAction("Сохранить", self)
        self._act_save.setShortcut("Ctrl+S")
        self._act_save.setEnabled(False)
        self._act_save.triggered.connect(self._on_save)
        file_menu.addAction(self._act_save)

        self._act_save_as = QAction("Сохранить как...", self)
        self._act_save_as.setShortcut("Ctrl+Shift+S")
        self._act_save_as.setEnabled(False)
        self._act_save_as.triggered.connect(self._on_save_as)
        file_menu.addAction(self._act_save_as)
        file_menu.addSeparator()

        act_quit = QAction("Выход", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        settings_menu = mb.addMenu("Настройки")
        self._act_apply = QAction("▶  Применить — перезапустить Polybar  [F5]", self)
        self._act_apply.setShortcut("F5")
        self._act_apply.setEnabled(False)
        self._act_apply.triggered.connect(self._on_apply)
        settings_menu.addAction(self._act_apply)

        self._act_save_apply = QAction("💾  Сохранить и перезапустить  [Shift+F5]", self)
        self._act_save_apply.setShortcut("Shift+F5")
        self._act_save_apply.setEnabled(False)
        self._act_save_apply.triggered.connect(self._on_save_and_apply)
        settings_menu.addAction(self._act_save_apply)

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("app_header")
        layout = QHBoxLayout(w)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        title = QLabel(f"◈ {self.APP_NAME}")
        title.setFont(QFont("Monospace", 15, QFont.Bold))
        title.setStyleSheet(f"color: {PALETTE['blue']};")

        sub = QLabel(
            f"Polybar Visual Configurator  //  "
            f"экран: {self.config.screen_w}×{self.config.screen_h}"
        )
        sub.setFont(QFont("Monospace", 8))
        sub.setStyleSheet(f"color: {PALETTE['surface2']};")

        self._lbl_file = QLabel("Файл не выбран")
        self._lbl_file.setFont(QFont("Monospace", 7))
        self._lbl_file.setStyleSheet(f"color: {PALETTE['surface1']};")
        self._lbl_file.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addStretch()
        layout.addWidget(self._lbl_file)
        return w

    def _on_new_config(self):
        """Create a new blank polybar config from scratch."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Создать новый конфиг Polybar",
            os.path.expanduser("~/.config/polybar/config.ini"),
            "INI files (*.ini *.conf);;All files (*)"
        )
        if not path:
            return
        sw, sh = self.config.screen_w, self.config.screen_h
        template = f"""; Polybar config — создан neopoly v2.0
; Документация: https://github.com/polybar/polybar/wiki

[colors]
background = #1e1e2e
foreground = #cdd6f4
primary    = #89b4fa
secondary  = #a6e3a1
alert      = #f38ba8

[bar/main]
monitor =
width = 100%
height = 30
offset-x = 0
offset-y = 0

background = ${{colors.background}}
foreground = ${{colors.foreground}}

line-size  = 2
line-color = ${{colors.primary}}

border-size  = 0
border-color = #313244

padding-left  = 1
padding-right = 1

module-margin-left  = 1
module-margin-right = 1

font-0 = monospace:size=10

modules-left   = cpu memory
modules-center = date
modules-right  = pulseaudio

tray-position = right
tray-padding  = 2

[module/cpu]
type = internal/cpu
interval = 2
format-prefix = " CPU "
format-prefix-foreground = ${{colors.primary}}
label = %percentage%%

[module/memory]
type = internal/memory
interval = 2
format-prefix = " MEM "
format-prefix-foreground = ${{colors.secondary}}
label = %percentage_used%%

[module/date]
type = internal/date
interval = 5
date = %H:%M
label = %date%

[module/pulseaudio]
type = internal/pulseaudio
format-volume = <label-volume>
label-volume = VOL %percentage%%
label-muted  = MUTE
"""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(template)
            self._load_config(path)
            self._set_status(f"Создан новый конфиг: {path}")
            QMessageBox.information(
                self, "Готово",
                f"Новый конфиг создан:\n{path}\n\n"
                "Переместите его в ~/.config/polybar/ и настраивайте!"
            )
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_save_and_apply(self):
        """Save config then restart Polybar."""
        if not self._config_loaded or not self.config.filepath:
            return
        self._save_to(self.config.filepath)
        self._on_apply()

    def _on_open(self):
        home = os.path.expanduser("~/.config/polybar")
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть конфиг Polybar", home,
            "INI files (*.ini *.conf);;All files (*)"
        )
        if path:
            self._load_config(path)

    def _load_config(self, path: str):
        try:
            self.config.load(path)
        except (FileNotFoundError, OSError) as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return

        if not self.config.bars:
            QMessageBox.warning(
                self, "Предупреждение",
                "Секции [bar/...] с параметрами позиционирования не найдены.\n"
                "Убедитесь, что конфиг содержит width или offset-x."
            )
            return

        self._config_loaded = True

        # Auto backup before anything else
        self._backup_tab.auto_backup(path)

        self._constructor_tab.load_config(self.config)
        self._manual_tab.load_config(self.config)
        self._modules_tab.load_config(self.config)
        self._config_tab.load_config(self.config)
        self._launch_tab.load_config(self.config)

        self._act_save.setEnabled(True)
        self._act_save_as.setEnabled(True)
        self._act_apply.setEnabled(True)
        self._act_save_apply.setEnabled(True)

        self._lbl_file.setText(path)
        self._set_status(
            f"Загружено: {os.path.basename(path)}  //  "
            f"баров: {len(self.config.bars)}  //  "
            f"модулей: {len(self.config.modules)}"
        )

    def _on_save(self):
        if not self._config_loaded or not self.config.filepath:
            return
        self._save_to(self.config.filepath)

    def _on_save_as(self):
        if not self._config_loaded:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как...",
            self.config.filepath or os.path.expanduser("~"),
            "INI files (*.ini *.conf);;All files (*)"
        )
        if path:
            self._save_to(path)

    def _save_to(self, path: str):
        dlg = SaveOptionsDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            self.config.save(path, save_as_percent=dlg.save_as_percent)
            fmt = "%" if dlg.save_as_percent else "px"
            self._set_status(f"Сохранено: {path}  (формат: {fmt})")
            QMessageBox.information(self, "Успех", f"Конфиг сохранён:\n{path}")
            self._config_tab.load_config(self.config)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", str(e))

    def _on_apply(self):
        reply = QMessageBox.question(
            self, "Применить",
            "Перезапустить Polybar?\n(polybar-msg cmd restart)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            result = subprocess.run(
                ["polybar-msg", "cmd", "restart"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                self._set_status("Polybar перезапущен через polybar-msg")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        try:
            subprocess.run(["pkill", "-x", "polybar"], timeout=3)
            self._set_status("Polybar остановлен. Запустите вручную или через скрипт.")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось перезапустить Polybar:\n{e}")

    def _set_status(self, msg: str):
        self.status.showMessage(f"  {msg}")

    def _apply_theme(self):
        self.setStyleSheet(f"""
        QMainWindow, QWidget {{
            background-color: {PALETTE['base']};
            color: {PALETTE['text']};
            font-family: Monospace;
        }}
        QWidget#app_header {{
            background: {PALETTE['mantle']};
            border-bottom: 1px solid {PALETTE['surface0']};
        }}
        QMenuBar {{
            background-color: {PALETTE['crust']};
            color: {PALETTE['text']};
            font-family: Monospace;
            font-size: 9px;
            padding: 2px 0;
            border-bottom: 1px solid {PALETTE['surface0']};
        }}
        QMenuBar::item {{ padding: 4px 12px; border-radius: 3px; }}
        QMenuBar::item:selected {{ background: {PALETTE['surface0']}; }}
        QMenu {{
            background-color: {PALETTE['mantle']};
            color: {PALETTE['text']};
            border: 1px solid {PALETTE['surface1']};
            font-family: Monospace;
            font-size: 9px;
            padding: 4px;
        }}
        QMenu::item {{ padding: 6px 24px; border-radius: 3px; }}
        QMenu::item:selected {{ background: {PALETTE['surface0']}; }}
        QMenu::separator {{ height: 1px; background: {PALETTE['surface0']}; margin: 3px 8px; }}
        QTabWidget::pane {{ border: none; border-top: 1px solid {PALETTE['surface0']}; }}
        QTabBar::tab {{
            background: {PALETTE['mantle']};
            color: {PALETTE['overlay1']};
            border: none;
            padding: 8px 18px;
            font-family: Monospace;
            font-size: 9px;
            border-top: 2px solid transparent;
        }}
        QTabBar::tab:selected {{
            background: {PALETTE['base']};
            color: {PALETTE['text']};
            border-top: 2px solid {PALETTE['blue']};
        }}
        QTabBar::tab:hover {{ color: {PALETTE['text']}; }}
        QPushButton {{
            background-color: {PALETTE['surface0']};
            color: {PALETTE['text']};
            border: 1px solid {PALETTE['surface1']};
            border-radius: 5px;
            padding: 6px 10px;
            font-size: 9px;
            font-family: Monospace;
        }}
        QPushButton:hover {{
            background-color: {PALETTE['surface1']};
            border-color: {PALETTE['overlay0']};
        }}
        QPushButton:pressed {{ background-color: {PALETTE['surface2']}; }}
        QPushButton:disabled {{
            color: {PALETTE['surface1']};
            background-color: {PALETTE['mantle']};
            border-color: {PALETTE['surface0']};
        }}
        QSpinBox, QLineEdit {{
            background-color: {PALETTE['mantle']};
            color: {PALETTE['text']};
            border: 1px solid {PALETTE['surface1']};
            border-radius: 4px;
            padding: 3px 6px;
            font-family: Monospace;
            font-size: 9px;
        }}
        QSpinBox:focus, QLineEdit:focus {{ border-color: {PALETTE['blue']}; }}
        QStatusBar {{
            background-color: {PALETTE['crust']};
            color: {PALETTE['surface2']};
            font-size: 8px;
            font-family: Monospace;
            border-top: 1px solid {PALETTE['surface0']};
        }}
        QScrollArea {{ border: none; }}
        QScrollBar:vertical {{
            background: {PALETTE['mantle']};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {PALETTE['surface1']};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{
            background: {PALETTE['mantle']};
            height: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {PALETTE['surface1']};
            border-radius: 4px;
            min-width: 20px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QDialog {{ background-color: {PALETTE['base']}; }}
        QRadioButton {{ font-family: Monospace; font-size: 9px; color: {PALETTE['text']}; }}
        QDialogButtonBox QPushButton {{ min-width: 70px; }}
        QSplitter::handle {{ background: {PALETTE['surface0']}; width: 1px; height: 1px; }}
        QWidget#props_panel {{ background: {PALETTE['mantle']}; border-left: 1px solid {PALETTE['surface0']}; }}
        QGroupBox {{
            border: 1px solid {PALETTE['surface0']};
            border-radius: 6px;
            margin-top: 10px;
            padding-top: 4px;
            font-family: Monospace;
            font-size: 9px;
            color: {PALETTE['overlay1']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 6px;
            color: {PALETTE['overlay1']};
        }}
        QListWidget {{
            background: {PALETTE['crust']};
            border: 1px solid {PALETTE['surface0']};
            border-radius: 6px;
            outline: none;
        }}
        QListWidget::item {{ padding: 5px 8px; }}
        QListWidget::item:selected {{
            background: {PALETTE['surface0']};
            color: {PALETTE['blue']};
            border-radius: 3px;
        }}
        QListWidget::item:hover {{ background: {PALETTE['surface0']}50; }}
        QCheckBox {{
            font-family: Monospace;
            font-size: 9px;
            color: {PALETTE['text']};
            spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {PALETTE['surface1']};
            border-radius: 3px;
            background: {PALETTE['mantle']};
        }}
        QCheckBox::indicator:checked {{
            background: {PALETTE['blue']};
            border-color: {PALETTE['blue']};
        }}
        """)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("neopoly")
    app.setApplicationVersion("1.2.0")
    app.setFont(QFont("Monospace", 9))
    window = NeopolyMainWindow()
    window.show()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        window._load_config(sys.argv[1])
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
