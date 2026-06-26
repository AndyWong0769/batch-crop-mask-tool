# Batch Crop & Mask Tool

A professional desktop tool for batch-processing images — apply color blocks, blur regions, mosaic effects, or crop areas across hundreds of photos in one go.

## Features

- **Mask Mode** — Color blocks, Gaussian blur, or pixel mosaic overlays
- **Crop Mode** — Precise crop regions with handle controls
- **Batch Import** — Load entire folders of images
- **Smart Sync** — Apply the same masks/crops across all images with proportional scaling
- **Presets** — Save and load mask/crop configurations as JSON
- **Drag & Drop** — Drop images or folders directly onto the window
- **Multi-Select** — Ctrl/Shift-click thumbnails for bulk operations

## Download

| Platform | Download |
|----------|----------|
| Windows  | [BatchCropMaskTool.exe](../../releases/latest/download/BatchCropMaskTool.exe) |
| macOS    | [BatchCropMaskTool.dmg](../../releases/latest/download/BatchCropMaskTool.dmg) |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| ↑ ↓ | Navigate images |
| Ctrl+D | Duplicate selected mask |
| Delete | Remove selected mask / crop |
| Ctrl+S | Save current image |
| Esc | Deselect |
| Ctrl+A | Select all images |

## Requirements (for running from source)

- Python 3.10+
- `pip install -r requirements.txt`

```
python batch-crop-mask-tool.py
```

## License

MIT
