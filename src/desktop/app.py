"""Standalone desktop workbench for the V8 board inspection pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
import uuid
from tkinter import filedialog, ttk
from tkinter import font as tkfont
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from .preprocess import load_bgr, prepare_image
from .diagnostics import diagnose_connection
from .protocol import BoardClient, PROTOCOL, canonical_sha256, class_domain, load_class_names, validate_class_names

HISTORY_DIR = Path(__file__).resolve().parent / "history"
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
UNIFIED_TASK = "all"
UI_FONT = "Microsoft YaHei UI"
NUMBER_FONT = "Segoe UI"
LETTER_FONT = "Segoe UI"


def _mixed_text_runs(text):
    """Separate digits, Latin letters and Chinese/punctuation for typography."""
    runs = []
    for character in str(text):
        numeric = 1 if character.isdecimal() else 2 if character.isascii() and character.isalpha() else 0
        if runs and runs[-1][0] == numeric:
            runs[-1] = (numeric, runs[-1][1] + character)
        else:
            runs.append((numeric, character))
    return runs


def _make_number_font(root, base_font):
    actual = base_font.actual()
    return tkfont.Font(root=root, family=NUMBER_FONT, size=actual["size"],
                       weight=actual["weight"], slant="roman")

def _run_font(kind, base_font, number_font):
    if kind == 1:
        return number_font
    if kind == 2:
        if not hasattr(base_font, "_letter_font"):
            actual = base_font.actual()
            base_font._letter_font = tkfont.Font(root=base_font._tk, family=LETTER_FONT,
                                                size=actual["size"], weight=actual["weight"], slant="roman")
        return base_font._letter_font
    return base_font


def _mixed_text_width(text, base_font, number_font):
    return sum(_run_font(numeric, base_font, number_font).measure(part)
               for numeric, part in _mixed_text_runs(text))


def _draw_mixed_text(canvas, text, x, y, base_font, number_font, color, *, anchor="w"):
    """Draw text runs at a shared baseline; x is the requested anchor position."""
    runs = _mixed_text_runs(text)
    width = sum(_run_font(numeric, base_font, number_font).measure(part)
                for numeric, part in runs)
    if anchor == "center":
        x -= width / 2
    elif anchor == "e":
        x -= width
    for numeric, part in runs:
        font = _run_font(numeric, base_font, number_font)
        canvas.create_text(x, y, text=part, fill=color, font=font,
                           anchor="w", tags=("mixed_text",))
        x += font.measure(part)


def _insert_mixed_text(widget, text, tag="numeric"):
    for numeric, part in _mixed_text_runs(text):
        widget.insert("end", part, (tag,) if numeric == 1 else ("latin",) if numeric == 2 else ())


class MixedLabel(tk.Canvas):
    """A small Label-like canvas that renders digits/Latin text in NUMBER_FONT."""

    _LABEL_OPTIONS = {"text", "textvariable", "font", "fg", "foreground", "anchor",
                      "justify", "wraplength", "padx", "pady"}
    _OPTION_DEFAULTS = {
        "text": ("Text", ""), "textvariable": ("Variable", ""),
        "font": ("Font", "TkDefaultFont"), "fg": ("Foreground", "black"),
        "anchor": ("Anchor", "center"), "justify": ("Justify", "center"),
        "wraplength": ("WrapLength", "0"), "padx": ("Pad", "1"),
        "pady": ("Pad", "1"),
    }

    def __init__(self, parent, *, text="", textvariable=None, font=(UI_FONT, 10),
                 fg=None, bg=None, anchor="w", justify="left", wraplength=0,
                 padx=0, pady=0, **kwargs):
        self._label_text = text
        self._textvariable = None
        self._text_trace = None
        self._font_spec = font
        self._foreground = fg or "black"
        self._anchor = anchor
        self._justify = justify
        self._wraplength = wraplength
        self._padx = padx
        self._pady = pady
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("width", 1)
        kwargs.setdefault("height", 1)
        super().__init__(parent, bg=bg, **kwargs)
        self._set_textvariable(textvariable)
        self._set_fonts(font)
        self.bind("<Configure>", self._redraw, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._redraw()

    def _set_fonts(self, font_spec):
        self._font_spec = font_spec
        self._base_font = tkfont.Font(root=self, font=font_spec)
        self._number_font = _make_number_font(self, self._base_font)

    def _set_textvariable(self, variable):
        if self._textvariable is variable:
            return
        if self._textvariable is not None and self._text_trace:
            try:
                self._textvariable.trace_remove("write", self._text_trace)
            except tk.TclError:
                pass
        self._textvariable = variable
        self._text_trace = None
        if variable is not None:
            self._label_text = variable.get()
            self._text_trace = variable.trace_add("write", self._variable_changed)

    def _variable_changed(self, *_args):
        if self._textvariable is not None:
            self._label_text = self._textvariable.get()
        self._redraw()

    def _on_destroy(self, event):
        if event.widget is self and self._textvariable is not None and self._text_trace:
            try:
                self._textvariable.trace_remove("write", self._text_trace)
            except tk.TclError:
                pass

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, str) and not kwargs:
            key = "fg" if cnf == "foreground" else cnf
            if key in self._OPTION_DEFAULTS:
                kind, default = self._OPTION_DEFAULTS[key]
                return (key, key, kind, default, self.cget(key))
            return super().configure(cnf)
        if cnf is None:
            options = {}
        elif isinstance(cnf, dict):
            options = dict(cnf)
        else:
            return super().configure(cnf, **kwargs)
        options.update(kwargs)
        canvas_options = {}
        redraw = False
        for key, value in options.items():
            if key == "text":
                self._label_text = value
                self._set_textvariable(None)
                redraw = True
            elif key == "textvariable":
                self._set_textvariable(value)
                redraw = True
            elif key == "font":
                self._set_fonts(value)
                redraw = True
            elif key in ("fg", "foreground"):
                self._foreground = value
                redraw = True
            elif key == "anchor":
                self._anchor = value
                redraw = True
            elif key == "justify":
                self._justify = value
                redraw = True
            elif key == "wraplength":
                self._wraplength = value
                redraw = True
            elif key == "padx":
                self._padx = value
                redraw = True
            elif key == "pady":
                self._pady = value
                redraw = True
            else:
                canvas_options[key] = value
        result = super().configure(canvas_options) if canvas_options else None
        if redraw:
            self._redraw()
        return result

    config = configure

    def cget(self, key):
        if key == "text":
            return self._textvariable.get() if self._textvariable is not None else self._label_text
        if key == "textvariable":
            return str(self._textvariable) if self._textvariable is not None else ""
        if key == "font":
            return self._font_spec
        if key in ("fg", "foreground"):
            return self._foreground
        if key == "anchor":
            return self._anchor
        if key == "justify":
            return self._justify
        if key == "wraplength":
            return self._wraplength
        if key == "padx":
            return self._padx
        if key == "pady":
            return self._pady
        return super().cget(key)

    def _redraw(self, _event=None):
        self.delete("all")
        text = str(self._textvariable.get() if self._textvariable is not None else self._label_text)
        width = self.winfo_width()
        wrap = int(self._wraplength or 0)
        if wrap <= 0 or width <= 1:
            wrap = 0
        else:
            wrap = min(wrap, width - 2 * int(self._padx))
        lines = []
        for logical in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = ""
            line_width = 0
            for character in logical:
                kind = 1 if character.isdecimal() else 2 if character.isascii() and character.isalpha() else 0
                font = _run_font(kind, self._base_font, self._number_font)
                character_width = font.measure(character)
                if wrap and line and line_width + character_width > wrap:
                    lines.append(line)
                    line, line_width = "", 0
                line += character
                line_width += character_width
            lines.append(line)
        line_height = max(self._base_font.metrics("linespace"),
                          self._number_font.metrics("linespace")) + 2
        widths = [_mixed_text_width(line, self._base_font, self._number_font) for line in lines]
        content_width = max(widths, default=0)
        requested_width = max(1, round(content_width + 2 * int(self._padx)))
        if self._wraplength:
            # Keep the requested width stable when a larger font wraps text;
            # using the last line's width can repeatedly shrink/reflow the grid.
            requested_width = max(1, int(self._wraplength))
        requested_height = max(1, line_height * max(1, len(lines)) + 2 * int(self._pady))
        if (self.winfo_reqwidth(), self.winfo_reqheight()) != (requested_width, requested_height):
            tk.Canvas.configure(self, width=requested_width, height=requested_height)

        canvas_width = max(width, requested_width)
        canvas_height = max(self.winfo_height(), requested_height)
        anchor = self._anchor.lower()
        if "w" in anchor:
            block_x = int(self._padx)
        elif "e" in anchor:
            block_x = canvas_width - int(self._padx) - content_width
        else:
            block_x = (canvas_width - content_width) / 2
        if "n" in anchor:
            block_y = int(self._pady)
        elif "s" in anchor:
            block_y = canvas_height - int(self._pady) - line_height * len(lines)
        else:
            block_y = (canvas_height - line_height * len(lines)) / 2
        for index, line in enumerate(lines):
            line_width = widths[index]
            if self._justify == "right":
                line_x = block_x + content_width - line_width
            elif self._justify == "center":
                line_x = block_x + (content_width - line_width) / 2
            else:
                line_x = block_x
            y = block_y + index * line_height + line_height / 2
            _draw_mixed_text(self, line, line_x, y, self._base_font,
                             self._number_font, self._foreground)

def display_class_name(name):
    return name.removeprefix("PIN_")

COLORS = {
    # Neutral dark industrial palette. Keys kept for older dialogs.
    "page": "#0d131b",
    "white": "#141c26",          # card surface
    "surface_alt": "#1b2532",    # raised controls / table headings
    "surface_hi": "#232f3e",     # hover
    "border": "#263345",
    "border_soft": "#1c2735",
    "navy": "#e6edf5",           # primary text
    "muted": "#8b9aaf",
    "faint": "#5d6c80",
    "blue": "#2f7cf6",
    "blue_hover": "#4b8ff8",
    "teal": "#1f8a8a",
    "teal_hover": "#27a0a0",
    "accent": "#4ea1ff",
    "select": "#1f3a5f",
    "preview": "#0a0f15",
    "grid": "#141c26",
    "success": "#3ccf8e",
    "warning": "#e3b341",
    "danger": "#f26d6d",
    "danger_bg": "#2b1a1f",
    "danger_border": "#5a2f37",
    "banner": "#141c26",
    "banner_border": "#263345",
    "banner_text": "#e6edf5",
    "error_bg": "#2b1a1f",
    "error_border": "#5a2f37",
    "error_text": "#ff9f9f",
    "green_bg": "#12261f",
    "green_border": "#24543f",
    "green_text": "#3ccf8e",
    "info_bg": "#141c26",
    "info_border": "#263345",
    "info_text": "#e6edf5",
    "disabled_bg": "#161e29",
    "disabled_border": "#1f2a38",
    "disabled_text": "#4f5d70",
}

# One colour per PIN class id (0..8); shared by image boxes and the table swatch.
CLASS_COLORS = ("#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#38d9a9",
                "#4dabf7", "#9775fa", "#f783ac", "#a9e34b")


def _class_color(hit):
    index = hit.get("class_id")
    if isinstance(index, int) and 0 <= index < len(CLASS_COLORS):
        return CLASS_COLORS[index]
    return "#adb5bd"


def _hex_rgb(value):
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def style_window_titlebar(window):
    """Match the native Windows caption to the workbench, keeping system controls."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.GetAncestor(window.winfo_id(), 2)
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmSetWindowAttribute.argtypes = (
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long

    def apply(attribute, value):
        setting = wintypes.DWORD(value)
        return dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting))

    def colorref(hex_color):
        red, green, blue = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return red | (green << 8) | (blue << 16)

    if apply(20, 1) != 0:
        apply(19, 1)  # Earlier Windows 10 builds use the previous attribute ID.
    apply(35, colorref(COLORS["page"]))
    apply(36, colorref(COLORS["navy"]))


