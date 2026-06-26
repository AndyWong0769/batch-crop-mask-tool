#!/usr/bin/env python3
"""
Batch Image Crop & Mask Tool
Dependencies: pip install Pillow windnd

A professional tool for batch-processing images — apply color blocks, blur regions,
mosaic effects, or crop areas across hundreds of photos in one go.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk, ImageDraw, ImageFilter
import json
import os
import threading
import queue

try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False
    import sys
    import os
    if hasattr(sys, '_MEIPASS'):
        windnd_path = os.path.join(sys._MEIPASS, 'windnd')
        if os.path.exists(windnd_path):
            sys.path.append(sys._MEIPASS)
            try:
                import windnd
                HAS_WINDND = True
            except:
                pass

# ═══════════════════════════════════════════════════════════════
#  Neo-Kinpaku Color Theme
#  Dark lacquer surfaces with kinpaku gold accents.
#  Inspired by the Impeccable design system.
# ═══════════════════════════════════════════════════════════════

THEME = {
    "lacquer":       "#1E1E1E",  # page ground, canvas bg
    "lacquer_deep":  "#171717",  # deepest insets
    "raised":        "#2A2A2A",  # panels, cards
    "graphite":      "#363636",  # inputs, inactive surfaces
    "graphite_2":    "#424242",  # one step above graphite
    "gold":          "#D4A83A",  # kinpaku gold — primary accent
    "gold_pale":     "#E0C868",  # hover lift
    "gold_rich":     "#C4962E",  # active CTA
    "gold_deep":     "#A07818",  # borders against brand
    "champagne":     "#EAEAEA",  # headlines, strong labels
    "text":          "#D4D4D4",  # body text
    "text_muted":    "#A0A0A0",  # captions, secondary
    "text_faint":    "#808080",  # subdued
    "text_disabled": "#606060",  # disabled
    "patina":        "#5A9E8F",  # verdigris — success, crop outlines
    "patina_pale":   "#8BC4B7",  # hover lift on patina
    "patina_deep":   "#3A7A6E",  # deep oxide
    "vermilion":     "#D94A3A",  # warnings only
    "rule":          "#444444",  # default border
    "rule_strong":   "#6B5A1A",  # active gold hairline
    "font_ui":       "Segoe UI",
    "font_mono":     "Consolas",
}

# ── Color mixing helpers ──────────────────────────────────────

def _hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _rgb_to_hex(r, g, b):
    return f"#{r:02x}{g:02x}{b:02x}"

def _blend(hex_a, hex_b, t=0.5):
    """Linear blend two hex colors. t=0 → hex_a, t=1 → hex_b."""
    ra, ga, ba = _hex_to_rgb(hex_a)
    rb, gb, bb = _hex_to_rgb(hex_b)
    r = int(ra + (rb - ra) * t)
    g = int(ga + (gb - ga) * t)
    b = int(ba + (bb - ba) * t)
    return _rgb_to_hex(r, g, b)

# Derived theme values
THEME["raised_hover"] = _blend(THEME["raised"], THEME["gold"], 0.06)
THEME["button_primary_bg"] = THEME["gold"]
THEME["button_primary_fg"] = THEME["lacquer"]
THEME["button_primary_hover"] = _blend(THEME["gold"], THEME["gold_pale"], 0.5)
THEME["button_secondary_bg"] = THEME["raised"]
THEME["button_secondary_fg"] = THEME["gold"]
THEME["entry_bg"] = THEME["lacquer_deep"]
THEME["entry_fg"] = THEME["champagne"]
THEME["active_thumb_bg"] = _blend(THEME["raised"], THEME["gold"], 0.15)
THEME["selected_thumb_bg"] = _blend(THEME["raised"], THEME["gold"], 0.08)


class MaskBlock:
    def __init__(self, x, y, w, h, block_type="color", color="#000000", opacity=100, mosaic_size=15):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.block_type = block_type
        self.color = color
        self.opacity = opacity
        self.mosaic_size = mosaic_size

    def contains(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h

    def get_handle_at_canvas(self, cx, cy, ox, oy, scale, threshold=10):
        handles = {
            'nw': (self.x, self.y), 'ne': (self.x + self.w, self.y),
            'sw': (self.x, self.y + self.h), 'se': (self.x + self.w, self.y + self.h),
            'n': (self.x + self.w / 2, self.y), 's': (self.x + self.w / 2, self.y + self.h),
            'w': (self.x, self.y + self.h / 2), 'e': (self.x + self.w, self.y + self.h / 2),
        }
        for name, (ix, iy) in handles.items():
            hx, hy = ix * scale + ox, iy * scale + oy
            if abs(cx - hx) <= threshold and abs(cy - hy) <= threshold:
                return name
        return None

    def get_cursor(self, handle):
        return {'nw': 'top_left_corner', 'ne': 'top_right_corner', 'sw': 'bottom_left_corner',
                'se': 'bottom_right_corner', 'n': 'top_side', 's': 'bottom_side',
                'w': 'left_side', 'e': 'right_side'}.get(handle, 'arrow')

    def to_dict(self):
        return {'x': self.x, 'y': self.y, 'w': self.w, 'h': self.h,
                'block_type': self.block_type, 'color': self.color,
                'opacity': self.opacity, 'mosaic_size': self.mosaic_size}

    @staticmethod
    def from_dict(d):
        return MaskBlock(d['x'], d['y'], d['w'], d['h'], d.get('block_type', 'color'),
                         d.get('color', '#000000'), d.get('opacity', 100), d.get('mosaic_size', 15))


class ImageItem:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.blocks: list[MaskBlock] = []
        self.crop_rect = None
        self.thumb_tk = None


class MaskTool:
    HS = 5
    MIN_SZ = 5
    EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff', '.tif'}
    THUMB_W, THUMB_H = 100, 75

    def __init__(self, root):
        self.root = root
        self.root.title("Batch Crop & Mask Tool")
        self.root.geometry("1300x820")
        self.root.minsize(900, 600)
        self.root.configure(bg=THEME["lacquer"])

        self.original_image = None
        self.display_image = None
        self.blocks: list[MaskBlock] = []
        self.selected_index = -1
        self.crop_rect = None

        self.drag_mode = None
        self.drag_handle = None
        self.drag_start = (0, 0)
        self.drag_block_orig = None
        self.ctrl_copy_index = -1

        self.is_single_mode = True
        self.single_path = None
        self.batch: list[ImageItem] = []
        self.batch_index = -1
        self.current_item: ImageItem = None

        self.output_dir = None

        self.selected_thumbs = set()
        self.last_clicked = -1

        self.mode_var = tk.StringVar(value="mask")
        self.type_var = tk.StringVar(value="color")
        self.color_var = tk.StringVar(value="#000000")
        self.opacity_var = tk.IntVar(value=100)
        self.mosaic_var = tk.IntVar(value=15)

        self.cfg_dir = os.path.join(os.path.expanduser("~"), ".batch_mask_tool")
        os.makedirs(self.cfg_dir, exist_ok=True)
        self.last_cfg = os.path.join(self.cfg_dir, "last_config.json")

        self._drop_queue = queue.Queue()

        self._configure_styles()
        self._build_ui()
        self._bind_keys()
        self._setup_drop()
        self._load_prefs()
        self.root.after(100, self._initial)
        self._poll_drop_queue()

    # ── Theme Setup ────────────────────────────────────────────

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Scrollbar
        style.configure("Vertical.TScrollbar",
                        background=THEME["graphite"],
                        troughcolor=THEME["lacquer"],
                        bordercolor=THEME["lacquer"],
                        arrowcolor=THEME["text_muted"],
                        width=8)
        style.map("Vertical.TScrollbar",
                  background=[("active", THEME["graphite_2"])])

        # Scale
        style.configure("TScale",
                        background=THEME["raised"],
                        troughcolor=THEME["graphite"],
                        bordercolor=THEME["rule"])

        # Progressbar
        style.configure("TProgressbar",
                        background=THEME["gold"],
                        troughcolor=THEME["graphite"],
                        bordercolor=THEME["rule"],
                        thickness=6)

        # LabelFrame
        style.configure("TLabelframe",
                        background=THEME["raised"],
                        bordercolor=THEME["rule"],
                        relief="solid")
        style.configure("TLabelframe.Label",
                        background=THEME["raised"],
                        foreground=THEME["gold"],
                        font=(THEME["font_ui"], 9, "bold"))

        # Separator
        style.configure("TSeparator", background=THEME["rule"])

        # Radiobutton
        style.configure("TRadiobutton",
                        background=THEME["raised"],
                        foreground=THEME["text"],
                        font=(THEME["font_ui"], 10))
        style.map("TRadiobutton",
                  background=[("active", THEME["raised"])],
                  foreground=[("active", THEME["champagne"])])

        # Label
        style.configure("TLabel",
                        background=THEME["raised"],
                        foreground=THEME["text"],
                        font=(THEME["font_ui"], 9))

    # ── Bounds Clipping ───────────────────────────────────────

    def _clip_rect_to_image(self, x, y, w, h, img_w=None, img_h=None):
        if img_w is None and self.original_image:
            img_w, img_h = self.original_image.size
        if not img_w or not img_h:
            return x, y, w, h
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        if x + w > img_w:
            w = img_w - x
        if y + h > img_h:
            h = img_h - y
        if w < self.MIN_SZ:
            w = self.MIN_SZ
            x = max(0, min(x, img_w - w))
        if h < self.MIN_SZ:
            h = self.MIN_SZ
            y = max(0, min(y, img_h - h))
        return int(x), int(y), int(w), int(h)

    def _clip_block_to_image(self, block, img_w=None, img_h=None):
        if img_w is None and self.original_image:
            img_w, img_h = self.original_image.size
        if not img_w or not img_h:
            return
        nx, ny, nw, nh = self._clip_rect_to_image(block.x, block.y, block.w, block.h, img_w, img_h)
        block.x, block.y, block.w, block.h = nx, ny, nw, nh

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self):
        # --- Top Toolbar ---
        tb = tk.Frame(self.root, bg=THEME["raised"], highlightthickness=0)
        tb.pack(fill=tk.X, padx=0, pady=0)

        # Left button group
        tb_left = tk.Frame(tb, bg=THEME["raised"])
        tb_left.pack(side=tk.LEFT, padx=(8, 0), pady=5)

        self._make_btn(tb_left, "Open Image", self.open_single, primary=True).pack(side=tk.LEFT, padx=2)
        self.btn_close = self._make_btn(tb_left, "Close", self.close_image, primary=False)
        self.btn_close.pack(side=tk.LEFT, padx=2)
        self.btn_save = self._make_btn(tb_left, "Save", self.save_current, primary=False)
        self.btn_save.pack(side=tk.LEFT, padx=2)

        sep1 = tk.Frame(tb, bg=THEME["rule"], width=1)
        sep1.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=6)

        self._make_btn(tb_left, "Import Folder", self.import_folder, primary=False).pack(side=tk.LEFT, padx=2)
        self.btn_output_dir = self._make_btn(tb_left, "Output Folder", self.set_output_dir, primary=False)
        self.btn_output_dir.pack(side=tk.LEFT, padx=2)

        sep2 = tk.Frame(tb, bg=THEME["rule"], width=1)
        sep2.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=6)

        # Navigation group
        self.btn_prev = tk.Button(tb, text="◂", font=(THEME["font_ui"], 14), width=2,
                                   bg=THEME["raised"], fg=THEME["text"], bd=0,
                                   activebackground=THEME["graphite"], activeforeground=THEME["gold"],
                                   cursor="hand2", command=self.prev_image)
        self.btn_prev.pack(side=tk.LEFT, padx=1)
        self.btn_next = tk.Button(tb, text="▸", font=(THEME["font_ui"], 14), width=2,
                                   bg=THEME["raised"], fg=THEME["text"], bd=0,
                                   activebackground=THEME["graphite"], activeforeground=THEME["gold"],
                                   cursor="hand2", command=self.next_image)
        self.btn_next.pack(side=tk.LEFT, padx=1)
        self.nav_label = tk.Label(tb, text=" Single Image ", width=14, anchor=tk.CENTER,
                                   font=(THEME["font_ui"], 9, "bold"),
                                   bg=THEME["raised"], fg=THEME["text_muted"])
        self.nav_label.pack(side=tk.LEFT, padx=4)

        sep3 = tk.Frame(tb, bg=THEME["rule"], width=1)
        sep3.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=6)

        self.btn_batch_save = self._make_btn(tb, "Batch Save", self.batch_save, primary=True)
        self.btn_batch_save.pack(side=tk.LEFT, padx=2)

        # Right side: progress bar
        self.progress = ttk.Progressbar(tb, length=0, mode='determinate')
        self.progress.pack(side=tk.RIGHT, padx=(6, 12))

        # Status indicator dot
        self.status_dot = tk.Canvas(tb, width=8, height=8, bg=THEME["raised"], highlightthickness=0)
        self.status_dot.pack(side=tk.RIGHT, padx=(0, 4))
        self._dot_id = self.status_dot.create_oval(1, 1, 7, 7, fill=THEME["text_muted"], outline="")

        self._set_batch_ui(False)

        # --- Body ---
        body = tk.Frame(self.root, bg=THEME["lacquer"])
        body.pack(fill=tk.BOTH, expand=True, padx=0, pady=(1, 0))

        # --- Left Thumbnail Panel ---
        self.left_frame = tk.Frame(body, bg=THEME["lacquer"], width=170)
        self.thumb_canvas = tk.Canvas(self.left_frame, bg=THEME["lacquer"], highlightthickness=0,
                                       width=150, bd=0)
        sb = ttk.Scrollbar(self.left_frame, orient=tk.VERTICAL,
                           command=self.thumb_canvas.yview, style="Vertical.TScrollbar")
        self.thumb_inner = tk.Frame(self.thumb_canvas, bg=THEME["lacquer"])
        self.thumb_inner.bind("<Configure>",
                              lambda e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")))
        self.thumb_canvas.create_window((0, 0), window=self.thumb_inner, anchor=tk.NW)
        self.thumb_canvas.configure(yscrollcommand=sb.set)
        self.thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            self.thumb_canvas.yview_scroll(-int(event.delta / 120), "units")
        for widget in (self.thumb_inner, self.thumb_canvas, self.left_frame):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", lambda e: self.thumb_canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda e: self.thumb_canvas.yview_scroll(1, "units"))

        self.thumb_buttons = []
        self.thumb_frames = []

        # --- Center Canvas ---
        mid = tk.Frame(body, bg=THEME["lacquer"])
        mid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(mid, bg=THEME["lacquer"], highlightthickness=0, cursor="crosshair", bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # --- Right Panel ---
        right = tk.Frame(body, bg=THEME["lacquer"], width=260)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(1, 0))
        right.pack_propagate(False)

        # Section label helper
        def _section_label(parent, text):
            lbl = tk.Label(parent, text=text.upper(),
                           font=(THEME["font_mono"], 8),
                           fg=THEME["gold"], bg=THEME["raised"],
                           anchor=tk.W)
            return lbl

        # Mode Selection
        mode_frame = tk.Frame(right, bg=THEME["raised"], padx=10, pady=8,
                              highlightbackground=THEME["rule"], highlightthickness=1)
        mode_frame.pack(fill=tk.X, pady=(8, 5), padx=4)
        _section_label(mode_frame, "Mode").pack(fill=tk.X, pady=(0, 6))

        rb_font = (THEME["font_ui"], 11, "bold")

        # Mask mode row
        mask_row = tk.Frame(mode_frame, bg=THEME["raised"])
        mask_row.pack(fill=tk.X, pady=3)
        tk.Radiobutton(mask_row, text="Mask", variable=self.mode_var, value="mask",
                       font=rb_font, bg=THEME["raised"], fg=THEME["text"],
                       activebackground=THEME["raised"], activeforeground=THEME["champagne"],
                       selectcolor=THEME["lacquer"], cursor="hand2").pack(side=tk.LEFT)
        self.sync_mask_btn = self._make_btn(mask_row, "Sync All", self.sync_all,
                                             outline=True, compact=True)
        self.sync_mask_btn.pack(side=tk.RIGHT)

        # Crop mode row
        crop_row = tk.Frame(mode_frame, bg=THEME["raised"])
        crop_row.pack(fill=tk.X, pady=3)
        tk.Radiobutton(crop_row, text="Crop", variable=self.mode_var, value="crop",
                       font=rb_font, bg=THEME["raised"], fg=THEME["text"],
                       activebackground=THEME["raised"], activeforeground=THEME["champagne"],
                       selectcolor=THEME["lacquer"], cursor="hand2").pack(side=tk.LEFT)
        self.sync_crop_btn = self._make_btn(crop_row, "Sync All", self.sync_crop_all,
                                             outline=True, compact=True)
        self.sync_crop_btn.pack(side=tk.RIGHT)

        # Mask Type
        f2 = tk.Frame(right, bg=THEME["raised"], padx=10, pady=8,
                       highlightbackground=THEME["rule"], highlightthickness=1)
        f2.pack(fill=tk.X, pady=5, padx=4)
        _section_label(f2, "Mask Type").pack(fill=tk.X, pady=(0, 6))
        for t, v in [("■  Color Block", "color"), ("◐  Blur", "blur"), ("▦  Mosaic", "mosaic")]:
            ttk.Radiobutton(f2, text=t, variable=self.type_var, value=v,
                            command=self._on_type_change, takefocus=False).pack(anchor=tk.W, pady=1)

        # Mask Settings
        f3 = tk.Frame(right, bg=THEME["raised"], padx=10, pady=8,
                       highlightbackground=THEME["rule"], highlightthickness=1)
        f3.pack(fill=tk.X, pady=5, padx=4)
        _section_label(f3, "Settings").pack(fill=tk.X, pady=(0, 6))

        # Color picker row
        color_label = tk.Label(f3, text="Color (color mode)", font=(THEME["font_ui"], 9),
                                bg=THEME["raised"], fg=THEME["text_muted"])
        color_label.pack(anchor=tk.W)
        cf = tk.Frame(f3, bg=THEME["raised"])
        cf.pack(fill=tk.X, pady=(2, 6))
        self.color_preview = tk.Canvas(cf, width=28, height=22,
                                        highlightthickness=1,
                                        highlightbackground=THEME["rule_strong"],
                                        bg=THEME["raised"], bd=0)
        self.color_preview.pack(side=tk.LEFT, padx=(0, 6))
        self.color_preview.create_rectangle(0, 0, 28, 22, fill="#000000", outline="", tags="swatch")
        color_entry = tk.Entry(cf, textvariable=self.color_var, width=9,
                               bg=THEME["entry_bg"], fg=THEME["entry_fg"],
                               insertbackground=THEME["gold"], relief="flat",
                               highlightbackground=THEME["rule"], highlightthickness=1,
                               font=(THEME["font_mono"], 9))
        color_entry.pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(cf, text="Pick", width=4, command=self._pick_color,
                  bg=THEME["graphite_2"], fg=THEME["text"], bd=0,
                  activebackground=THEME["gold"], activeforeground=THEME["lacquer"],
                  font=(THEME["font_ui"], 8), cursor="hand2").pack(side=tk.LEFT)

        # Opacity slider
        op_label = tk.Label(f3, text="Intensity", font=(THEME["font_ui"], 9),
                             bg=THEME["raised"], fg=THEME["text_muted"])
        op_label.pack(anchor=tk.W, pady=(6, 0))
        of = tk.Frame(f3, bg=THEME["raised"])
        of.pack(fill=tk.X, pady=2)
        self.opacity_scale = tk.Scale(of, from_=0, to=100, variable=self.opacity_var,
                                       orient=tk.HORIZONTAL, command=self._on_opacity_change,
                                       bg=THEME["raised"], fg=THEME["text"],
                                       troughcolor=THEME["graphite"],
                                       highlightbackground=THEME["raised"],
                                       highlightthickness=0, bd=0, length=170)
        self.opacity_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.opacity_lbl = tk.Label(of, text="100%", width=5,
                                     bg=THEME["raised"], fg=THEME["text_muted"],
                                     font=(THEME["font_mono"], 9))
        self.opacity_lbl.pack(side=tk.RIGHT)

        # Mosaic Settings
        f4 = tk.Frame(right, bg=THEME["raised"], padx=10, pady=8,
                       highlightbackground=THEME["rule"], highlightthickness=1)
        f4.pack(fill=tk.X, pady=5, padx=4)
        _section_label(f4, "Mosaic").pack(fill=tk.X, pady=(0, 6))
        tk.Label(f4, text="Block Size", font=(THEME["font_ui"], 9),
                bg=THEME["raised"], fg=THEME["text_muted"]).pack(anchor=tk.W)
        mf = tk.Frame(f4, bg=THEME["raised"])
        mf.pack(fill=tk.X, pady=2)
        self.mosaic_scale = tk.Scale(mf, from_=3, to=50, variable=self.mosaic_var,
                                      orient=tk.HORIZONTAL, command=self._on_mosaic_change,
                                      bg=THEME["raised"], fg=THEME["text"],
                                      troughcolor=THEME["graphite"],
                                      highlightbackground=THEME["raised"],
                                      highlightthickness=0, bd=0, length=170)
        self.mosaic_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.mosaic_lbl = tk.Label(mf, text="15", width=5,
                                    bg=THEME["raised"], fg=THEME["text_muted"],
                                    font=(THEME["font_mono"], 9))
        self.mosaic_lbl.pack(side=tk.RIGHT)

        # Config Presets
        f6 = tk.Frame(right, bg=THEME["raised"], padx=10, pady=8,
                       highlightbackground=THEME["rule"], highlightthickness=1)
        f6.pack(fill=tk.X, pady=5, padx=4)
        _section_label(f6, "Presets").pack(fill=tk.X, pady=(0, 6))
        self._make_btn(f6, "Save Preset", self.save_config, primary=False).pack(fill=tk.X, pady=1)
        self._make_btn(f6, "Load Preset", self.load_config, primary=False).pack(fill=tk.X, pady=1)
        self._make_btn(f6, "Auto-Load Last", self._auto_load, primary=False).pack(fill=tk.X, pady=1)

        # --- Status Bar ---
        status_frame = tk.Frame(self.root, bg=THEME["lacquer_deep"], height=26)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        status_frame.pack_propagate(False)
        self.status_var = tk.StringVar(value="Ready — Open an image or drag files to begin")
        tk.Label(status_frame, textvariable=self.status_var, anchor=tk.W, padx=10,
                bg=THEME["lacquer_deep"], fg=THEME["text_muted"],
                font=(THEME["font_ui"], 8)).pack(fill=tk.BOTH, expand=True)

    def _make_btn(self, parent, text, command, primary=False, compact=False, outline=False):
        """Create a styled button. primary=gold fill, outline=gold border on dark bg."""
        if primary:
            bg = THEME["gold"]
            fg = "#1A1A1A"
            hover_bg = THEME["gold_pale"]
            border = THEME["gold_deep"]
        elif outline:
            bg = THEME["raised"]
            fg = THEME["gold"]
            hover_bg = _blend(THEME["raised"], THEME["gold"], 0.12)
            border = THEME["gold_deep"]
        else:
            bg = "#3E3E3E"
            fg = THEME["text"]
            hover_bg = "#4E4E4E"
            border = "#555555"

        if compact:
            font = (THEME["font_ui"], 8, "bold")
            pad_y = 3
            pad_x = 8
        else:
            font = (THEME["font_ui"], 9)
            pad_y = 5
            pad_x = 10

        btn = tk.Button(parent, text=text, command=command,
                        bg=bg, fg=fg, bd=1, padx=pad_x, pady=pad_y,
                        font=font, cursor="hand2",
                        activebackground=hover_bg, activeforeground=fg,
                        highlightbackground=border, highlightthickness=1,
                        relief="solid")
        return btn

    def _set_batch_ui(self, active):
        st = tk.NORMAL if active else tk.DISABLED
        for w in [self.btn_prev, self.btn_next, self.btn_batch_save]:
            w.config(state=st)

    def _show_left(self, show):
        if show and not self.left_frame.winfo_manager():
            self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        elif not show and self.left_frame.winfo_manager():
            self.left_frame.pack_forget()

    # ── Keyboard Shortcuts ────────────────────────────────────

    def _bind_keys(self):
        self.root.bind("<Up>", self._on_up_key, add=True)
        self.root.bind("<Down>", self._on_down_key, add=True)
        self.root.bind("<Delete>", self._handle_delete)
        self.root.bind("<BackSpace>", lambda e: self._handle_delete(e))
        self.root.bind("<Control-d>", lambda e: self.duplicate_block())
        self.root.bind("<Control-D>", lambda e: self.duplicate_block())
        self.root.bind("<Escape>", lambda e: self._deselect_all())
        self.root.bind("<Control-s>", self._handle_ctrl_s)
        self.root.bind("<Control-S>", self._handle_ctrl_s)
        self.root.bind("<Control-a>", self._select_all_thumbs)
        self.root.bind("<Control-A>", self._select_all_thumbs)

    def _on_up_key(self, event):
        self.prev_image()
        return "break"

    def _on_down_key(self, event):
        self.next_image()
        return "break"

    def _handle_delete(self, event=None):
        if self.mode_var.get() == "crop":
            if self.crop_rect:
                self.crop_rect = None
                self._refresh()
                self._save_current()
                self.status_var.set("Crop area cleared")
        else:
            self.delete_block()
        return "break"

    def _handle_ctrl_s(self, event=None):
        self.save_current()
        return "break"

    def _select_all_thumbs(self, event=None):
        if not self.batch:
            return
        self.selected_thumbs = set(range(len(self.batch)))
        self._update_thumb_highlight()
        self.status_var.set(f"Selected {len(self.selected_thumbs)} images")
        return "break"

    # ── Drag & Drop ────────────────────────────────────────────

    def _setup_drop(self):
        if not HAS_WINDND: return
        try:
            hwnd = self.root.winfo_id()
            windnd.hook_dropfiles(hwnd, func=self._on_drop_raw)
        except Exception:
            pass

    def _on_drop_raw(self, files):
        try:
            raw = files[0] if isinstance(files, (list, tuple)) else files
            if isinstance(raw, bytes):
                try: path = raw.decode('gbk', errors='replace')
                except: path = raw.decode('utf-8', errors='replace')
                path = path.split('\x00')[0]
            elif isinstance(raw, str):
                path = raw
            else: return
            path = path.strip().strip('"').strip("'")
            if path: self._drop_queue.put(path)
        except Exception: pass

    def _poll_drop_queue(self):
        try:
            while True:
                path = self._drop_queue.get_nowait()
                if os.path.isdir(path):
                    self._do_import(path)
                elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in self.EXTS:
                    self._do_open_single(path)
        except queue.Empty: pass
        self.root.after(100, self._poll_drop_queue)

    # ── Preferences ────────────────────────────────────────────

    def _load_prefs(self):
        p = os.path.join(self.cfg_dir, "preferences.json")
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f: d = json.load(f)
                self.color_var.set(d.get('color', '#000000'))
                self.opacity_var.set(d.get('opacity', 100))
                self.mosaic_var.set(d.get('mosaic_size', 15))
                self.type_var.set(d.get('type', 'color'))
                self.output_dir = d.get('output_dir', None)
                self._update_color_preview(); self._on_opacity_change(); self._on_mosaic_change()
            except: pass

    def _save_prefs(self):
        try:
            with open(os.path.join(self.cfg_dir, "preferences.json"), 'w', encoding='utf-8') as f:
                json.dump({'color': self.color_var.get(), 'opacity': self.opacity_var.get(),
                           'mosaic_size': self.mosaic_var.get(), 'type': self.type_var.get(),
                           'output_dir': self.output_dir}, f, ensure_ascii=False, indent=2)
        except: pass

    # ── Panel Callbacks ───────────────────────────────────────

    def set_output_dir(self):
        dir_selected = filedialog.askdirectory(title="Select default output folder")
        if dir_selected:
            self.output_dir = dir_selected
            self._save_prefs()
            self._set_dot("patina")
            self.status_var.set(f"Output folder: {self.output_dir}")
        else:
            if messagebox.askyesno("Clear Setting", "Clear the output folder setting? You'll be prompted to choose a location each time you save."):
                self.output_dir = None
                self._save_prefs()
                self._set_dot("muted")
                self.status_var.set("Output folder cleared — you'll choose per save")

    def _set_dot(self, color_key):
        colors = {"gold": THEME["gold"], "patina": THEME["patina"],
                  "muted": THEME["text_muted"], "vermilion": THEME["vermilion"]}
        self.status_dot.itemconfig(self._dot_id, fill=colors.get(color_key, THEME["text_muted"]))

    def _pick_color(self):
        c = colorchooser.askcolor(self.color_var.get(), title="Pick Color")
        if c and c[1]: self.color_var.set(c[1]); self._update_color_preview(); self._sync_block()

    def _update_color_preview(self):
        self.color_preview.delete("swatch")
        self.color_preview.create_rectangle(0, 0, 28, 22, fill=self.color_var.get(), outline="", tags="swatch")

    def _on_type_change(self): self._sync_block(); self._refresh()
    def _on_opacity_change(self, *_): self.opacity_lbl.config(text=f"{int(self.opacity_var.get())}%"); self._sync_block(); self._refresh()
    def _on_mosaic_change(self, *_): self.mosaic_lbl.config(text=f"{int(self.mosaic_var.get())}"); self._sync_block(); self._refresh()

    def _sync_block(self):
        if 0 <= self.selected_index < len(self.blocks):
            b = self.blocks[self.selected_index]
            b.block_type, b.color = self.type_var.get(), self.color_var.get()
            b.opacity, b.mosaic_size = int(self.opacity_var.get()), int(self.mosaic_var.get())
            self._update_color_preview()
            self._save_current()

    def _load_block_to_panel(self, b):
        self.type_var.set(b.block_type); self.color_var.set(b.color)
        self.opacity_var.set(b.opacity); self.mosaic_var.set(b.mosaic_size)
        self._update_color_preview(); self._on_opacity_change(); self._on_mosaic_change()

    # ── File Operations ───────────────────────────────────────

    def open_single(self):
        path = filedialog.askopenfilename(title="Select Image",
                                          filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.webp *.tiff"),
                                                     ("All Files", "*.*")])
        if path: self._do_open_single(path)

    def _do_open_single(self, path):
        self._save_current()
        self.is_single_mode = True; self.single_path = path
        self.batch.clear(); self.batch_index = -1; self.current_item = None
        try:
            self.original_image = Image.open(path).convert("RGB")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open image:\n{e}"); return
        self.blocks.clear(); self.selected_index = -1
        self.crop_rect = None
        self._set_batch_ui(False); self._show_left(False); self._clear_thumb_list()
        self._fit_display()
        self.nav_label.config(text=" Single Image ")
        self._set_dot("patina")
        self.status_var.set(f"{os.path.basename(path)}  |  {self.original_image.size[0]} × {self.original_image.size[1]}")

    def close_image(self):
        if not self.original_image: return
        if self.blocks and not messagebox.askyesno("Close", "Closing will discard current masks. Continue?"): return
        self.original_image = self.display_image = None
        self.is_single_mode = True; self.single_path = None
        self.blocks.clear(); self.selected_index = -1
        self.crop_rect = None
        self._show_left(False); self._refresh()
        self.nav_label.config(text=" Single Image ")
        self._set_dot("muted")
        self.status_var.set("Image closed")

    def _get_unique_path(self, folder, filename):
        name, ext = os.path.splitext(filename)
        out = os.path.join(folder, filename)
        if not os.path.exists(out): return out
        i = 1
        while True:
            out = os.path.join(folder, f"{name}({i}){ext}")
            if not os.path.exists(out): return out
            i += 1

    def _ask_overwrite(self, filepath):
        return messagebox.askyesno("File Exists",
                                   f"{os.path.basename(filepath)}\nalready exists. Overwrite?")

    def save_current(self):
        if not self.original_image:
            return
        if self.is_single_mode and self.single_path:
            base_name = os.path.basename(self.single_path)
        elif self.current_item:
            base_name = self.current_item.name
        else:
            messagebox.showerror("Error", "No image to save")
            return

        if self.output_dir and os.path.isdir(self.output_dir):
            target_path = os.path.join(self.output_dir, base_name)
            if os.path.exists(target_path):
                if not self._ask_overwrite(target_path):
                    self.status_var.set("Save cancelled")
                    return
        else:
            target_path = filedialog.asksaveasfilename(
                title="Save Image", defaultextension=".png",
                initialfile=base_name,
                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")]
            )
            if not target_path:
                return

        try:
            self._save_current()
            result = self._apply_crop_and_mask(self.original_image, self.crop_rect, self.blocks)
            if target_path.lower().endswith(('.jpg', '.jpeg')):
                result = result.convert("RGB")
            result.save(target_path)
            self._set_dot("patina")
            self.status_var.set(f"Saved: {target_path}")
        except Exception as e:
            self._set_dot("vermilion")
            messagebox.showerror("Error", str(e))

    # ── Batch Operations ──────────────────────────────────────

    def import_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing images")
        if folder: self._do_import(folder)

    def _do_import(self, folder):
        files = [os.path.join(folder, fn) for fn in sorted(os.listdir(folder))
                 if os.path.splitext(fn)[1].lower() in self.EXTS]
        if not files:
            messagebox.showinfo("Notice", "No supported images found in this folder")
            return
        self._save_current()
        self.is_single_mode = False; self.single_path = None
        self.batch = [ImageItem(p) for p in files]; self.batch_index = 0
        self.selected_thumbs.clear()
        self.last_clicked = -1
        self._gen_thumbs(); self._build_thumb_list(); self._show_left(True)
        self._load_item(0); self._set_batch_ui(True)
        self._set_dot("gold")
        self.status_var.set(f"Imported {len(files)} images — Right-click thumbnails for multi-select actions")

    def _gen_thumbs(self):
        for item in self.batch:
            try:
                img = Image.open(item.path).convert("RGB")
                img.thumbnail((self.THUMB_W * 2, self.THUMB_H * 2), Image.LANCZOS)
                item.thumb_tk = self._make_thumb_tk(img)
            except: pass

    def _make_thumb_tk(self, img):
        tw, th = self.THUMB_W, self.THUMB_H
        ratio = min(tw / img.width, th / img.height, 1.0)
        nw, nh = int(img.width * ratio), int(img.height * ratio)
        resized = img.resize((nw, nh), Image.LANCZOS)
        c_img = Image.new("RGB", (tw, th), (18, 18, 18))
        c_img.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
        return ImageTk.PhotoImage(c_img)

    def _clear_thumb_list(self):
        for w in self.thumb_inner.winfo_children():
            w.destroy()
        self.thumb_buttons.clear()
        self.thumb_frames.clear()
        self.selected_thumbs.clear()

    def _build_thumb_list(self):
        self._clear_thumb_list()
        for i, item in enumerate(self.batch):
            f = tk.Frame(self.thumb_inner, bg=THEME["lacquer"])
            f.pack(fill=tk.X, padx=2, pady=1)
            btn = tk.Button(f, image=item.thumb_tk, borderwidth=0, highlightthickness=0,
                            bg=THEME["lacquer"], activebackground=THEME["graphite"],
                            cursor="hand2")
            btn.image = item.thumb_tk
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
            btn.bind("<Button-1>", lambda e, idx=i: self._on_thumb_click(e, idx))
            btn.bind("<Button-3>", lambda e, idx=i: self._show_thumb_menu(e, idx))
            lbl = tk.Label(f, text=str(i+1), width=4, anchor=tk.CENTER,
                           font=(THEME["font_mono"], 8), fg=THEME["text_faint"], bg=THEME["lacquer"])
            lbl.pack(side=tk.RIGHT, padx=(0, 2))
            self.thumb_frames.append(f)
            self.thumb_buttons.append(btn)
        self._update_thumb_highlight()

    # ── Thumbnail Click Logic ─────────────────────────────────

    def _on_thumb_click(self, event, idx):
        ctrl = (event.state & 0x4) != 0
        shift = (event.state & 0x1) != 0

        if shift and self.last_clicked != -1:
            start = min(self.last_clicked, idx)
            end = max(self.last_clicked, idx)
            self.selected_thumbs = set(range(start, end+1))
            self._update_thumb_highlight()
            self.status_var.set(f"Selected {len(self.selected_thumbs)} images")
        elif ctrl:
            if idx in self.selected_thumbs:
                self.selected_thumbs.discard(idx)
            else:
                self.selected_thumbs.add(idx)
            self.last_clicked = idx
            self._update_thumb_highlight()
            self.status_var.set(f"Selected {len(self.selected_thumbs)} images")
        else:
            self._load_item(idx)
            self.last_clicked = idx
            self.status_var.set(f"Image {idx+1}/{len(self.batch)}")

    def _update_thumb_highlight(self):
        for i, frame in enumerate(self.thumb_frames):
            if i == self.batch_index:
                frame.config(bg=THEME["active_thumb_bg"])
                for child in frame.winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(bg=THEME["active_thumb_bg"], fg=THEME["gold"])
                    elif isinstance(child, tk.Button):
                        child.config(bg=THEME["active_thumb_bg"], activebackground=THEME["active_thumb_bg"])
            else:
                if i in self.selected_thumbs:
                    frame.config(bg=THEME["selected_thumb_bg"])
                    for child in frame.winfo_children():
                        if isinstance(child, tk.Label):
                            child.config(bg=THEME["selected_thumb_bg"], fg=THEME["text_muted"])
                        elif isinstance(child, tk.Button):
                            child.config(bg=THEME["selected_thumb_bg"], activebackground=THEME["selected_thumb_bg"])
                else:
                    frame.config(bg=THEME["lacquer"])
                    for child in frame.winfo_children():
                        if isinstance(child, tk.Label):
                            child.config(bg=THEME["lacquer"], fg=THEME["text_faint"])
                        elif isinstance(child, tk.Button):
                            child.config(bg=THEME["lacquer"], activebackground=THEME["graphite"])
        if 0 <= self.batch_index < len(self.thumb_frames):
            self._scroll_to_thumb(self.batch_index)

    def _scroll_to_thumb(self, idx):
        if idx < 0 or idx >= len(self.thumb_frames):
            return
        self.thumb_inner.update_idletasks()
        frame = self.thumb_frames[idx]
        y0 = frame.winfo_y()
        y1 = y0 + frame.winfo_height()
        canvas_top = self.thumb_canvas.canvasy(0)
        canvas_bottom = self.thumb_canvas.canvasy(self.thumb_canvas.winfo_height())
        if y0 >= canvas_top and y1 <= canvas_bottom:
            return
        target_y = y0 - (self.thumb_canvas.winfo_height() // 3)
        target_y = max(0, target_y)
        total_height = max(1, self.thumb_inner.winfo_height())
        ratio = target_y / total_height
        ratio = max(0.0, min(1.0, ratio))
        self.thumb_canvas.yview_moveto(ratio)

    def _show_thumb_menu(self, event, idx):
        if idx not in self.selected_thumbs:
            self.selected_thumbs = {idx}
            self.batch_index = idx
            self._load_item(idx)
            self.last_clicked = idx

        menu = tk.Menu(self.root, tearoff=0,
                       bg=THEME["raised"], fg=THEME["text"],
                       activebackground=THEME["graphite"],
                       activeforeground=THEME["gold"],
                       font=(THEME["font_ui"], 9))
        menu.add_command(label="Sync from Current", command=self.sync_selected)
        menu.add_command(label="Clear All Edits", command=self.clear_selected_ops)
        menu.add_separator()
        menu.add_command(label="Save Selected As...", command=self.save_selected)
        menu.post(event.x_root, event.y_root)

    def sync_selected(self):
        if not self.original_image:
            messagebox.showwarning("Notice", "Open an image as the source first")
            return
        if not self.selected_thumbs:
            messagebox.showwarning("Notice", "No images selected")
            return
        self._save_current()
        src_w, src_h = self.original_image.size
        src_blocks = [b.to_dict() for b in self.blocks]
        src_crop = self.crop_rect[:] if self.crop_rect else None

        synced = 0
        for idx in self.selected_thumbs:
            if idx == self.batch_index:
                continue
            item = self.batch[idx]
            try:
                img = Image.open(item.path).convert("RGB")
                iw, ih = img.size
                if iw == 0 or ih == 0:
                    continue
                sx, sy = iw / src_w, ih / src_h
                new_blocks = []
                for bd in src_blocks:
                    nb = MaskBlock.from_dict(bd)
                    nb.x, nb.y = bd['x'] * sx, bd['y'] * sy
                    nb.w, nb.h = max(self.MIN_SZ, bd['w'] * sx), max(self.MIN_SZ, bd['h'] * sy)
                    self._clip_block_to_image(nb, iw, ih)
                    new_blocks.append(nb)
                item.blocks = new_blocks
                if src_crop:
                    new_crop = [
                        src_crop[0] * sx, src_crop[1] * sy,
                        src_crop[2] * sx, src_crop[3] * sy
                    ]
                    new_crop[0] = max(0, min(new_crop[0], iw-1))
                    new_crop[1] = max(0, min(new_crop[1], ih-1))
                    new_crop[2] = max(self.MIN_SZ, min(new_crop[2], iw - new_crop[0]))
                    new_crop[3] = max(self.MIN_SZ, min(new_crop[3], ih - new_crop[1]))
                    item.crop_rect = new_crop
                else:
                    item.crop_rect = None
                self._refresh_thumb(idx)
                synced += 1
            except Exception:
                pass
        self._set_dot("patina")
        self.status_var.set(f"Synced to {synced} image(s)")
        self._refresh()

    def clear_selected_ops(self):
        if not self.selected_thumbs:
            messagebox.showwarning("Notice", "No images selected")
            return
        if not messagebox.askyesno("Confirm", f"Clear all masks and crops on {len(self.selected_thumbs)} image(s)?"):
            return
        cleared = 0
        for idx in self.selected_thumbs:
            if idx == self.batch_index:
                continue
            item = self.batch[idx]
            item.blocks = []
            item.crop_rect = None
            self._refresh_thumb(idx)
            cleared += 1
        if self.batch_index in self.selected_thumbs:
            self.blocks.clear()
            self.crop_rect = None
            self.selected_index = -1
            self._refresh()
            self._save_current()
            self._refresh_thumb(self.batch_index)
            cleared += 1
        self.status_var.set(f"Cleared edits on {cleared} image(s)")

    def save_selected(self):
        if not self.selected_thumbs:
            messagebox.showwarning("Notice", "No images selected")
            return
        if len(self.selected_thumbs) > 1:
            if not self.output_dir or not os.path.isdir(self.output_dir):
                dir_selected = filedialog.askdirectory(title="Select output folder")
                if not dir_selected:
                    return
                self.output_dir = dir_selected
                self._save_prefs()
            out_dir = self.output_dir
            os.makedirs(out_dir, exist_ok=True)
            saved = 0
            for idx in self.selected_thumbs:
                item = self.batch[idx]
                target_path = os.path.join(out_dir, item.name)
                if os.path.exists(target_path):
                    if not self._ask_overwrite(target_path):
                        continue
                try:
                    img = Image.open(item.path).convert("RGB")
                    result = self._apply_crop_and_mask(img, item.crop_rect, item.blocks)
                    if target_path.lower().endswith(('.jpg', '.jpeg')):
                        result = result.convert("RGB")
                    result.save(target_path)
                    saved += 1
                except Exception as e:
                    messagebox.showerror("Save Failed", f"{item.name}\n{str(e)}")
            self._set_dot("patina")
            self.status_var.set(f"Saved {saved} image(s) to {out_dir}")
        else:
            idx = next(iter(self.selected_thumbs))
            item = self.batch[idx]
            if self.output_dir and os.path.isdir(self.output_dir):
                target_path = os.path.join(self.output_dir, item.name)
                if os.path.exists(target_path) and not self._ask_overwrite(target_path):
                    return
            else:
                target_path = filedialog.asksaveasfilename(
                    title="Save As", defaultextension=".png",
                    initialfile=item.name,
                    filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")]
                )
                if not target_path:
                    return
            try:
                img = Image.open(item.path).convert("RGB")
                result = self._apply_crop_and_mask(img, item.crop_rect, item.blocks)
                if target_path.lower().endswith(('.jpg', '.jpeg')):
                    result = result.convert("RGB")
                result.save(target_path)
                self.status_var.set(f"Saved: {target_path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _refresh_thumb(self, idx):
        if idx < 0 or idx >= len(self.batch):
            return
        item = self.batch[idx]
        try:
            img = Image.open(item.path).convert("RGB")
            img.thumbnail((self.THUMB_W * 2, self.THUMB_H * 2), Image.LANCZOS)
            item.thumb_tk = self._make_thumb_tk(img)
            if idx < len(self.thumb_buttons):
                btn = self.thumb_buttons[idx]
                btn.config(image=item.thumb_tk)
                btn.image = item.thumb_tk
        except:
            pass

    def _save_current(self):
        if not self.is_single_mode and self.current_item and 0 <= self.batch_index < len(self.batch):
            self.current_item.blocks = [MaskBlock(b.x, b.y, b.w, b.h, b.block_type, b.color, b.opacity, b.mosaic_size) for b in self.blocks]
            self.current_item.crop_rect = self.crop_rect.copy() if self.crop_rect else None
            self._refresh_thumb(self.batch_index)

    def _load_item(self, idx):
        if not (0 <= idx < len(self.batch)):
            return
        self._save_current()
        self.selected_thumbs = {idx}
        self.batch_index = idx
        self.current_item = self.batch[idx]
        self.is_single_mode = False
        try:
            self.original_image = Image.open(self.current_item.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open:\n{e}")
            return
        self.blocks = [MaskBlock.from_dict(b.to_dict()) for b in self.current_item.blocks]
        self.crop_rect = self.current_item.crop_rect.copy() if self.current_item.crop_rect else None
        self.selected_index = -1
        self._fit_display()
        self._update_thumb_highlight()
        self._set_batch_ui(True)
        self.nav_label.config(text=f" {idx + 1} / {len(self.batch)} ")
        self.status_var.set(f"{self.current_item.name}  |  {self.original_image.size[0]} × {self.original_image.size[1]}  |  Masks: {len(self.blocks)}")

    def prev_image(self):
        if self.batch and self.batch_index > 0:
            self._load_item(self.batch_index - 1)

    def next_image(self):
        if self.batch and self.batch_index < len(self.batch) - 1:
            self._load_item(self.batch_index + 1)

    def sync_all(self):
        if not self.original_image:
            messagebox.showwarning("Notice", "Open an image first")
            return
        if not self.blocks:
            messagebox.showwarning("Notice", "No masks on current image")
            return
        self._save_current()
        src_w, src_h = self.original_image.size
        src_blocks = [b.to_dict() for b in self.blocks]
        synced = 0
        for idx, item in enumerate(self.batch):
            try:
                img = Image.open(item.path).convert("RGB")
                iw, ih = img.size
                if iw == 0 or ih == 0:
                    continue
                sx, sy = iw / src_w, ih / src_h
                item.blocks = []
                for bd in src_blocks:
                    nb = MaskBlock.from_dict(bd)
                    nb.x, nb.y = bd['x'] * sx, bd['y'] * sy
                    nb.w, nb.h = max(self.MIN_SZ, bd['w'] * sx), max(self.MIN_SZ, bd['h'] * sy)
                    self._clip_block_to_image(nb, iw, ih)
                    item.blocks.append(nb)
                synced += 1
                self._refresh_thumb(idx)
            except:
                continue
        if self.current_item:
            for b in self.current_item.blocks:
                self._clip_block_to_image(b, self.original_image.width, self.original_image.height)
        self.blocks = [MaskBlock.from_dict(b.to_dict()) for b in self.current_item.blocks]
        self.selected_index = -1
        self._refresh()
        self._set_dot("patina")
        self.status_var.set(f"Masks synced to {synced} image(s) — fine-tune individually before saving")

    def sync_crop_all(self):
        if not self.original_image:
            messagebox.showwarning("Notice", "Open an image first")
            return
        if not self.crop_rect:
            messagebox.showwarning("Notice", "No crop area on current image")
            return
        self._save_current()
        src_w, src_h = self.original_image.size
        src_crop = self.crop_rect[:]
        synced = 0
        for idx, item in enumerate(self.batch):
            try:
                img = Image.open(item.path).convert("RGB")
                iw, ih = img.size
                if iw == 0 or ih == 0:
                    continue
                sx, sy = iw / src_w, ih / src_h
                new_crop = [
                    src_crop[0] * sx, src_crop[1] * sy,
                    src_crop[2] * sx, src_crop[3] * sy
                ]
                new_crop[0] = max(0, min(new_crop[0], iw-1))
                new_crop[1] = max(0, min(new_crop[1], ih-1))
                new_crop[2] = max(self.MIN_SZ, min(new_crop[2], iw - new_crop[0]))
                new_crop[3] = max(self.MIN_SZ, min(new_crop[3], ih - new_crop[1]))
                item.crop_rect = new_crop
                synced += 1
                self._refresh_thumb(idx)
            except:
                continue
        if self.crop_rect:
            img_w, img_h = self.original_image.size
            x, y, w, h = self.crop_rect
            x, y, w, h = self._clip_rect_to_image(x, y, w, h, img_w, img_h)
            self.crop_rect = [x, y, w, h]
        self._refresh()
        self._set_dot("patina")
        self.status_var.set(f"Crop area synced to {synced} image(s)")

    def batch_save(self):
        if not self.batch:
            messagebox.showwarning("Notice", "No images loaded")
            return
        if not self.output_dir or not os.path.isdir(self.output_dir):
            if messagebox.askyesno("No Output Folder", "Set a default output folder first?"):
                self.set_output_dir()
                if not self.output_dir:
                    return
            else:
                return
        self._save_current()
        out_dir = self.output_dir
        os.makedirs(out_dir, exist_ok=True)

        self.progress['maximum'] = len(self.batch)
        self.progress['value'] = 0
        self.progress['length'] = 120
        self.status_var.set("Saving batch...")

        overwrite_all = None

        def do_save():
            nonlocal overwrite_all
            saved, skipped = 0, 0
            for i, item in enumerate(self.batch):
                target_path = os.path.join(out_dir, item.name)
                need_save = True
                if os.path.exists(target_path):
                    if overwrite_all is None:
                        resp = messagebox.askyesnocancel("File Exists",
                                                         f"{item.name}\nalready exists. Overwrite?\n\nYes = Overwrite  No = Skip  Cancel = Skip All")
                        if resp is None:
                            overwrite_all = False
                            need_save = False
                        elif resp:
                            overwrite_all = True
                        else:
                            need_save = False
                    elif not overwrite_all:
                        need_save = False
                if need_save:
                    try:
                        img = Image.open(item.path).convert("RGB")
                        result = self._apply_crop_and_mask(img, item.crop_rect, item.blocks)
                        if target_path.lower().endswith(('.jpg', '.jpeg')):
                            result = result.convert("RGB")
                        result.save(target_path)
                        saved += 1
                    except Exception as e:
                        messagebox.showerror("Save Failed", f"{item.name}\n{str(e)}")
                        skipped += 1
                else:
                    skipped += 1
                self.root.after(0, lambda v=i+1: self.progress.configure(value=v))

            self.root.after(0, lambda: self._save_done(saved, skipped, out_dir))

        threading.Thread(target=do_save, daemon=True).start()

    def _save_done(self, saved, skipped, out_dir):
        self.progress['length'] = 0
        msg = f"Successfully saved {saved} image(s) to:\n{out_dir}"
        if skipped:
            msg += f"\nSkipped/Failed: {skipped}"
        self._set_dot("patina")
        self.status_var.set(f"Batch complete — saved {saved}, skipped {skipped}")
        messagebox.showinfo("Batch Save Complete", msg)

    # ── Configuration Presets ─────────────────────────────────

    def save_config(self):
        if not self.original_image:
            messagebox.showwarning("Notice", "Open an image first")
            return
        path = filedialog.asksaveasfilename(title="Save Preset", defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        self._write_cfg(path)
        self._write_cfg(self.last_cfg)
        self.status_var.set("Preset saved")

    def load_config(self):
        if not self.original_image:
            messagebox.showwarning("Notice", "Open an image first")
            return
        path = filedialog.askopenfilename(title="Load Preset", filetypes=[("JSON", "*.json")])
        if path:
            self._apply_cfg(path)

    def _auto_load(self):
        if not self.original_image:
            messagebox.showwarning("Notice", "Open an image first")
            return
        if os.path.exists(self.last_cfg):
            self._apply_cfg(self.last_cfg)
        else:
            messagebox.showinfo("Notice", "No previous preset found")

    def _write_cfg(self, path):
        w, h = self.original_image.size
        data = {
            'image_width': w, 'image_height': h,
            'blocks': [b.to_dict() for b in self.blocks],
            'crop_rect': self.crop_rect
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._save_prefs()

    def _apply_cfg(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            iw, ih = self.original_image.size
            cw, ch = cfg['image_width'], cfg['image_height']
            if cw == 0 or ch == 0:
                return
            sx, sy = iw / cw, ih / ch
            self.blocks = []
            for bd in cfg['blocks']:
                nb = MaskBlock.from_dict(bd)
                nb.x, nb.y = bd['x'] * sx, bd['y'] * sy
                nb.w, nb.h = max(self.MIN_SZ, bd['w'] * sx), max(self.MIN_SZ, bd['h'] * sy)
                self._clip_block_to_image(nb, iw, ih)
                self.blocks.append(nb)
            crop = cfg.get('crop_rect')
            if crop and len(crop) == 4:
                x, y, w, h = crop
                x, y, w, h = self._clip_rect_to_image(x*sx, y*sy, w*sx, h*sy, iw, ih)
                self.crop_rect = [x, y, w, h]
            else:
                self.crop_rect = None
            self.selected_index = -1
            self._refresh()
            self.status_var.set(f"Preset loaded ({len(self.blocks)} mask(s), crop {'on' if self.crop_rect else 'off'})")
            if self.current_item:
                self.current_item.blocks = [MaskBlock.from_dict(b.to_dict()) for b in self.blocks]
                self.current_item.crop_rect = self.crop_rect.copy() if self.crop_rect else None
                self._refresh_thumb(self.batch_index)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Mask Operations ───────────────────────────────────────

    def duplicate_block(self):
        if self.mode_var.get() != "mask":
            messagebox.showinfo("Notice", "Switch to Mask mode first")
            return
        if not (0 <= self.selected_index < len(self.blocks)):
            messagebox.showinfo("Notice", "Select a mask first")
            return
        s = self.blocks[self.selected_index]
        self.blocks.append(MaskBlock(s.x + 20, s.y + 20, s.w, s.h, s.block_type, s.color, s.opacity, s.mosaic_size))
        self.selected_index = len(self.blocks) - 1
        self._refresh()
        self._save_current()

    def delete_block(self):
        if self.mode_var.get() != "mask":
            messagebox.showinfo("Notice", "Switch to Mask mode first")
            return
        if 0 <= self.selected_index < len(self.blocks):
            self.blocks.pop(self.selected_index)
            self.selected_index = -1
            self._refresh()
            self._save_current()

    def clear_blocks(self):
        if self.mode_var.get() != "mask":
            messagebox.showinfo("Notice", "Switch to Mask mode first")
            return
        if self.blocks and messagebox.askyesno("Confirm", "Clear all masks?"):
            self.blocks.clear()
            self.selected_index = -1
            self._refresh()
            self._save_current()

    def _deselect_all(self):
        self.selected_index = -1
        self._refresh()

    # ── Coordinate Helpers ────────────────────────────────────

    def _get_off(self):
        if not self.display_image:
            return 0, 0, 1.0
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        iw, ih = self.display_image.size
        ox, oy = max(0, (cw - iw) / 2), max(0, (ch - ih) / 2)
        s = (self.display_image.size[0] / self.original_image.size[0] if self.original_image and self.original_image.size[0] > 0 else 1.0)
        return ox, oy, s

    def _c2i(self, cx, cy):
        ox, oy, s = self._get_off()
        return (cx - ox) / s, (cy - oy) / s

    def _i2c(self, ix, iy):
        ox, oy, s = self._get_off()
        return ix * s + ox, iy * s + oy

    def _fit_display(self):
        if not self.original_image:
            self._refresh()
            return
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        iw, ih = self.original_image.size
        r = min(cw / iw, ch / ih, 1.0)
        nw, nh = int(iw * r), int(ih * r)
        if nw < 1 or nh < 1:
            return
        self.display_image = self.original_image.resize((nw, nh), Image.LANCZOS)
        self._refresh()

    def _initial(self):
        self._fit_display()

    def _on_canvas_resize(self, _=None):
        self._fit_display()

    # ── Canvas Rendering ──────────────────────────────────────

    def _refresh(self):
        self.canvas.delete("all")
        if not self.display_image:
            self.canvas.create_text(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2,
                                    text=("Drop an image or folder here to begin\n\n"
                                          "Keyboard Shortcuts:\n"
                                          "↑ ↓    Navigate images\n"
                                          "Ctrl+D  Duplicate mask\n"
                                          "Delete  Remove mask / crop\n"
                                          "Ctrl+S  Save\n"
                                          "Esc     Deselect\n\n"
                                          "Select Mask or Crop mode in the right panel"),
                                    fill=THEME["text_faint"],
                                    font=(THEME["font_ui"], 11), justify=tk.CENTER)
            return
        ox, oy, s = self._get_off()
        iw, ih = self.display_image.size

        # Draw the original image
        self._photo = ImageTk.PhotoImage(self.display_image)
        self.canvas.create_image(ox, oy, anchor=tk.NW, image=self._photo)

        # Draw mask preview overlay
        preview = self._apply_effects(self.display_image, self.blocks, False)
        self._preview = ImageTk.PhotoImage(preview)
        self.canvas.create_image(ox, oy, anchor=tk.NW, image=self._preview)

        # Crop rectangle — verdigris patina
        if self.crop_rect:
            cx1, cy1 = self._i2c(self.crop_rect[0], self.crop_rect[1])
            cx2, cy2 = self._i2c(self.crop_rect[0] + self.crop_rect[2], self.crop_rect[1] + self.crop_rect[3])
            self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline=THEME["patina"], width=2, dash=(5, 3))
            hs = self.HS
            handles = {'nw': (cx1, cy1), 'ne': (cx2, cy1), 'sw': (cx1, cy2), 'se': (cx2, cy2),
                       'n': ((cx1+cx2)/2, cy1), 's': ((cx1+cx2)/2, cy2),
                       'w': (cx1, (cy1+cy2)/2), 'e': (cx2, (cy1+cy2)/2)}
            for hx, hy in handles.values():
                self.canvas.create_rectangle(hx-hs, hy-hs, hx+hs, hy+hs, fill=THEME["champagne"], outline=THEME["patina"])

        # Selected mask — kinpaku gold
        if 0 <= self.selected_index < len(self.blocks):
            b = self.blocks[self.selected_index]
            cx1, cy1 = self._i2c(b.x, b.y)
            cx2, cy2 = self._i2c(b.x + b.w, b.y + b.h)
            self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline=THEME["gold"], width=2, dash=(5, 3))
            hs = self.HS
            for _, (hx, hy) in {'nw': (cx1, cy1), 'ne': (cx2, cy1), 'sw': (cx1, cy2), 'se': (cx2, cy2),
                                 'n': ((cx1+cx2)/2, cy1), 's': ((cx1+cx2)/2, cy2),
                                 'w': (cx1, (cy1+cy2)/2), 'e': (cx2, (cy1+cy2)/2)}.items():
                self.canvas.create_rectangle(hx-hs, hy-hs, hx+hs, hy+hs, fill=THEME["champagne"], outline=THEME["gold"])

        # Image border — subtle hairline
        self.canvas.create_rectangle(ox, oy, ox+iw, oy+ih, outline=THEME["rule"])

    # ── Image Processing ──────────────────────────────────────

    def _apply_crop_and_mask(self, img, crop_rect, blocks):
        if crop_rect and len(crop_rect) == 4:
            x, y, w, h = [int(v) for v in crop_rect]
            x = max(0, x); y = max(0, y)
            w = min(w, img.width - x); h = min(h, img.height - y)
            if w > 0 and h > 0:
                img = img.crop((x, y, x+w, y+h))
                new_blocks = []
                for b in blocks:
                    bx1, by1, bx2, by2 = b.x, b.y, b.x+b.w, b.y+b.h
                    cx1, cy1, cx2, cy2 = x, y, x+w, y+h
                    ix1, iy1 = max(bx1, cx1), max(by1, cy1)
                    ix2, iy2 = min(bx2, cx2), min(by2, cy2)
                    if ix2 > ix1 and iy2 > iy1:
                        nb = MaskBlock(ix1 - x, iy1 - y, ix2 - ix1, iy2 - iy1,
                                       b.block_type, b.color, b.opacity, b.mosaic_size)
                        new_blocks.append(nb)
                blocks = new_blocks
        return self._apply_effects(img, blocks, True)

    def _apply_effects(self, base, blocks, orig_scale=True):
        if not blocks: return base.copy()
        result = base.copy()
        iw, ih = result.size
        for b in blocks:
            if orig_scale:
                x1, y1, x2, y2 = int(b.x), int(b.y), int(b.x+b.w), int(b.y+b.h)
            else:
                _, _, sc = self._get_off()
                x1, y1 = int(b.x*sc), int(b.y*sc)
                x2, y2 = int((b.x+b.w)*sc), int((b.y+b.h)*sc)
            x1, y1 = max(0, min(x1, iw-1)), max(0, min(y1, ih-1))
            x2, y2 = max(x1+1, min(x2, iw)), max(y1+1, min(y2, ih))
            region = result.crop((x1, y1, x2, y2))
            a = int(b.opacity / 100 * 255)
            if b.block_type == "color":
                ov = Image.new("RGB", region.size, b.color)
                ov.putalpha(a)
                region = Image.alpha_composite(region.convert("RGBA"), ov).convert("RGB")
            elif b.block_type == "blur":
                rw, rh = region.size
                blurred = region.filter(ImageFilter.GaussianBlur(radius=max(5, min(int(min(rw, rh)/3), 40))))
                bl = blurred.convert("RGBA"); bl.putalpha(a)
                region = Image.alpha_composite(region.convert("RGBA"), bl).convert("RGB")
            elif b.block_type == "mosaic":
                ms = b.mosaic_size if orig_scale else max(2, int(b.mosaic_size * self._get_off()[2]))
                ms = max(2, ms)
                rw, rh = region.size
                mosaic = region.resize((max(1, rw//ms), max(1, rh//ms)), Image.NEAREST).resize((rw, rh), Image.NEAREST)
                ml = mosaic.convert("RGBA"); ml.putalpha(a)
                region = Image.alpha_composite(region.convert("RGBA"), ml).convert("RGB")
            result.paste(region, (x1, y1))
        return result

    # ── Mouse Interaction ─────────────────────────────────────

    def _on_press(self, event):
        if not self.display_image: return
        ix, iy = self._c2i(event.x, event.y)
        ox, oy, sc = self._get_off()
        ctrl = bool(event.state & 0x4)
        mode = self.mode_var.get()
        if mode == "crop":
            if self.crop_rect:
                tmp = MaskBlock(self.crop_rect[0], self.crop_rect[1], self.crop_rect[2], self.crop_rect[3])
                h = tmp.get_handle_at_canvas(event.x, event.y, ox, oy, sc, 10)
                if h:
                    self.drag_mode, self.drag_handle = 'resize', h
                    self.drag_start = (ix, iy); self.drag_block_orig = tuple(self.crop_rect)
                    return
                if tmp.contains(ix, iy):
                    self.drag_mode, self.drag_start = 'move', (ix, iy)
                    self.drag_block_orig = tuple(self.crop_rect)
                    return
            self.drag_mode, self.drag_start = 'draw', (ix, iy)
            self.drag_block_orig = None; self._refresh(); return

        if 0 <= self.selected_index < len(self.blocks):
            h = self.blocks[self.selected_index].get_handle_at_canvas(event.x, event.y, ox, oy, sc, 10)
            if h:
                self.drag_mode, self.drag_handle = 'resize', h
                self.drag_start = (ix, iy); b = self.blocks[self.selected_index]
                self.drag_block_orig = (b.x, b.y, b.w, b.h); return
        ci = -1
        for i in range(len(self.blocks)-1, -1, -1):
            if self.blocks[i].contains(ix, iy): ci = i; break
        if ci >= 0:
            self.selected_index = ci; self._load_block_to_panel(self.blocks[ci])
            if ctrl:
                s = self.blocks[ci]; self.blocks.append(MaskBlock(s.x, s.y, s.w, s.h, s.block_type, s.color, s.opacity, s.mosaic_size))
                self.selected_index = len(self.blocks) - 1; self.ctrl_copy_index = self.selected_index
            self.drag_mode, self.drag_start = 'move', (ix, iy)
            b = self.blocks[self.selected_index]; self.drag_block_orig = (b.x, b.y, b.w, b.h); self._refresh()
        else:
            self.selected_index = -1; self.drag_mode, self.drag_start = 'draw', (ix, iy)
            self.drag_block_orig = None; self._refresh()

    def _on_drag(self, event):
        if not self.display_image or not self.drag_mode: return
        ix, iy = self._c2i(event.x, event.y); si, sy = self.drag_start; mode = self.mode_var.get()
        if self.drag_mode == 'draw':
            self.canvas.delete("dp"); cx1, cy1 = self._i2c(si, sy); cx2, cy2 = self._i2c(ix, iy)
            self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline=THEME["gold"], width=1, dash=(4, 4), tags="dp")
            if mode == "crop":
                self.canvas.create_rectangle(cx1, cy1, cx2, cy2, fill=THEME["patina"], stipple="gray25", outline="", tags="dp")
            else:
                self.canvas.create_rectangle(cx1, cy1, cx2, cy2, fill=self.color_var.get(), stipple="gray50", outline="", tags="dp")
        elif self.drag_mode == 'move':
            if mode == "crop" and self.crop_rect:
                ox, oy, _, _ = self.drag_block_orig
                nx, ny = ox + (ix - si), oy + (iy - sy)
                nx = max(0, min(nx, self.original_image.width - self.crop_rect[2]))
                ny = max(0, min(ny, self.original_image.height - self.crop_rect[3]))
                self.crop_rect = [nx, ny, self.crop_rect[2], self.crop_rect[3]]; self._refresh()
            elif mode == "mask" and 0 <= self.selected_index < len(self.blocks):
                b = self.blocks[self.selected_index]; ox, oy, _, _ = self.drag_block_orig
                b.x, b.y = ox + (ix - si), oy + (iy - sy); self._clip_block_to_image(b); self._refresh()
        elif self.drag_mode == 'resize':
            if mode == "crop" and self.crop_rect:
                ox, oy, ow, oh = self.drag_block_orig; dx, dy = ix - si, iy - sy
                nx, ny, nw, nh = ox, oy, ow, oh
                if 'w' in self.drag_handle: nx, nw = ox + dx, ow - dx
                if 'e' in self.drag_handle: nw = ow + dx
                if 'n' in self.drag_handle: ny, nh = oy + dy, oh - dy
                if 's' in self.drag_handle: nh = oh + dy
                self.crop_rect = list(self._clip_rect_to_image(nx, ny, nw, nh, self.original_image.width, self.original_image.height))
                self._refresh()
            elif mode == "mask" and 0 <= self.selected_index < len(self.blocks):
                b = self.blocks[self.selected_index]; ox, oy, ow, oh = self.drag_block_orig
                dx, dy = ix - si, iy - sy; self._do_resize(b, ox, oy, ow, oh, dx, dy)
                self._clip_block_to_image(b); self._refresh()

    def _do_resize(self, b, ox, oy, ow, oh, dx, dy):
        h = self.drag_handle; nx, ny, nw, nh = ox, oy, ow, oh
        if 'w' in h: nx, nw = ox+dx, ow-dx
        if 'e' in h: nw = ow+dx
        if 'n' in h: ny, nh = oy+dy, oh-dy
        if 's' in h: nh = oh+dy
        b.x, b.y, b.w, b.h = self._clip_rect_to_image(nx, ny, nw, nh, self.original_image.width, self.original_image.height)

    def _on_release(self, event):
        if not self.display_image or not self.drag_mode: return
        ix, iy = self._c2i(event.x, event.y); self.canvas.delete("dp"); mode = self.mode_var.get()
        if self.drag_mode == 'draw':
            si, sy = self.drag_start; x1, y1, x2, y2 = min(si, ix), min(sy, iy), max(si, ix), max(sy, iy)
            w, h = x2 - x1, y2 - y1
            if w >= self.MIN_SZ and h >= self.MIN_SZ:
                x1, y1, w, h = self._clip_rect_to_image(x1, y1, w, h, self.original_image.width, self.original_image.height)
                if mode == "crop":
                    self.crop_rect = [x1, y1, w, h]; self._save_current()
                else:
                    new_block = MaskBlock(x1, y1, w, h, self.type_var.get(), self.color_var.get(), int(self.opacity_var.get()), int(self.mosaic_var.get()))
                    self.blocks.append(new_block); self.selected_index = len(self.blocks) - 1; self._save_current()
            self._refresh()
        self.drag_mode = self.drag_handle = self.drag_block_orig = None; self.ctrl_copy_index = -1; self._refresh()

    def _on_motion(self, event):
        if not self.display_image or self.drag_mode: return
        ox, oy, sc = self._get_off(); mode = self.mode_var.get()
        if mode == "crop" and self.crop_rect:
            tmp = MaskBlock(self.crop_rect[0], self.crop_rect[1], self.crop_rect[2], self.crop_rect[3])
            h = tmp.get_handle_at_canvas(event.x, event.y, ox, oy, sc, 10)
            if h: self.canvas.config(cursor=tmp.get_cursor(h)); return
            if tmp.contains(*self._c2i(event.x, event.y)): self.canvas.config(cursor="fleur"); return
        if mode == "mask":
            if 0 <= self.selected_index < len(self.blocks):
                h = self.blocks[self.selected_index].get_handle_at_canvas(event.x, event.y, ox, oy, sc, 10)
                if h: self.canvas.config(cursor=self.blocks[self.selected_index].get_cursor(h)); return
            ix, iy = self._c2i(event.x, event.y)
            for i in range(len(self.blocks)-1, -1, -1):
                if self.blocks[i].contains(ix, iy): self.canvas.config(cursor="fleur"); return
        self.canvas.config(cursor="crosshair")


def main():
    root = tk.Tk()
    try: root.tk.call('tk', 'scaling', 1.25)
    except: pass
    MaskTool(root)
    root.mainloop()

if __name__ == "__main__":
    main()