class MixedTreeview(ttk.Treeview):
    """Keep native tree interactions while giving visible numeric text its own font."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._cells = []
        self._pending_draw = None
        self._font = tkfont.Font(root=self, family=UI_FONT, size=11)
        self._digits = _make_number_font(self, self._font)
        for event in ("<Configure>", "<MouseWheel>", "<KeyRelease>", "<<TreeviewSelect>>"):
            self.bind(event, self._schedule_cells, add="+")
        self.bind("<Destroy>", self._stop_cells, add="+")

    def _stop_cells(self, event):
        if event.widget is self and self._pending_draw:
            self.after_cancel(self._pending_draw)
            self._pending_draw = None

    def _schedule_cells(self, *_args):
        if not self._pending_draw:
            self._pending_draw = self.after_idle(self._draw_cells)

    def insert(self, *args, **kwargs):
        result = super().insert(*args, **kwargs)
        self._schedule_cells()
        return result

    def delete(self, *items):
        result = super().delete(*items)
        self._schedule_cells()
        return result

    def yview(self, *args):
        result = super().yview(*args)
        self._schedule_cells()
        return result

    def yview_scroll(self, *args):
        result = super().yview_scroll(*args)
        self._schedule_cells()
        return result

    def _forward_cell_click(self, event):
        self.focus_set()
        self.event_generate("<ButtonPress-1>", x=event.widget.winfo_x() + event.x,
                            y=event.widget.winfo_y() + event.y, state=event.state)
        return "break"

    def _forward_cell_release(self, event):
        self.event_generate("<ButtonRelease-1>", x=event.widget.winfo_x() + event.x,
                            y=event.widget.winfo_y() + event.y, state=event.state)
        return "break"

    def _cell_wheel(self, event):
        self.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _draw_cells(self):
        self._pending_draw = None
        for canvas in self._cells:
            canvas.destroy()
        self._cells.clear()
        selected = set(self.selection())
        columns = list(self["columns"])
        show_tree = "tree" in tuple(map(str, self["show"]))
        for item in self.get_children():
            values = self.item(item, "values")
            entries = [(column, values[i] if i < len(values) else "")
                       for i, column in enumerate(columns)]
            if show_tree:
                entries.insert(0, ("#0", self.item(item, "text")))
            for column, text in entries:
                bounds = self.bbox(item, column)
                if not bounds or not any(c.isdecimal() or (c.isascii() and c.isalpha()) for c in str(text)):
                    continue
                x, y, width, height = bounds
                fill = "#245477" if item in selected else COLORS["white"]
                canvas = tk.Canvas(self, bg=fill, bd=0, highlightthickness=0)
                canvas.place(x=x, y=y, width=width, height=height)
                start = 7
                if column == "#0":
                    images = self.item(item, "image")
                    if images:
                        canvas.create_image(5, height / 2, image=images[0], anchor="w")
                        start = 5 + int(self.tk.call("image", "width", images[0])) + 5
                _draw_mixed_text(canvas, text, start, height / 2,
                                 self._font, self._digits, COLORS["navy"])
                canvas.bind("<ButtonPress-1>", self._forward_cell_click)
                canvas.bind("<ButtonRelease-1>", self._forward_cell_release)
                canvas.bind("<MouseWheel>", self._cell_wheel)
                self._cells.append(canvas)


class MixedEntry(tk.Text):
    """Single-line settings field with separate letter and digit fonts."""

    def __init__(self, parent, *, textvariable, **kwargs):
        kwargs.pop("font", None)
        super().__init__(parent, height=1, wrap="none", font=(UI_FONT, 10), **kwargs)
        self.variable = textvariable
        self._syncing = False
        self.tag_configure("numeric", font=(NUMBER_FONT, 10))
        self.tag_configure("latin", font=(LETTER_FONT, 10))
        self._trace = self.variable.trace_add("write", self._from_variable)
        self.bind("<<Modified>>", self._from_input)
        self.bind("<Return>", self._submit)
        self.bind("<Destroy>", self._cleanup)
        self._from_variable()

    def _submit(self, _event):
        self.winfo_toplevel().event_generate("<Return>")
        return "break"

    def _cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self._trace)

    def _from_variable(self, *_args):
        if self._syncing:
            return
        self._syncing = True
        self.delete("1.0", "end")
        _insert_mixed_text(self, self.variable.get())
        self.edit_modified(False)
        self._syncing = False

    def _from_input(self, _event):
        if self._syncing or not self.edit_modified():
            return
        self._syncing = True
        text = self.get("1.0", "end-1c")
        if "\n" in text or "\r" in text:
            text = text.replace("\n", "").replace("\r", "")
            self.delete("1.0", "end")
            self.insert("1.0", text)
        self.variable.set(text)
        self.tag_remove("numeric", "1.0", "end")
        self.tag_remove("latin", "1.0", "end")
        for index, character in enumerate(text):
            tag = "numeric" if character.isdecimal() else "latin" if character.isascii() and character.isalpha() else None
            if tag:
                self.tag_add(tag, f"1.0+{index}c", f"1.0+{index + 1}c")
        self.edit_modified(False)
        self._syncing = False


def _rounded_photo(widget, width, height, radius, fill, outline, background):
    """Anti-aliased rounded rectangle, rendered at 3x and downsampled.

    Images belong to one Tk interpreter, so the cache lives on the root.
    """
    root = widget._root()
    cache = root.__dict__.setdefault("_rounded_cache", {})
    key = (width, height, radius, fill, outline, background)
    photo = cache.get(key)
    if photo is not None:
        return photo
    factor = 3
    big = Image.new("RGB", (width * factor, height * factor), _hex_rgb(background))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, width * factor - 1, height * factor - 1),
                           radius=radius * factor, fill=_hex_rgb(fill),
                           outline=_hex_rgb(outline), width=factor)
    photo = ImageTk.PhotoImage(big.resize((width, height), Image.Resampling.LANCZOS), master=root)
    if len(cache) > 256:
        cache.clear()
    cache[key] = photo
    return photo


class RoundedButton(tk.Canvas):
    """Canvas button sized from its font, so it follows Windows display scaling.

    variant: primary (main action), secondary, ghost (low emphasis), danger.
    """

    def __init__(self, parent, text, command, *, variant="secondary", background=None,
                 foreground=None, hover=None, border=None, width=None, height=None,
                 radius=7, font=None, padx=16, pady=7, min_texts=(), **kwargs):
        self._font = tkfont.Font(root=parent, font=font or (UI_FONT, 10, "bold"))
        texts = (text,) + tuple(min_texts)
        natural_w = max(self._font.measure(t) for t in texts) + 2 * padx
        natural_h = self._font.metrics("linespace") + 2 * pady
        width = max(natural_w, width or 0)
        height = max(natural_h, height or 0)
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0,
                         bg=parent.cget("bg"), cursor="hand2", takefocus=True, **kwargs)
        self.text, self.command = text, command
        self.variant = variant
        self._custom = (background, foreground, hover, border)
        self.radius = radius
        self.height = height
        self.enabled = True
        self.hovering = False
        self.focused = False
        self._photo = None
        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self._draw()

    def configure(self, cnf=None, **kwargs):
        state = kwargs.pop("state", None)
        text = kwargs.pop("text", None)
        if text is not None:
            self.text = text
        if "radius" in kwargs:
            self.radius = kwargs.pop("radius")
        result = super().configure(cnf, **kwargs)
        if state is not None:
            self.enabled = state != "disabled"
            super().configure(cursor="hand2" if self.enabled else "arrow")
        if state is not None or text is not None or kwargs:
            self._draw()
        return result

    config = configure

    def _colors(self):
        page = self.cget("bg")
        custom_bg, custom_fg, custom_hover, custom_border = self._custom
        if not self.enabled:
            if self.variant == "ghost":
                return page, page, COLORS["disabled_text"]
            return COLORS["disabled_bg"], COLORS["disabled_border"], COLORS["disabled_text"]
        hover = self.hovering
        if self.variant == "primary":
            fill = COLORS["blue_hover"] if hover else (custom_bg or COLORS["blue"])
            outline, fg = fill, custom_fg or "#ffffff"
        elif self.variant == "danger":
            fill = "#3a2026" if hover else COLORS["surface_alt"]
            outline, fg = COLORS["danger_border"], COLORS["danger"]
        elif self.variant == "ghost":
            fill = COLORS["surface_alt"] if hover else page
            outline = fill
            fg = COLORS["navy"] if hover else COLORS["muted"]
        else:
            fill = (custom_hover or COLORS["surface_hi"]) if hover else (custom_bg or COLORS["surface_alt"])
            outline = custom_border or COLORS["border"]
            fg = custom_fg or COLORS["navy"]
        if self.focused:
            outline = COLORS["accent"]
        return fill, outline, fg

    def _draw(self, _event=None):
        self.delete("all")
        width = max(4, self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width")))
        height = max(4, self.winfo_height() if self.winfo_height() > 1 else int(self.cget("height")))
        radius = min(self.radius, height // 2, width // 2)
        fill, outline, foreground = self._colors()
        self._photo = _rounded_photo(self, width, height, radius, fill, outline, self.cget("bg"))
        self.create_image(0, 0, image=self._photo, anchor="nw")
        self.create_text(width // 2, height // 2, text=self.text, fill=foreground, font=self._font)

    def _enter(self, _event=None):
        self.hovering = True
        self._draw()

    def _leave(self, _event=None):
        self.hovering = False
        self._draw()

    def _focus_in(self, _event=None):
        self.focused = True
        self._draw()

    def _focus_out(self, _event=None):
        self.focused = False
        self._draw()

    def _click(self, _event=None):
        if self.enabled:
            self.focus_set()
            self.command()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_PIL_LABEL_FONTS = {}


def _label_font(size):
    """Chinese-capable font for on-image labels (display only)."""
    if size not in _PIL_LABEL_FONTS:
        windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates = [windows / "msyhbd.ttc", windows / "msyh.ttc", windows / "simhei.ttf",
                      Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
                      Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
        font = None
        for candidate in candidates:
            try:
                font = ImageFont.truetype(str(candidate), size=size)
                break
            except OSError:
                continue
        _PIL_LABEL_FONTS[size] = font or ImageFont.load_default()
    return _PIL_LABEL_FONTS[size]


def _confidence_font(size):
    return _label_font(size)


def draw_detections(source_bgr, detections):
    """Draw board-returned boxes; keep the original public helper signature.

    Each box gets a filled tag "<n> <class> <score%>" whose number matches the
    row number in the details table. Drawing only; detections are unchanged.
    """
    image = source_bgr.copy()
    if not detections:
        return image
    height, width = image.shape[:2]
    short_side = max(1, min(height, width))
    thickness = max(2, round(short_side / 260))
    font_size = max(13, round(short_side / 30))
    font = _label_font(font_size)
    display = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(display)
    for index, hit in enumerate(detections, start=1):
        x1, y1, x2, y2 = (round(v) for v in hit["xyxy"])
        rgb = _hex_rgb(_class_color(hit))
        draw.rectangle((x1, y1, x2, y2), outline=rgb, width=thickness)
        label = f"{index} {display_class_name(hit.get('class_name', ''))} {hit['score'] * 100:.0f}%"
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        text_w, text_h = right - left, bottom - top
        pad = max(3, font_size // 4)
        tag_w, tag_h = text_w + 2 * pad, text_h + 2 * pad
        tag_x = min(max(0, x1 - thickness // 2), max(0, width - tag_w))
        tag_y = y1 - tag_h if y1 - tag_h >= 0 else min(max(0, y1), max(0, height - tag_h))
        draw.rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), fill=rgb)
        draw.text((tag_x + pad - left, tag_y + pad - top), label, font=font, fill=(10, 14, 20))
    return cv2.cvtColor(np.asarray(display), cv2.COLOR_RGB2BGR)


class App:
    """PIN9 640x640 Tk workbench that submits images to the configured endpoint."""

    def __init__(self, root: tk.Tk, *, host: str, port: int, model: Path, names: list[str],
                 allow_host_reference: bool, timeout: float, local_address: str | None = None,
                 interface_index: int | None = None):
        self.root = root
        self.host, self.port, self.model = host, port, model
        self.names = validate_class_names(names)
        self.allow_host_reference = allow_host_reference
        self.local_address, self.interface_index = local_address, interface_index
        self.model_hash = sha256_file(model)
        self.timeout = timeout

        self.image_paths: list[Path] = []
        self.records: dict[str, dict] = {}
        self.active_path: Path | None = None
        self.events: queue.Queue = queue.Queue()
        self.cancel_pending = threading.Event()
        self.busy = False
        self.playback_paused = False
        self._playback_timer = None
        self._playback_generation = 0
        self._image_inflight = False
        self._closed = False
        self.probing = False
        self.history_errors = 0
        self.photos: dict[str, ImageTk.PhotoImage | None] = {"source": None, "result": None}
        self.empty_preview_photos: dict[str, ImageTk.PhotoImage] = {}
        self.thumbnail_photos: dict[str, ImageTk.PhotoImage] = {}
        self._queue_iids: dict[str, str] = {}
        self.preview_source = None
        self.preview_result = None
        self.preview_path: str | None = None
        self._preview_resize_pending = False
        self._active_started_at: float | None = None
        self.last_diagnostics: dict | None = None

        self.endpoint_text = tk.StringVar()
        self.status_text = tk.StringVar(value="请检查设备连接后添加图片，开始缺陷检测")
        self.count_text = tk.StringVar(value="0 张")
        self.result_summary = tk.StringVar(value="检测详情")
        self.live_text = tk.StringVar(value="空闲 · 等待检测任务")
        self.include_subfolders = tk.BooleanVar(value=False)
        self.playback_delay = tk.DoubleVar(value=3.0)

        self.root.title("PIN 9类光电缺陷检测 · YOLOv8n 640")
        self.root.configure(bg=COLORS["page"])
        self.root.geometry("1500x1000")
        self.root.minsize(960, 600)
        if os.name == "nt" and self.root.state() != "withdrawn":
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self._set_fonts_and_styles()
        self._build_compact_layout()
        self._update_endpoint_label()
        self.detect_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.remove_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        self._set_status(self.status_text.get(), "info")
        self.root.after(100, self._poll)
        self.root.after_idle(lambda: style_window_titlebar(self.root))
        self.root.bind("<Map>", lambda event: self.root.after(
            20, lambda: style_window_titlebar(self.root)) if event.widget is self.root else None, add="+")
        self.root.bind("<Destroy>", self._on_playback_destroy, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _px(self, value):
        """Scale a 96-dpi pixel size to the current Tk scaling."""
        return max(1, round(value * self.ui_scale))

    def _set_fonts_and_styles(self):
        try:
            self.ui_scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        except tk.TclError:
            self.ui_scale = 1.0
        font = (UI_FONT, 10)
        self.root.option_add("*Font", font)
        self.root.option_add("*insertBackground", COLORS["accent"])
        self.root.option_add("*selectBackground", COLORS["select"])
        self.root.option_add("*selectForeground", COLORS["navy"])
        self.root.option_add("*TCombobox*Listbox.background", COLORS["surface_alt"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["navy"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["select"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", COLORS["navy"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        heading_font = (UI_FONT, 9, "bold")
        for name, row_height in (("Workbench.Treeview", 30), ("Queue.Treeview", 54)):
            style.configure(name, font=font, rowheight=self._px(row_height),
                            background=COLORS["white"], fieldbackground=COLORS["white"],
                            foreground=COLORS["navy"], bordercolor=COLORS["white"],
                            lightcolor=COLORS["white"], darkcolor=COLORS["white"], borderwidth=0)
            style.map(name, background=[("selected", COLORS["select"])],
                      foreground=[("selected", COLORS["navy"])])
            style.configure(name + ".Heading", font=heading_font, background=COLORS["surface_alt"],
                            foreground=COLORS["muted"], relief="flat", borderwidth=0,
                            bordercolor=COLORS["border_soft"], lightcolor=COLORS["surface_alt"],
                            darkcolor=COLORS["surface_alt"], padding=(self._px(10), self._px(6)))
            style.map(name + ".Heading", background=[("active", COLORS["surface_hi"])],
                      foreground=[("active", COLORS["navy"])])
        style.layout("Workbench.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.layout("Queue.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("TCombobox", fieldbackground=COLORS["surface_alt"],
                        background=COLORS["surface_alt"], foreground=COLORS["navy"],
                        arrowcolor=COLORS["accent"], bordercolor=COLORS["border"],
                        lightcolor=COLORS["border"], darkcolor=COLORS["border"], padding=(8, 5))
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface_alt"]),
                                                 ("disabled", COLORS["white"])],
                  foreground=[("readonly", COLORS["navy"]), ("disabled", COLORS["muted"])],
                  selectbackground=[("readonly", COLORS["surface_alt"])],
                  selectforeground=[("readonly", COLORS["navy"])])
        style.configure("TCheckbutton", background=COLORS["white"], foreground=COLORS["muted"],
                        font=(UI_FONT, 9), padding=2, indicatorcolor=COLORS["surface_alt"],
                        indicatorbackground=COLORS["surface_alt"], bordercolor=COLORS["border"])
        style.map("TCheckbutton", background=[("active", COLORS["white"])],
                  foreground=[("disabled", COLORS["disabled_text"]), ("active", COLORS["navy"])],
                  indicatorcolor=[("selected", COLORS["accent"]), ("active", COLORS["surface_hi"])])
        style.configure("TEntry", fieldbackground=COLORS["surface_alt"], foreground=COLORS["navy"],
                        insertcolor=COLORS["accent"], bordercolor=COLORS["border"],
                        lightcolor=COLORS["border"], darkcolor=COLORS["border"], padding=6)
        # Slim scrollbar without arrow buttons.
        style.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
            "sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Slim.Vertical.TScrollbar", troughcolor=COLORS["white"],
                        background=COLORS["surface_hi"], bordercolor=COLORS["white"],
                        lightcolor=COLORS["surface_hi"], darkcolor=COLORS["surface_hi"],
                        gripcount=0, arrowsize=self._px(8), width=self._px(8))
        style.map("Slim.Vertical.TScrollbar", background=[("active", COLORS["border"])])
        style.configure("Vertical.TScrollbar", background=COLORS["surface_alt"],
                        troughcolor=COLORS["page"], arrowcolor=COLORS["muted"],
                        bordercolor=COLORS["page"], lightcolor=COLORS["surface_alt"],
                        darkcolor=COLORS["surface_alt"], gripcount=0)
        style.configure("Resource.Horizontal.TProgressbar", troughcolor=COLORS["surface_alt"],
                        background=COLORS["accent"], bordercolor=COLORS["border"],
                        lightcolor=COLORS["accent"], darkcolor=COLORS["accent"], thickness=8)

    def _build_compact_layout(self):
        px = self._px
        page, card = COLORS["page"], COLORS["white"]
        pad = px(16)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(3, weight=1)

        # ---- header: title, live indicators, secondary navigation ----
        header = tk.Frame(self.root, bg=page)
        header.grid(row=0, column=0, sticky="ew", padx=pad, pady=(px(12), px(10)))
        header.grid_columnconfigure(1, weight=1)
        title = tk.Frame(header, bg=page)
        title.grid(row=0, column=0, sticky="w")
        tk.Label(title, text="PIN 光电缺陷检测", bg=page, fg=COLORS["navy"],
                 font=(UI_FONT, 16, "bold")).pack(side="left")
        tk.Label(title, text="YOLOv8n  ·  INT8  ·  640×640  ·  9 类", bg=page, fg=COLORS["muted"],
                 font=(UI_FONT, 10)).pack(side="left", padx=(px(14), 0), pady=(px(4), 0))
        indicators = tk.Frame(header, bg=page)
        indicators.grid(row=0, column=2, sticky="e")
        self.conn_pill, self.conn_dot, self.conn_label = self._pill(indicators)
        self.conn_pill.pack(side="left")
        self.run_pill, self.run_dot, self.run_label = self._pill(indicators)
        self.run_pill.pack(side="left", padx=(px(8), px(14)))
        tk.Frame(indicators, bg=COLORS["border"], width=1, height=px(22)).pack(side="left", padx=(0, px(6)))
        small = (UI_FONT, 10)
        self.history_button = RoundedButton(indicators, "历史", self.show_history, variant="ghost",
                                            font=small, padx=px(10), pady=px(5))
        self.history_button.pack(side="left")
        self.settings_button = RoundedButton(indicators, "高级设置", self.open_settings, variant="ghost",
                                             font=small, padx=px(10), pady=px(5))
        self.settings_button.pack(side="left")
        self.help_button = RoundedButton(indicators, "帮助", self.show_help, variant="ghost",
                                         font=small, padx=px(10), pady=px(5))
        self.help_button.pack(side="left")

        # ---- main action bar ----
        actions = tk.Frame(self.root, bg=page)
        actions.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, px(10)))
        def separator():
            tk.Frame(actions, bg=COLORS["border"], width=1, height=px(24)).pack(
                side="left", padx=px(10))
        self.connect_button = RoundedButton(actions, "检查连接", self.check_connection, padx=px(16))
        self.connect_button.pack(side="left")
        separator()
        self.choose_button = RoundedButton(actions, "导入图片", self.choose_images, padx=px(16))
        self.choose_button.pack(side="left")
        self.folder_button = RoundedButton(actions, "导入文件夹", self.choose_folder, padx=px(16))
        self.folder_button.pack(side="left", padx=(px(8), 0))
        separator()
        self.detect_button = RoundedButton(actions, "开始检测", self.start_batch, variant="primary",
                                           padx=px(24))
        self.detect_button.pack(side="left")
        self.pause_button = RoundedButton(actions, "暂停", self.toggle_playback, padx=px(16),
                                          min_texts=("继续",))
        self.pause_button.configure(state="disabled")
        self.pause_button.pack(side="left", padx=(px(8), 0))
        self.stop_button = RoundedButton(actions, "停止后续", self.stop_pending, variant="danger",
                                         padx=px(16))
        self.stop_button.configure(state="disabled")
        self.stop_button.pack(side="left", padx=(px(8), 0))

        self.save_button = RoundedButton(actions, "保存结果", self.save_batch, padx=px(16))
        self.save_button.configure(state="disabled")
        self.save_button.pack(side="right")
        dwell = tk.Frame(actions, bg=page)
        dwell.pack(side="right", padx=(0, px(14)))
        tk.Label(dwell, text="结果停留", bg=page, fg=COLORS["muted"], font=small).pack(side="left")
        self.playback_delay_input = tk.Spinbox(
            dwell, from_=0, to=30, increment=0.5, width=4, justify="center",
            textvariable=self.playback_delay, font=(NUMBER_FONT, 10),
            bg=COLORS["surface_alt"], fg=COLORS["navy"], disabledbackground=COLORS["disabled_bg"],
            disabledforeground=COLORS["disabled_text"], readonlybackground=COLORS["surface_alt"],
            buttonbackground=COLORS["surface_hi"], insertbackground=COLORS["accent"],
            relief="flat", bd=0, highlightthickness=1, highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"])
        self.playback_delay_input.pack(side="left", padx=px(6), ipady=px(4))
        tk.Label(dwell, text="秒", bg=page, fg=COLORS["muted"], font=small).pack(side="left")

        # ---- status line ----
        self.banner = tk.Frame(self.root, bg=COLORS["banner"], highlightthickness=1,
                               highlightbackground=COLORS["banner_border"])
        self.banner.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, px(10)))
        self.banner.grid_columnconfigure(2, weight=1)
        self.banner_strip = tk.Frame(self.banner, bg=COLORS["accent"], width=px(3))
        self.banner_strip.grid(row=0, column=0, sticky="ns")
        self.status_icon = tk.Label(self.banner, text="ⓘ", bg=COLORS["banner"], fg=COLORS["accent"],
                                    font=(UI_FONT, 11, "bold"), width=2)
        self.status_icon.grid(row=0, column=1, padx=(px(8), 0))
        self.status_label = tk.Label(self.banner, textvariable=self.status_text, anchor="w",
                                     justify="left", bg=COLORS["banner"], fg=COLORS["banner_text"],
                                     font=(UI_FONT, 10))
        self.status_label.grid(row=0, column=2, sticky="ew", padx=(px(4), px(8)), pady=px(8))
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(
            wraplength=max(200, event.width - 4)), add="+")
        self.diagnostics_button = RoundedButton(self.banner, "诊断详情", self.show_diagnostics,
                                                variant="ghost", font=small, padx=px(10), pady=px(4))
        self.diagnostics_button.configure(state="disabled")
        self.diagnostics_button.grid(row=0, column=3, padx=px(6))

        # ---- work area: queue | previews + details ----
        work = tk.Frame(self.root, bg=page)
        work.grid(row=3, column=0, sticky="nsew", padx=pad, pady=(0, px(8)))
        work.grid_columnconfigure(0, minsize=px(360), weight=0)
        self._work = work
        work.grid_columnconfigure(1, weight=1)
        work.grid_rowconfigure(0, weight=1)

        sidebar = self._card(work)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, px(10)))
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(1, weight=1)
        side_header = tk.Frame(sidebar, bg=card)
        side_header.grid(row=0, column=0, sticky="ew", padx=px(14), pady=(px(12), px(8)))
        tk.Label(side_header, text="图片队列", bg=card, fg=COLORS["navy"],
                 font=(UI_FONT, 11, "bold")).pack(side="left")
        tk.Label(side_header, textvariable=self.count_text, bg=COLORS["surface_alt"],
                 fg=COLORS["muted"], font=(UI_FONT, 9), padx=px(8), pady=px(1)).pack(side="right")
        queue_body = tk.Frame(sidebar, bg=card)
        queue_body.grid(row=1, column=0, sticky="nsew", padx=(px(6), px(4)))
        queue_body.grid_columnconfigure(0, weight=1)
        queue_body.grid_rowconfigure(0, weight=1)
        self.queue_list = ttk.Treeview(queue_body, style="Queue.Treeview", columns=("status", "time"),
                                       show="tree headings", selectmode="extended")
        self.queue_list.heading("#0", text="图片", anchor="w")
        self.queue_list.heading("status", text="状态", anchor="w")
        self.queue_list.heading("time", text="耗时", anchor="e")
        self.queue_list.column("#0", width=px(120), minwidth=px(100), stretch=True)
        self.queue_list.column("status", width=px(74), minwidth=px(66), stretch=False, anchor="w")
        self.queue_list.column("time", width=px(62), minwidth=px(56), stretch=False, anchor="e")
        for tag, color in (("待检测", COLORS["navy"]), ("正在检测", COLORS["accent"]),
                           ("已完成", COLORS["navy"]), ("检测失败", COLORS["danger"]),
                           ("已取消", COLORS["faint"])):
            self.queue_list.tag_configure(tag, foreground=color)
        self.queue_list.grid(row=0, column=0, sticky="nsew")
        queue_scroll = ttk.Scrollbar(queue_body, orient="vertical", command=self.queue_list.yview,
                                     style="Slim.Vertical.TScrollbar")
        queue_scroll.grid(row=0, column=1, sticky="ns", padx=(px(2), 0))
        self.queue_list.configure(yscrollcommand=queue_scroll.set)
        self.queue_empty_label = tk.Label(
            queue_body, text="暂无图片\n点击上方“导入图片”或“导入文件夹”", bg=card,
            fg=COLORS["faint"], justify="center", font=(UI_FONT, 10))
        self.queue_empty_label.place(relx=0.5, rely=0.45, anchor="center")
        self.queue_list.bind("<<TreeviewSelect>>", self._on_queue_select)
        self.queue_list.bind("<Double-Button-1>", self._on_queue_select)
        side_footer = tk.Frame(sidebar, bg=card)
        side_footer.grid(row=2, column=0, sticky="ew", padx=px(10), pady=px(8))
        side_footer.grid_columnconfigure(0, weight=1)
        ttk.Checkbutton(side_footer, text="导入时包含子文件夹", variable=self.include_subfolders).grid(
            row=0, column=0, sticky="w")
        self.remove_button = RoundedButton(side_footer, "移除选中", self.remove_selected, variant="ghost",
                                           font=(UI_FONT, 9), padx=px(8), pady=px(4))
        self.remove_button.grid(row=0, column=1)
        self.clear_button = RoundedButton(side_footer, "清空", self.clear_images, variant="ghost",
                                          font=(UI_FONT, 9), padx=px(8), pady=px(4))
        self.clear_button.grid(row=0, column=2)

        right = tk.Frame(work, bg=page)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        previews = tk.Frame(right, bg=page)
        previews.grid(row=0, column=0, sticky="nsew", pady=(0, px(10)))
        previews.grid_columnconfigure(0, weight=1, uniform="preview")
        previews.grid_columnconfigure(1, weight=1, uniform="preview")
        previews.grid_rowconfigure(0, weight=1)
        self.source_meta = tk.StringVar(value="")
        self.result_meta = tk.StringVar(value="")
        self.source_preview, self.source_image = self._preview_card(previews, "原图", self.source_meta)
        self.source_preview.grid(row=0, column=0, sticky="nsew", padx=(0, px(5)))
        self.result_preview, self.result_image = self._preview_card(previews, "检测结果", self.result_meta)
        self.result_preview.grid(row=0, column=1, sticky="nsew", padx=(px(5), 0))
        self.result_meta_label = self.result_preview._meta_label
        previews.bind("<Configure>", self._schedule_preview_resize)

        details_card = self._card(right)
        details_card.grid(row=1, column=0, sticky="nsew")
        details_card.grid_columnconfigure(0, weight=1)
        details_card.grid_rowconfigure(1, weight=1)
        details_header = tk.Frame(details_card, bg=card)
        details_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=px(14), pady=(px(10), px(8)))
        details_header.grid_columnconfigure(1, weight=1)
        tk.Label(details_header, text="检测详情", bg=card, fg=COLORS["navy"],
                 font=(UI_FONT, 11, "bold")).grid(row=0, column=0, sticky="w")
        self.detail_file = tk.StringVar(value="未选择图片")
        tk.Label(details_header, textvariable=self.detail_file, bg=card, fg=COLORS["muted"],
                 font=(UI_FONT, 10), anchor="w").grid(row=0, column=1, sticky="ew", padx=(px(12), px(8)))
        chips = tk.Frame(details_header, bg=card)
        chips.grid(row=0, column=2, sticky="e")
        self.detail_count_chip = self._chip(chips, "缺陷")
        self.detail_count_chip.pack(side="left")
        self.detail_time_chip = self._chip(chips, "单张耗时")
        self.detail_time_chip.pack(side="left", padx=(px(8), 0))
        self.table = ttk.Treeview(details_card, style="Workbench.Treeview",
                                  columns=("class", "score", "box"), show="tree headings", height=4)
        self.table.heading("#0", text="序号", anchor="w")
        self.table.column("#0", width=px(70), minwidth=px(60), stretch=False, anchor="w")
        for key, title, width, anchor, stretch in (
                ("class", "缺陷类别", 180, "w", False), ("score", "置信度", 110, "center", False),
                ("box", "框坐标  x1, y1, x2, y2", 260, "w", True)):
            self.table.heading(key, text=title, anchor=anchor)
            self.table.column(key, width=px(width), minwidth=px(60), anchor=anchor, stretch=stretch)
        self.table.tag_configure("odd", background=COLORS["white"])
        self.table.tag_configure("even", background="#17202b")
        self.table.tag_configure("note", foreground=COLORS["success"])
        self.table.tag_configure("error", foreground=COLORS["danger"])
        self.table.grid(row=1, column=0, sticky="nsew", padx=(px(6), 0), pady=(0, px(8)))
        table_scroll = ttk.Scrollbar(details_card, orient="vertical", command=self.table.yview,
                                     style="Slim.Vertical.TScrollbar")
        table_scroll.grid(row=1, column=1, sticky="ns", padx=(px(2), px(4)), pady=(0, px(8)))
        self.table_scroll = table_scroll
        self.table.configure(yscrollcommand=table_scroll.set)
        self._swatches = {}

        # ---- footer: endpoint / identity ----
        footer = tk.Frame(self.root, bg=page)
        footer.grid(row=4, column=0, sticky="ew", padx=pad, pady=(0, px(8)))
        self.endpoint_label = tk.Label(footer, textvariable=self.endpoint_text, bg=page,
                                       fg=COLORS["faint"], anchor="w", font=(UI_FONT, 9))
        self.endpoint_label.pack(side="left")
        tk.Label(footer, text="推理在 Z100 开发板执行 · 电脑端负责预处理、通信、显示与保存",
                 bg=page, fg=COLORS["faint"], font=(UI_FONT, 9)).pack(side="right")
        self.conn_state = "unknown"
        self.run_state = "idle"
        self._refresh_indicators()
        self._density = None
        self.root.bind("<Configure>", self._on_root_configure, add="+")

    def _on_root_configure(self, event):
        if event.widget is not self.root or self._closed:
            return
        # Images stay the visual centre: on small windows the queue narrows and
        # the details table shows fewer rows (it scrolls) before previews shrink.
        width, height = event.width / self.ui_scale, event.height / self.ui_scale
        density = (0 if width < 1280 else 1, 2 if height < 720 else 3 if height < 880 else 4)
        if density == self._density:
            return
        self._density = density
        self._work.grid_columnconfigure(0, minsize=self._px(280 if density[0] == 0 else 360))
        self.table.configure(height=density[1])

    def _pill(self, parent):
        frame = tk.Frame(parent, bg=COLORS["surface_alt"], highlightthickness=1,
                         highlightbackground=COLORS["border"])
        dot = tk.Label(frame, text="●", bg=COLORS["surface_alt"], fg=COLORS["faint"], font=(UI_FONT, 8))
        dot.pack(side="left", padx=(self._px(10), self._px(5)), pady=self._px(3))
        label = tk.Label(frame, text="", bg=COLORS["surface_alt"], fg=COLORS["navy"], font=(UI_FONT, 10))
        label.pack(side="left", padx=(0, self._px(12)), pady=self._px(3))
        return frame, dot, label

    def _chip(self, parent, caption):
        frame = tk.Frame(parent, bg=COLORS["surface_alt"])
        tk.Label(frame, text=caption, bg=COLORS["surface_alt"], fg=COLORS["muted"],
                 font=(UI_FONT, 9)).pack(side="left", padx=(self._px(8), self._px(4)), pady=self._px(2))
        value = tk.Label(frame, text="—", bg=COLORS["surface_alt"], fg=COLORS["navy"],
                         font=(NUMBER_FONT, 10, "bold"))
        value.pack(side="left", padx=(0, self._px(8)), pady=self._px(2))
        frame.value = value
        return frame

    def _refresh_indicators(self):
        if not hasattr(self, "conn_label"):
            return
        conn_text, conn_color = {
            "unknown": ("开发板 · 未连接", COLORS["faint"]),
            "checking": ("开发板 · 连接中…", COLORS["warning"]),
            "ok": ("开发板 · 已连接", COLORS["success"]),
            "fail": ("开发板 · 连接失败", COLORS["danger"]),
        }[self.conn_state]
        total = len(getattr(self, "_playback_paths", []) or [])
        index = getattr(self, "_playback_index", 0)
        if self.busy:
            if self.cancel_pending.is_set():
                run_text, run_color = "正在停止", COLORS["warning"]
            elif self.playback_paused:
                run_text, run_color = f"已暂停  {index}/{total}", COLORS["warning"]
            else:
                run_text, run_color = f"检测中  {index}/{total}", COLORS["accent"]
        elif self.probing:
            run_text, run_color = "连接检查中", COLORS["warning"]
        else:
            run_text, run_color = {
                "idle": ("空闲", COLORS["faint"]),
                "done": ("检测完成", COLORS["success"]),
                "partial": ("部分失败", COLORS["danger"]),
                "stopped": ("已停止", COLORS["warning"]),
            }[self.run_state]
        self.conn_dot.configure(fg=conn_color)
        self.conn_label.configure(text=conn_text)
        self.run_dot.configure(fg=run_color)
        self.run_label.configure(text=run_text)

    def _button(self, parent, text, command, color):
        return RoundedButton(parent, text, command, variant="primary")

    def _toolbar_button(self, parent, text, command, disabled=False):
        button = RoundedButton(parent, text, command)
        if disabled:
            button.configure(state="disabled")
        return button

    def _card(self, parent):
        return tk.Frame(parent, bg=COLORS["white"], highlightthickness=1,
                        highlightbackground=COLORS["border_soft"], bd=0)

    def _preview_card(self, parent, title, meta_var=None):
        card = self._card(parent)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        head = tk.Frame(card, bg=COLORS["white"])
        head.grid(row=0, column=0, sticky="ew", padx=self._px(14), pady=(self._px(10), self._px(8)))
        tk.Label(head, text=title, bg=COLORS["white"], fg=COLORS["navy"],
                 font=(UI_FONT, 11, "bold")).pack(side="left")
        meta = tk.Label(head, textvariable=meta_var, bg=COLORS["white"], fg=COLORS["muted"],
                        font=(UI_FONT, 9), anchor="e")
        meta.pack(side="right")
        card._meta_label = meta
        body = tk.Frame(card, bg=COLORS["preview"])
        body.grid(row=1, column=0, sticky="nsew", padx=self._px(8), pady=(0, self._px(8)))
        placeholder = "请选择图片" if title == "原图" else "检测结果将在此显示"
        image = tk.Label(body, text=placeholder, bg=COLORS["preview"], fg=COLORS["faint"],
                         font=(UI_FONT, 10), justify="center", compound="top", bd=0)
        image.place(relx=.5, rely=.5, anchor="center", relwidth=1, relheight=1)
        card._body = body
        body.bind("<Configure>", self._schedule_preview_resize)
        return card, image

    def _update_endpoint_label(self):
        target = "主机参考服务（流程验证）" if self.allow_host_reference else "开发板"
        binding = ""
        if self.local_address:
            binding = f"  ·  本机 {self.local_address}"
        if self.interface_index:
            binding += f" / 网卡 {self.interface_index}"
        self.endpoint_text.set(f"{target} {self.host}:{self.port}{binding}  ·  模型 {self.model_hash[:12]}…")

    def _client(self, timeout: float):
        return BoardClient(self.host, self.port, model_sha256=self.model_hash, class_names=self.names,
                           allow_host_reference=self.allow_host_reference, timeout=timeout,
                           local_address=self.local_address, interface_index=self.interface_index)

    def _set_status(self, message: str, kind: str = "error"):
        color, icon = {
            "error": (COLORS["danger"], "✕"),
            "success": (COLORS["success"], "✓"),
            "info": (COLORS["accent"], "ⓘ"),
            "warning": (COLORS["warning"], "!"),
        }[kind]
        self.status_text.set(message)
        self.banner_strip.configure(bg=color)
        self.status_icon.configure(fg=color, text=icon)
        self.status_label.configure(fg=COLORS["error_text"] if kind == "error" else COLORS["banner_text"])
        self._refresh_indicators()

    def choose_images(self):
        if self.busy: return
        paths = filedialog.askopenfilenames(title="选择待检测图片", filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp"), ("所有文件", "*.*")])
        if paths: self._import_paths(paths)

    def choose_folder(self):
        if self.busy: return
        folder = filedialog.askdirectory(title="选择图片文件夹")
        if not folder: return
        base = Path(folder)
        try:
            paths = sorted((base.rglob("*") if self.include_subfolders.get() else base.iterdir()), key=lambda p: str(p).casefold())
            self._import_paths(p for p in paths if p.is_file())
        except OSError as exc:
            self._set_status(f"无法读取文件夹：{exc}", "error")

    def _import_paths(self, paths):
        added, duplicates, invalid = 0, 0, []
        first = None
        for raw in paths:
            path = Path(raw).resolve()
            if path.suffix.lower() not in IMAGE_TYPES: continue
            key = str(path)
            if key in self.records:
                duplicates += 1
                continue
            try:
                # Decode once for validation, retain only a small thumbnail until selected.
                source = load_bgr(path)
                thumb = Image.fromarray(cv2.cvtColor(source, cv2.COLOR_BGR2RGB))
                thumb.thumbnail((44, 44), Image.Resampling.LANCZOS)
                self.thumbnail_photos[key] = ImageTk.PhotoImage(thumb)
            except Exception as exc:
                invalid.append(f"{path.name}: {exc}")
                continue
            self.image_paths.append(path)
            self.records[key] = {"path":path,"status":"待检测","source":None,"annotated":None,"results":None,"task":UNIFIED_TASK,"elapsed":None,"error":None}
            if first is None: first=path
            added += 1
        if added and not self.busy:
            self.run_state = "idle"
        self._refresh_queue()
        if first: self._focus_queue_path(first)
        note=f"已添加 {added} 张，跳过重复 {duplicates} 张，损坏图片 {len(invalid)} 张。"
        self._set_status(note, "info" if not invalid else "error")
        if invalid:
            self._set_status(f"已添加 {added} 张；以下图片无法读取：" + "；".join(invalid[:3]), "error")

    def _refresh_queue(self):
        selected = set(self.queue_list.selection())
        children=self.queue_list.get_children()
        if children: self.queue_list.delete(*children)
        if self.image_paths:
            self.queue_empty_label.place_forget()
        else:
            self.queue_empty_label.place(relx=0.5, rely=0.45, anchor="center")
        done = 0
        for path in self.image_paths:
            key=str(path.resolve()); record=self.records[key]
            status="待检测" if self._needs_detection(record) else record["status"]
            done += status == "已完成"
            shown = {"正在检测": "检测中", "检测失败": "失败"}.get(status, status)
            elapsed = record.get("elapsed")
            timing = f"{elapsed * 1000:.0f} ms" if status == "已完成" and isinstance(elapsed, (int, float)) else ""
            self.queue_list.insert("", "end", iid=key, text=f"  {path.name}",
                                   image=self.thumbnail_photos.get(key, ""),
                                   values=(f"{self._status_icon(status)} {shown}", timing), tags=(status,))
        selected=[k for k in selected if self.queue_list.exists(k)]
        if selected: self.queue_list.selection_set(selected)
        self.count_text.set(f"{done}/{len(self.image_paths)} 已完成" if self.image_paths else "0 张")
        self.detect_button.configure(state="normal" if self._pending_count() and not self.busy and not self.probing else "disabled")
        self.clear_button.configure(state="normal" if self.image_paths and not self.busy else "disabled")
        self.remove_button.configure(state="normal" if self.queue_list.selection() and not self.busy else "disabled")
        self.save_button.configure(state="normal" if self._has_results() and not self.busy else "disabled")
        self.folder_button.configure(state="disabled" if self.busy else "normal")

    @staticmethod
    def _status_icon(status: str) -> str:
        return {"待检测": "○", "正在检测": "◐", "已完成": "✓", "检测失败": "✕", "已取消": "–"}.get(status, "○")

    def _pending_count(self):
        return sum(1 for record in self.records.values() if self._needs_detection(record))

    @staticmethod
    def _needs_detection(record: dict):
        return record.get("status") in ("待检测", "检测失败", "已取消") or (
            record.get("status") == "已完成" and record.get("task") != UNIFIED_TASK)

    def _has_results(self):
        return any(record["results"] is not None for record in self.records.values())

    def _on_queue_select(self, _event=None):
        selected=self.queue_list.selection()
        if selected and selected[0] in self.records:
            self._select_path(self.records[selected[0]]["path"])
        self.remove_button.configure(state="normal" if selected and not self.busy else "disabled")

    def _focus_queue_path(self, path):
        key=str(path.resolve())
        if self.queue_list.exists(key):
            self.queue_list.selection_set(key)
            self.queue_list.see(key)
        self._select_path(path)

    @staticmethod
    def _task_label(task):
        return {UNIFIED_TASK: "全部9类光电缺陷", "pin": "光电"}.get(task, "尚无结果")

    def _select_path(self, path: Path):
        self.active_path = path
        record = self.records[str(path.resolve())]
        if record.get("results") is not None and record.get("task") != UNIFIED_TASK:
            task_note = f"上次结果：{self._task_label(record.get('task'))}；待PIN 9类复测"
        else:
            task_note = self._task_label(record.get("task") or UNIFIED_TASK)
        no_defects = record.get("status") == "已完成" and record.get("results") == [] and not record.get("error")
        outcome = "未检测到明显缺陷" if no_defects else record["status"]
        self.result_summary.set(f"检测详情  ·  {path.name}  ·  {task_note}  ·  {outcome}")
        self.detail_file.set(f"{path.name}  ·  {outcome}")
        results = record.get("results")
        self.detail_count_chip.value.configure(
            text=str(len(results)) if results is not None else "—",
            fg=(COLORS["danger"] if results else COLORS["success"]) if results is not None else COLORS["navy"])
        elapsed = record.get("elapsed")
        self.detail_time_chip.value.configure(
            text=f"{elapsed * 1000:.1f} ms" if isinstance(elapsed, (int, float)) and results is not None else "—")
        self._render_previews()
        self._show_table(results or [])
        if no_defects:
            self.table.insert("", "end", text="", values=("未检测到明显缺陷", "", ""), tags=("note",))
        if record.get("error"):
            self.table.insert("", "end", text="", values=("检测失败", "", record["error"]), tags=("error",))
            self._set_status(f"{path.name}：{record['error']}", "error")

    def _reset_details(self):
        self.detail_file.set("未选择图片")
        self.detail_count_chip.value.configure(text="—", fg=COLORS["navy"])
        self.detail_time_chip.value.configure(text="—")

    def _render_previews(self):
        if not self.active_path:
            self.source_meta.set("")
            self.result_meta.set("")
            self._show_empty_preview(self.source_image, "source", "请选择图片")
            self._show_empty_preview(self.result_image, "result", "检测结果将在此显示")
            return
        key=str(self.active_path.resolve()); record=self.records.get(key)
        if not record: return
        try:
            if self.preview_path != key or self.preview_source is None:
                self.preview_source=load_bgr(self.active_path)
                self.preview_path=key
            height, width = self.preview_source.shape[:2]
            self.source_meta.set(f"{width} × {height}")
            self._show_image_widget(self.source_image,self.preview_source,"source")
            self._show_image_widget(self.result_image,record.get("annotated"),"result")
            status, results = record.get("status"), record.get("results")
            if status == "已完成" and results == [] and not record.get("error"):
                meta, color = "未检出缺陷", COLORS["success"]
            elif status == "已完成" and results:
                meta, color = f"检出 {len(results)} 处缺陷", COLORS["danger"]
            elif status == "正在检测":
                meta, color = "开发板推理中…", COLORS["accent"]
            elif status == "检测失败":
                meta, color = "检测失败", COLORS["danger"]
            else:
                meta, color = "", COLORS["muted"]
            self.result_meta.set(meta)
            self.result_meta_label.configure(fg=color)
            if record.get("annotated") is None:
                text = {"正在检测": "开发板推理中…", "检测失败": "检测失败，详见下方详情"}.get(status, "待检测")
                self.result_image.configure(text=text)
        except Exception as exc:
            self._set_status(f"图片无法预览：{exc}","error")

    def _show_image_widget(self, widget, bgr, key):
        if bgr is None:
            placeholder = "请选择图片" if key == "source" else "检测结果将在此显示"
            self.photos[key] = None
            self._show_empty_preview(widget, key, placeholder)
            return
        available_w = max(60, widget.winfo_width() - self._px(12))
        available_h = max(60, widget.winfo_height() - self._px(12))
        height, width = bgr.shape[:2]
        scale = min(available_w / width, available_h / height)
        resized = cv2.resize(bgr, (max(1, round(width * scale)), max(1, round(height * scale))),
                             interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)))
        self.photos[key] = photo
        widget.configure(image=photo, text="", compound=tk.CENTER)

    def _show_empty_preview(self, widget, key, placeholder):
        photo = self.empty_preview_photos.get("icon")
        if photo is None:
            size = self._px(56)
            factor = 3
            ink = _hex_rgb(COLORS["faint"])
            image = Image.new("RGB", (size * factor, size * factor), _hex_rgb(COLORS["preview"]))
            draw = ImageDraw.Draw(image)
            s = size * factor
            stroke = 2 * factor
            draw.rounded_rectangle((s * .1, s * .2, s * .9, s * .8), radius=s * .08, outline=ink, width=stroke)
            draw.ellipse((s * .64, s * .3, s * .76, s * .42), outline=ink, width=stroke)
            draw.line((s * .16, s * .72, s * .38, s * .48, s * .54, s * .64, s * .64, s * .56, s * .84, s * .72),
                      fill=ink, width=stroke, joint="curve")
            photo = ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=self.root)
            self.empty_preview_photos["icon"] = photo
        widget.configure(image=photo, text=placeholder, compound="top")

    def _schedule_preview_resize(self, _event=None):
        if self._closed:
            return
        if not self._preview_resize_pending:
            self._preview_resize_pending = True
            self.root.after_idle(self._resize_previews)

    def _resize_previews(self):
        self._preview_resize_pending=False
        if self._closed:
            return
        self.root.update_idletasks()
        self._render_previews()

    def _swatch(self, color):
        photo = self._swatches.get(color)
        if photo is None:
            size, factor = self._px(10), 3
            image = Image.new("RGB", (size * factor, size * factor), _hex_rgb(COLORS["white"]))
            ImageDraw.Draw(image).rounded_rectangle((0, 0, size * factor - 1, size * factor - 1),
                                                    radius=factor * 2, fill=_hex_rgb(color))
            photo = ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=self.root)
            self._swatches[color] = photo
        return photo

    def _show_table(self, rows):
        for iid in self.table.get_children():
            self.table.delete(iid)
        for index, hit in enumerate(rows, start=1):
            x1, y1, x2, y2 = hit["xyxy"]
            self.table.insert("", "end", text=f"  {index}", image=self._swatch(_class_color(hit)),
                              values=(display_class_name(hit["class_name"]), f"{hit['score'] * 100:.1f}%",
                                      f"{x1:.0f},  {y1:.0f},  {x2:.0f},  {y2:.0f}"),
                              tags=("odd" if index % 2 else "even",))

    def _on_table_yview(self, *args):
        self.table_scroll.set(*args)

    def _schedule_table_overlay(self, _event=None):
        """Kept for compatibility; the table no longer needs a font overlay."""
        return

    def start_batch(self):
        if self._closed or self.busy:
            return
        if self.probing:
            self._set_status("连接检查正在进行，请完成后再开始检测。", "info")
            return
        pending = [path for path in self.image_paths
                   if self._needs_detection(self.records[str(path.resolve())])]
        if not pending:
            self._set_status("队列中没有待检测图片。", "info")
            return
        if not self._probe_timeout_valid():
            return
        try:
            delay = float(self.playback_delay.get())
            if not math.isfinite(delay) or not 0 <= delay <= 30:
                raise ValueError()
        except (ValueError, TypeError, tk.TclError):
            self._show_message("播放间隔无效", "结果停留时间须为 0 至 30 秒；0 秒表示连续检测。", kind="error")
            return
        timeout = self.timeout
        try:
            client = self._client(timeout)
        except Exception as exc:
            self._show_message("连接设置无效", str(exc), kind="error")
            return
        self.busy = True
        self.history_errors = 0
        self.cancel_pending.clear()
        self._cancel_playback_timer()
        self._playback_generation += 1
        self._playback_paths = pending
        self._playback_index = 0
        self._playback_complete = 0
        self._playback_failures = 0
        self._playback_finishing = False
        self._playback_client = client
        self._playback_delay_seconds = delay
        self._image_inflight = False
        self.playback_paused = False
        self.pause_button.configure(state="normal", text="暂停")
        self.playback_delay_input.configure(state="disabled")
        self._refresh_queue()
        self.detect_button.configure(state="disabled")
        self.connect_button.configure(state="disabled")
        self.choose_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.settings_button.configure(state="disabled")
        self._set_status(f"正在检测 {len(pending)} 张图片；按队列顺序提交到开发板…", "info")
        self._dispatch_next_image()

    def _probe_timeout_valid(self):
        if not isinstance(self.timeout, (int, float)) or not 0 < self.timeout <= 86400:
            self._show_message("等待时间无效", "等待上限必须在 1 至 86400 秒之间。", kind="error")
            return False
        return True

    def _cancel_playback_timer(self):
        if self._playback_timer is not None:
            self.root.after_cancel(self._playback_timer)
            self._playback_timer = None

    def _dispatch_next_image(self):
        if self._closed or not self.busy or self._image_inflight or self.playback_paused:
            return
        if self.cancel_pending.is_set() or self._playback_index >= len(self._playback_paths):
            self._finish_playback()
            return
        path = self._playback_paths[self._playback_index]
        self._playback_index += 1
        self._image_inflight = True
        self.records[str(path.resolve())]["status"] = "正在检测"
        self._refresh_queue()
        self._focus_queue_path(path)
        self._active_started_at = time.monotonic()
        self._set_status(f"正在检测第 {self._playback_index}/{len(self._playback_paths)} 张：{path.name}，请等待板端返回…", "info")
        threading.Thread(target=self._image_worker,
                         args=(path, self._playback_client, self._playback_generation), daemon=True).start()

    def _image_worker(self, path: Path, client: BoardClient, generation: int):
        started = time.perf_counter()
        try:
            source, tensor, mapping = prepare_image(path)
            rows = client.infer(tensor, mapping, UNIFIED_TASK)
            result = ("success", path, UNIFIED_TASK, source, rows, time.perf_counter() - started)
        except Exception as exc:
            result = ("error", path, UNIFIED_TASK, str(exc))
        # Worker threads only send data. Tk owns rendering and the dwell timer.
        self.events.put(("image_result", generation, result))

    def _after_image_result(self, success: bool):
        self._image_inflight = False
        self._active_started_at = None
        if success:
            self._playback_complete += 1
        else:
            self._playback_failures += 1
        if self.cancel_pending.is_set() or self._playback_index >= len(self._playback_paths):
            self._finish_playback()
        elif self.playback_paused:
            self._set_status("当前图片已处理，播放已暂停；点击“继续”恢复检测。", "info")
            self.live_text.set("播放已暂停 · 当前结果已保留")
        else:
            if success:
                self._set_status(f"第 {self._playback_index}/{len(self._playback_paths)} 张检测完成，正在展示结果。", "success")
            self._schedule_playback_advance()

    def _schedule_playback_advance(self):
        self._cancel_playback_timer()
        generation = self._playback_generation
        self.live_text.set("连续检测 · 正在准备下一张" if self._playback_delay_seconds == 0 else
                           f"结果展示中 · {self._playback_delay_seconds:g} 秒后检测下一张")
        def advance():
            if self._closed or generation != self._playback_generation:
                return
            self._playback_timer = None
            self._dispatch_next_image()
        self._playback_timer = self.root.after(round(self._playback_delay_seconds * 1000), advance)

    def toggle_playback(self):
        if not self.busy or self.cancel_pending.is_set():
            return
        self.playback_paused = not self.playback_paused
        self.pause_button.configure(text="继续" if self.playback_paused else "暂停")
        if self.playback_paused:
            self._cancel_playback_timer()
            message = "已暂停后续播放；当前检测完成后保留结果。" if self._image_inflight else "播放已暂停；点击“继续”恢复检测。"
            self._set_status(message, "info")
            if not self._image_inflight:
                self.live_text.set("播放已暂停 · 当前结果已保留")
        elif not self._image_inflight:
            self._set_status("已继续播放，展示当前结果后自动检测下一张。", "info")
            self._schedule_playback_advance()
        else:
            self._set_status("已继续播放，正在等待当前图片的板端检测结果。", "info")

    def _finish_playback(self):
        if self._playback_finishing:
            return
        self._playback_finishing = True
        self._cancel_playback_timer()
        self.events.put(("done", self._playback_complete, self._playback_failures,
                         self.cancel_pending.is_set(), len(self._playback_paths)))

    def _on_playback_destroy(self, event):
        if event.widget is self.root and not self._closed:
            self._closed = True
            self._playback_generation += 1
            self.cancel_pending.set()
            self._cancel_playback_timer()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._playback_generation += 1
        self.cancel_pending.set()
        self._cancel_playback_timer()
        # Cancel scheduled callbacks before destroying their widgets. Tcl
        # commands remain owned by the widgets and are cleaned up by destroy.
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()

    def stop_pending(self):
        if not self.busy:
            return
        self.cancel_pending.set()
        self._cancel_playback_timer()
        self.stop_button.configure(state="disabled")
        self.pause_button.configure(state="disabled")
        self._refresh_indicators()
        if not self._image_inflight:
            self._finish_playback()
            return
        self._set_status("已标记停止后续任务；当前图片的板端请求无法中断，会在返回后停止。", "info")

    def check_connection(self):
        if self.busy or self.probing:
            return
        try:
            timeout = self.timeout
            if not 0 < timeout <= 86400:
                raise ValueError()
        except (TypeError, ValueError):
            self._show_message("等待时间无效", "等待上限必须在 1 至 86400 秒之间。", kind="error")
            return
        self.probing = True
        self.connect_button.configure(state="disabled")
        self.detect_button.configure(state="disabled")
        self.settings_button.configure(state="disabled")
        self.conn_state = "checking"
        self._set_status("正在检查连接并核对协议、模型和类别身份…", "info")
        try:
            client = self._client(timeout)
        except Exception as exc:
            self.probing = False
            self.conn_state = "unknown"
            self.connect_button.configure(state="normal")
            self.settings_button.configure(state="normal")
            self._refresh_queue()
            self._set_status(f"连接设置无效：{exc}", "error")
            return
        expected_runtime = "host_reference" if self.allow_host_reference else "board"
        expected = {
            "type": "HELLO_OK", "protocol": PROTOCOL, "runtime": expected_runtime,
            "model_sha256": self.model_hash, "classes_sha256": canonical_sha256(self.names),
            "input": "rgb-u8-640-letterbox114", "box_space": "normalized-model-xyxy",
        }
        threading.Thread(target=self._connection_worker, args=(client, expected), daemon=True).start()

    def _connection_worker(self, client, expected=None):
        self.events.put(("diagnostics",diagnose_connection(client)))

    def _show_message(self, title, message, kind="info", parent=None):
        parent = parent or self.root
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=COLORS["page"])
        dialog.resizable(False, False)
        dialog.transient(parent)
        panel = self._card(dialog)
        panel.pack(fill="both", expand=True, padx=12, pady=12)
        color = COLORS["error_text"] if kind == "error" else COLORS["green_text"] if kind == "success" else COLORS["accent"]
        tk.Label(panel, text=title, bg=COLORS["white"], fg=color,
                 font=(UI_FONT, 12, "bold"), anchor="w").pack(
                     fill="x", padx=16, pady=(14, 7))
        MixedLabel(panel, text=message, bg=COLORS["white"], fg=COLORS["navy"],
                   font=(UI_FONT, 10), anchor="w", justify="left",
                   wraplength=500).pack(fill="x", padx=16, pady=(0, 14))
        close = self._toolbar_button(panel, "知道了", dialog.destroy)
        close.pack(anchor="e", padx=16, pady=(0, 14))
        dialog.bind("<Return>", lambda _event: dialog.destroy())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        width = min(560, max(380, dialog.winfo_reqwidth()))
        height = dialog.winfo_reqheight()
        dialog.geometry(f"{width}x{height}")
        self._center_dialog(dialog)
        dialog.grab_set()
        dialog.wait_window()

    def show_diagnostics(self):
        if not self.last_diagnostics:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("连接诊断详情")
        dialog.configure(bg=COLORS["page"])
        dialog.geometry("800x480")
        box = tk.Text(dialog, wrap="word", font=(UI_FONT, 10), padx=16, pady=12,
                      bg=COLORS["white"], fg=COLORS["navy"], insertbackground=COLORS["accent"],
                      selectbackground="#245477", relief="flat", borderwidth=0)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.tag_configure("numeric", font=(NUMBER_FONT, 10))
        box.tag_configure("latin", font=(LETTER_FONT, 10))
        labels={"pass":"通过","fail":"失败","warn":"提示","skipped":"未检查"}
        for stage in self.last_diagnostics["stages"]:
            _insert_mixed_text(box, f"【{labels.get(stage['status'],stage['status'])}】{stage['name']}\n{stage['detail']}\n")
            if stage.get("action"):
                _insert_mixed_text(box, f"处理建议：{stage['action']}\n")
            box.insert("end","\n")
        box.configure(state="disabled")

    def open_settings(self):
        if self.busy or self.probing:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("高级设置")
        dialog.configure(bg=COLORS["page"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        panel = tk.Frame(dialog, bg=COLORS["white"], highlightthickness=1,
                         highlightbackground=COLORS["border"], padx=18, pady=16)
        panel.pack(fill="both", expand=True, padx=16, pady=16)
        host_var, port_var, timeout_var = tk.StringVar(value=self.host), tk.StringVar(value=str(self.port)), tk.StringVar(value=str(self.timeout))
        local_var = tk.StringVar(value=self.local_address or "")
        index_var = tk.StringVar(value=str(self.interface_index or ""))
        fields = (("开发板地址", host_var), ("端口", port_var), ("单张等待上限（秒）", timeout_var),
                  ("本机 IPv4（留空自动选择）", local_var), ("网卡编号（留空自动选择）", index_var))
        for row, (label, variable) in enumerate(fields):
            MixedLabel(panel, text=label, bg=COLORS["white"], fg=COLORS["navy"], anchor="w").grid(
                row=row, column=0, sticky="w", pady=7, padx=(0, 20))
            MixedEntry(panel, textvariable=variable, width=28, relief="flat", bd=0,
                     bg=COLORS["surface_alt"], fg=COLORS["navy"], insertbackground=COLORS["accent"],
                     font=(NUMBER_FONT, 10),
                     selectbackground="#245477", highlightthickness=1,
                     highlightbackground=COLORS["border"], highlightcolor=COLORS["accent"]).grid(
                row=row, column=1, sticky="ew", pady=7, ipady=5)
        MixedLabel(panel, text="工作台会核对板端 V8 协议及当前模型身份。",
                 bg=COLORS["white"], fg=COLORS["muted"], anchor="w").grid(
                     row=5, column=0, columnspan=2, sticky="ew", pady=(7, 12))
        buttons = tk.Frame(panel, bg=COLORS["white"])
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        tk.Button(buttons, text="取消", command=dialog.destroy, padx=16, pady=7,
                  bg=COLORS["surface_alt"], fg=COLORS["navy"], activebackground="#203b53",
                  activeforeground=COLORS["navy"], relief="flat", bd=0, cursor="hand2").pack(
                      side="right", padx=(8, 0))

        def save():
            host = host_var.get().strip()
            try:
                port = int(port_var.get())
                timeout = float(timeout_var.get())
                local = str(ipaddress.IPv4Address(local_var.get().strip())) if local_var.get().strip() else None
                index = int(index_var.get()) if index_var.get().strip() else None
                if index is not None and not 1 <= index <= 0xffffffff:
                    raise ValueError()
                if not host or not 1 <= port <= 65535 or not 1 <= timeout <= 86400:
                    raise ValueError()
            except ValueError:
                self._show_message("设置无效", "请检查板端地址、端口、等待上限、本机 IPv4 和正整数网卡编号。",
                                   kind="error", parent=dialog)
                return
            self.host, self.port, self.timeout = host, port, timeout
            self.local_address, self.interface_index = local, index
            self._update_endpoint_label()
            self.conn_state = "unknown"
            self._set_status("连接设置已更新。请检查连接后再开始检测。", "info")
            dialog.destroy()

        tk.Button(buttons, text="保存设置", command=save, bg=COLORS["blue"], fg=COLORS["navy"],
                  activebackground=COLORS["blue_hover"], activeforeground=COLORS["navy"],
                  relief="flat", bd=0, cursor="hand2", padx=16, pady=7).pack(side="right")
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        dialog.update_idletasks()
        self._center_dialog(dialog)

    def _center_dialog(self, dialog):
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

    def show_help(self):
        self._show_message(
            "使用帮助",
            "1. 点击“检查连接”，确认开发板、V8 协议和模型身份匹配。\n"
            "2. 点击“导入图片”或“导入文件夹”添加图片。\n"
            "3. 点击“开始检测”，每张图片都会检查 PIN 9 类光电缺陷，按队列顺序逐张提交到开发板。\n"
            "“结果停留”为每张结果的展示时间，0 秒表示连续检测；停留时间不计入单张耗时。\n"
            "点击“暂停”保留当前结果，“继续”会重新计时后检测下一张。\n"
            "4. 点击图片队列查看原图、检测图和类别详情。\n"
            "5. 点击“保存结果”导出检测图和 JSON 报告。\n\n"
            "停止后续只会取消尚未开始的图片；当前板端请求会继续等待结果。",
        )

    def show_history(self):
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        dialog = tk.Toplevel(self.root)
        dialog.title("检测历史")
        dialog.configure(bg=COLORS["page"])
        dialog.geometry("760x470")
        dialog.minsize(600, 360)
        panel = self._card(dialog)
        panel.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(panel, text="检测历史", bg=COLORS["white"], fg=COLORS["navy"],
                 font=(UI_FONT, 14, "bold"), anchor="w").pack(fill="x", padx=14, pady=(12, 8))
        tree = ttk.Treeview(panel, style="Workbench.Treeview", columns=("time", "task", "source", "count"),
                            show="headings", height=12)
        for key, title, width in (("time", "时间", 165), ("task", "任务", 90), ("source", "图片", 340), ("count", "目标数", 90)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for report_path in sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:500]:
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                stamp = datetime.fromtimestamp(report_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                source = Path(report.get("source", "")).name
                tree.insert("", "end", iid=str(report_path), values=(stamp, self._task_label(report.get("task")),
                              source, len(report.get("detections", []))))
            except (OSError, ValueError, TypeError):
                continue

        def open_record(_event=None):
            selection = tree.selection()
            if selection:
                path = Path(selection[0])
                if os.name == "nt":
                    os.startfile(path)
                else:
                    self._show_message("历史报告", str(path), parent=dialog)

        tree.bind("<Double-Button-1>", open_record)
        MixedLabel(panel, text=f"双击记录打开 JSON · {HISTORY_DIR}", bg=COLORS["white"],
                   fg=COLORS["muted"], anchor="w").pack(fill="x", padx=14, pady=(0, 10))

    def remove_selected(self):
        if self.busy: return
        keys=list(self.queue_list.selection())
        for key in keys:
            self.records.pop(key,None); self.thumbnail_photos.pop(key,None)
        self.image_paths=[p for p in self.image_paths if str(p.resolve()) not in keys]
        self.active_path=None; self.preview_path=None
        self._refresh_queue()
        if self.image_paths: self._focus_queue_path(self.image_paths[0])
        else: self._show_table([]); self._render_previews(); self._reset_details()
        self._set_status(f"已移除 {len(keys)} 张图片。","info")

    def clear_images(self):
        if self.busy:
            return
        self.image_paths.clear()
        self.records.clear()
        self.thumbnail_photos.clear()
        self.preview_path=None
        self.active_path = None
        self._refresh_queue()
        self._show_table([])
        self._render_previews()
        self.result_summary.set("检测详情")
        self._reset_details()
        self.run_state = "idle"
        self._set_status("图片队列已清空。", "info")

    def save_batch(self):
        completed = [(path, self.records[str(path.resolve())]) for path in self.image_paths
                     if self.records[str(path.resolve())]["results"] is not None]
        if not completed:
            self._show_message("暂无结果", "完成至少一张图片的检测后即可保存。")
            return
        target = filedialog.askdirectory(title="选择本批结果保存位置")
        if not target:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = Path(target) / f"v8_检测结果_{stamp}"
        suffix = 1
        while folder.exists():
            suffix += 1
            folder = Path(target) / f"v8_检测结果_{stamp}_{suffix}"
        try:
            folder.mkdir(parents=True)
            exported = []
            for index, (path, record) in enumerate(completed, start=1):
                stem = f"{index:03d}_{self._safe_stem(path.stem)}"
                report = self._report(path, record)
                json_path = folder / f"{stem}.json"
                image_path = folder / f"{stem}_检测图.png"
                json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                ok, encoded = cv2.imencode(".png", record["annotated"])
                if not ok:
                    raise OSError(f"无法编码检测结果图片：{path.name}")
                encoded.tofile(str(image_path))
                exported.append((json_path, image_path))
        except (OSError, cv2.error, TypeError, ValueError) as exc:
            self._set_status(f"保存本批结果失败：{exc}", "error")
            self._show_message("保存失败", f"结果未能完整保存。\n\n{exc}", kind="error")
            return
        self._set_status(f"已保存 {len(exported)} 张图片的结果：{folder}", "success")
        self._show_message("保存完成", f"已保存 {len(exported)} 份检测报告及检测图。\n\n{folder}",
                           kind="success")

    @staticmethod
    def _safe_stem(stem: str):
        clean = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem).strip("._")
        return clean[:80] or "image"

    def _report(self, path: Path, record: dict):
        return {
            "stage": "host_reference" if self.allow_host_reference else "board_response_unverified",

            "source": str(path),
            "task": record["task"],
            "task_label": self._task_label(record.get("task")),
            "elapsed_seconds": record["elapsed"],
            "timing_scope": "image read, RGB640 preprocessing, connect/HELLO, board inference and response validation; excludes result display dwell and rendering",
            "protocol": PROTOCOL,
            "classes_sha256": canonical_sha256(self.names),
            "result_message": ("未检测到明显缺陷" if record.get("status") == "已完成"
                               and record.get("results") == [] and not record.get("error")
                               else f"检测到 {len(record.get('results') or [])} 个缺陷"
                               if record.get("results") else record.get("status", "尚无结果")),
            "model_sha256": self.model_hash,
            "classes": self.names,
            "display_classes": [display_class_name(name) for name in self.names],
            "detections": [dict(hit, display_name=display_class_name(hit["class_name"]))
                           for hit in (record["results"] or [])],
        }

    def _save_history(self, path: Path, record: dict):
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        report_path = HISTORY_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
        report_path.write_text(json.dumps(self._report(path, record), ensure_ascii=False, indent=2), encoding="utf-8")

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "image_result":
                    _, generation, event = event
                    if generation != self._playback_generation or not self.busy or not self._image_inflight:
                        continue
                    kind = event[0]
                if kind == "started":
                    _, path, index, total = event
                    record = self.records.get(str(path.resolve()))
                    if record:
                        record["status"] = "正在检测"
                    self._refresh_queue()
                    self._select_path(path)
                    self._active_started_at=time.monotonic()
                    self._set_status(f"正在检测第 {index}/{total} 张：{path.name}，请等待板端返回…", "info")
                elif kind == "success":
                    _, path, task, source, rows, elapsed = event
                    self.conn_state = "ok"
                    record = self.records.get(str(path.resolve()))
                    if record:
                        record.update(status="已完成", source=None, results=rows,
                                       annotated=draw_detections(source, rows), task=task,
                                       elapsed=elapsed, error=None)
                        history_error = None
                        try:
                            self._save_history(path, record)
                        except OSError as exc:
                            self.history_errors += 1
                            history_error = str(exc)
                        self._focus_queue_path(path)
                        if history_error:
                            self._set_status(f"检测已完成，但自动写入历史失败：{history_error}", "error")
                        self._refresh_queue()
                    self._after_image_result(True)
                elif kind == "error":
                    _, path, task, error = event
                    record = self.records.get(str(path.resolve()))
                    if record:
                        record.update(status="检测失败", task=task, results=None, error=error)
                        self._focus_queue_path(path)
                        self._refresh_queue()
                    self._set_status(f"{path.name} 检测失败：{error}", "error")
                    self._after_image_result(False)
                elif kind == "done":
                    _, complete, failures, cancelled, total = event
                    self.busy = False
                    self.playback_paused = False
                    self.pause_button.configure(state="disabled", text="暂停")
                    self.playback_delay_input.configure(state="normal")
                    self._active_started_at=None
                    self.stop_button.configure(state="disabled")
                    self.connect_button.configure(state="normal")
                    self.choose_button.configure(state="normal")
                    self.settings_button.configure(state="normal")
                    self.run_state = "stopped" if cancelled else "partial" if failures else "done"
                    self._refresh_queue()
                    if cancelled:
                        self._set_status(f"已完成 {complete} 张，失败 {failures} 张；队列剩余任务已停止。", "info")
                    elif failures:
                        self._set_status(f"本批 {complete + failures}/{total} 张已处理，其中 {failures} 张失败；可查看失败详情后重试。", "error")
                    elif self.history_errors:
                        self._set_status(f"检测已完成，但有 {self.history_errors} 条历史记录未能自动写入；可用“保存本批结果”另存。", "error")
                    else:
                        self._set_status(f"本批 {complete}/{total} 张检测完成。", "success")
                elif kind == "diagnostics":
                    self.last_diagnostics=event[1]
                    self.probing=False
                    self.conn_state = "ok" if self.last_diagnostics["ok"] else "fail"
                    self.connect_button.configure(state="normal")
                    self.settings_button.configure(state="normal")
                    self.diagnostics_button.configure(state="normal")
                    self._refresh_queue()
                    self._set_status(self.last_diagnostics["message"].split("详情：")[0]+(" 点击“诊断详情”查看处理建议。" if not self.last_diagnostics["ok"] else ""), "success" if self.last_diagnostics["ok"] else "error")
                elif kind == "probe_success":
                    _, peer, local, runtime = event
                    self.probing = False
                    self.conn_state = "ok"
                    self.connect_button.configure(state="normal")
                    self.settings_button.configure(state="normal")
                    self._refresh_queue()
                    label = "主机参考服务" if runtime == "host_reference" else "开发板"
                    self._set_status(f"{label}连接成功，协议和模型身份匹配；本机 {local[0]}，对端 {peer[0]}:{peer[1]}。", "success")
                elif kind == "probe_error":
                    _, error = event
                    self.probing = False
                    self.conn_state = "fail"
                    self.connect_button.configure(state="normal")
                    self.settings_button.configure(state="normal")
                    self._refresh_queue()
                    self._set_status(f"连接检查失败：{error}", "error")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


def main():
    parser = argparse.ArgumentParser(description="PIN 9-class, 640x640 V8 board inspection desktop workbench")
    parser.add_argument("--host", required=True, help="V8 board IP or hostname")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--timeout", type=float, default=60.0, help="maximum seconds for one board inference")
    parser.add_argument("--local-address", help="optional local IPv4 address to bind for the board connection")
    parser.add_argument("--interface-index", type=int,
                        help="optional Windows IPv4 interface index for the board connection")
    parser.add_argument("--model", type=Path, required=True,
                        help="exact deployed PIN9 640 model package for identity SHA256")
    parser.add_argument("--classes", type=Path, required=True,
                        help="matching ordered nine-class PIN names config")
    parser.add_argument("--allow-host-reference", action="store_true", help="explicitly allow non-board reference server")
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error("--model must point to the exact deployed PIN9 640 model package")
    if not args.classes.is_file():
        parser.error("--classes must point to the matching nine-class PIN data configuration")
    if not 0 < args.timeout <= 86400:
        parser.error("--timeout must be between 1 and 86400 seconds")
    try:
        names = load_class_names(args.classes)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(f"invalid --classes configuration: {exc}")
    root = tk.Tk()
    App(root, host=args.host, port=args.port, model=args.model, names=names,
        allow_host_reference=args.allow_host_reference, timeout=args.timeout,
        local_address=args.local_address, interface_index=args.interface_index)
    root.mainloop()


if __name__ == "__main__":
    main()
