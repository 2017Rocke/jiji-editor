"""Document operations. Coordinates received from the UI are display-normalized.

All edits are transactional: a failed operation restores the last PDF byte for byte.
No input file is ever overwritten. PyMuPDF is used under the GNU AGPL v3.
"""
from __future__ import annotations

import base64
import html
import io
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

import pymupdf as fitz
from PIL import Image, ImageOps

MAX_FILE = 64 * 1024 * 1024
MAX_PAGES = 1000
HISTORY_BYTES = 192 * 1024 * 1024
OFFICE = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".heic"}


class UserError(Exception):
    pass


def office_binary():
    candidates = [os.environ.get("JIJI_SOFFICE"), shutil.which("soffice"),
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                  r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]
    return next((str(p) for p in candidates if p and Path(p).is_file()), None)


def office_environment(binary):
    env = os.environ.copy()
    if sys.platform == "darwin":
        # Some headless LibreOffice builds do not discover macOS fonts by default.
        # Configure only the child process; never modify system fonts or settings.
        env.setdefault("SAL_FONTPATH", "/System/Library/Fonts:/System/Library/Fonts/Supplemental:/Library/Fonts")
        config_candidates = [Path(binary).resolve().parent.parent / "Resources/fontconfig/fonts.conf"]
        if env.get("JIJI_FONTCONFIG_FILE"):
            config_candidates.insert(0, Path(env["JIJI_FONTCONFIG_FILE"]))
        config = next((p for p in config_candidates if p.is_file()), None)
        if config:
            env.setdefault("FONTCONFIG_FILE", str(config))
    return env


def unpack_file(item):
    name = Path(str(item.get("name", "文件.pdf")).replace("\\", "/")).name
    try:
        data = base64.b64decode(item["data"], validate=True)
    except (KeyError, ValueError, TypeError):
        raise UserError("文件数据不完整，请重新选择。")
    if not data or len(data) > MAX_FILE:
        raise UserError("单个文件需要在 64 MB 以内，且不能为空。")
    return name, data


def write_text(page, rect, text, size=18, color="#172820", rotate=0):
    if not str(text).strip():
        raise UserError("请先输入文字。")
    if len(text) > 10000:
        raise UserError("单次文字编辑最多 10000 字。")
    if not (isinstance(color, str) and len(color) == 7 and color[0] == "#"):
        raise UserError("颜色格式不正确。")
    try:
        int(color[1:], 16)
        size = float(size)
    except (ValueError, TypeError):
        raise UserError("文字样式不正确。")
    if not math.isfinite(size) or not 6 <= size <= 96:
        raise UserError("字号需要在 6 到 96 之间。")
    safe = html.escape(str(text)).replace("\n", "<br>")
    spare, scale = page.insert_htmlbox(
        rect, f'<div style="font-size:{size}pt;color:{color};line-height:1.12">{safe}</div>',
        css="*{font-family:sans-serif;margin:0;padding:0}",
        scale_low=0.65, rotate=rotate)
    if spare < 0:
        raise UserError("文字超出了选框，请缩短内容、减小字号，或画一个更大的文字框。")
    return scale


def convert_file(name, data, password=""):
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception:
            raise UserError("无法打开这个 PDF，文件可能已经损坏。")
        if doc.needs_pass and not doc.authenticate(password):
            doc.close()
            raise UserError("这个 PDF 需要正确的打开密码。请填写密码后重新导入。")
        if doc.is_encrypted or (doc.permissions >= 0 and not doc.permissions & fitz.PDF_PERM_MODIFY):
            doc.close()
            raise UserError("此 PDF 的权限不允许编辑，请使用有编辑权限的版本。")
        if not 0 < len(doc) <= MAX_PAGES:
            doc.close()
            raise UserError("目前支持 1 到 1000 页的 PDF。")
        return doc
    if suffix in IMAGES:
        try:
            with Image.open(io.BytesIO(data)) as raw:
                if raw.width * raw.height > 60_000_000:
                    raise UserError("图片像素过大，请先缩小到 6000 万像素以内。")
                img = ImageOps.exif_transpose(raw).convert("RGB")
                stream = io.BytesIO()
                img.save(stream, "JPEG", quality=95)
                doc = fitz.open()
                w, h = img.size
                page = doc.new_page(width=595 if w <= h else 842, height=842 if w <= h else 595)
                page.insert_image(page.rect + (24, 24, -24, -24), stream=stream.getvalue(), keep_proportion=True)
                return doc
        except UserError:
            raise
        except Exception:
            raise UserError("无法读取图片。请尝试 PNG 或 JPG 格式。")
    if suffix in {".txt", ".md"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("gb18030")
            except UnicodeDecodeError:
                raise UserError("文本编码无法识别，请另存为 UTF-8 再导入。")
        if not text.strip():
            raise UserError("文本文件没有内容。")
        # Story paginates text; it does not pretend that Markdown is a Word renderer.
        content = '<div style="font-size:12pt;line-height:1.7;white-space:pre-wrap">' + html.escape(text).replace("\n", "<br>") + '</div>'
        story = fitz.Story(html=content)
        out = io.BytesIO()
        writer = fitz.DocumentWriter(out)
        more = True
        count = 0
        while more:
            count += 1
            if count > MAX_PAGES:
                writer.close()
                raise UserError("文本分页超过 1000 页，请拆分后导入。")
            device = writer.begin_page(fitz.Rect(0, 0, 595, 842))
            more, _ = story.place(fitz.Rect(48, 48, 547, 794))
            story.draw(device)
            writer.end_page()
        writer.close()
        return fitz.open(stream=out.getvalue(), filetype="pdf")
    if suffix in OFFICE:
        binary = office_binary()
        if not binary:
            raise UserError("Office 转 PDF 需要免费的 LibreOffice。安装后重新启动吉吉即可；PDF 和图片功能无需安装。")
        with tempfile.TemporaryDirectory(prefix="jiji-convert-") as temp:
            root = Path(temp)
            source = root / ("input" + suffix)
            source.write_bytes(data)
            dest = root / "converted"
            dest.mkdir()
            profile = (root / "profile").as_uri()
            try:
                result = subprocess.run([binary, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", str(dest), str(source)],
                                        capture_output=True, timeout=120, env=office_environment(binary))
            except subprocess.TimeoutExpired:
                raise UserError("转换超过 2 分钟，请尝试拆分文档后再试。")
            except OSError:
                raise UserError("LibreOffice 无法启动，请检查安装后重试。")
            target = dest / "input.pdf"
            if result.returncode or not target.exists():
                raise UserError("Office 转换未成功，请确认文件未损坏、未加密，并已安装所需字体。")
            return convert_file("converted.pdf", target.read_bytes())
    raise UserError("暂不支持此格式。请选择 PDF、图片、TXT、Word、Excel 或 PowerPoint。")


class Workspace:
    def __init__(self):
        self.lock = threading.RLock()
        self.doc = None
        self.name = "未命名.pdf"
        self.history = []
        self.future = []
        self.revision = 0
        self.dirty = False

    def require(self):
        if self.doc is None:
            raise UserError("请先打开一个文件。")

    def bytes(self):
        self.require()
        return self.doc.tobytes(garbage=4, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)

    def state(self):
        return {"name": self.name, "revision": self.revision, "dirty": self.dirty,
                "undo": bool(self.history), "redo": bool(self.future), "office": bool(office_binary()),
                "pages": [{"width": p.rect.width, "height": p.rect.height, "rotation": p.rotation} for p in self.doc] if self.doc else []}

    def remember(self, snapshot):
        self.history.append(snapshot)
        while len(self.history) > 20 or (len(self.history) > 1 and sum(len(x) for x in self.history) > HISTORY_BYTES):
            self.history.pop(0)
        self.future.clear()

    def load(self, files, password="", append=False):
        if not files or len(files) > 40:
            raise UserError("一次请选择 1 到 40 个文件。")
        if append:
            self.require()
        assembled = fitz.open()
        try:
            if append:
                assembled.insert_pdf(self.doc, widgets=True)
            for item in files:
                name, data = unpack_file(item)
                with convert_file(name, data, password) as incoming:
                    if len(assembled) + len(incoming) > MAX_PAGES:
                        raise UserError("合并后不能超过 1000 页。")
                    assembled.insert_pdf(incoming, widgets=True)
            if append:
                self.remember(self.bytes())
            else:
                self.history.clear()
                self.future.clear()
                first = unpack_file(files[0])[0]
                self.name = Path(first).stem + ("_合并" if len(files) > 1 else "") + ".pdf"
            if self.doc:
                self.doc.close()
            self.doc = assembled
            self.dirty = append or len(files) > 1 or Path(files[0]["name"]).suffix.lower() != ".pdf"
            self.revision += 1
            return self.state()
        except Exception:
            assembled.close()
            raise

    def page(self, index):
        self.require()
        if not isinstance(index, int) or not 0 <= index < len(self.doc):
            raise UserError("页码不存在。")
        return self.doc[index]

    def rect(self, page, coords):
        try:
            x0, y0, x1, y1 = [float(x) for x in coords]
        except (ValueError, TypeError):
            raise UserError("选框不正确，请重新框选。")
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in [x0, y0, x1, y1]) or x1 <= x0 or y1 <= y0:
            raise UserError("请在页面内画一个有效选框。")
        r = fitz.Rect(x0 * page.rect.width, y0 * page.rect.height, x1 * page.rect.width, y1 * page.rect.height)
        return r * page.derotation_matrix

    def render(self, index, scale):
        page = self.page(index)
        scale = float(scale)
        if not math.isfinite(scale) or not 0.1 <= scale <= 3:
            raise UserError("缩放比例不正确。")
        scale = min(scale, 2400 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")

    def blocks(self, index):
        page = self.page(index)
        result = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s["text"] for s in spans)
                if not text.strip() or tuple(line.get("dir", (1, 0))) != (1.0, 0.0):
                    continue
                r = (fitz.Rect(line["bbox"]) * page.rotation_matrix) & page.rect
                if r.is_empty:
                    continue
                result.append({"text": text, "size": round(spans[0]["size"], 1),
                               "rect": [r.x0 / page.rect.width, r.y0 / page.rect.height, r.x1 / page.rect.width, r.y1 / page.rect.height]})
        return result

    def edit(self, payload):
        self.require()
        if payload.get("revision") != self.revision:
            raise UserError("页面已变化，请刷新后重试。")
        action = payload.get("action")
        if action in {"undo", "redo"}:
            source, dest = (self.history, self.future) if action == "undo" else (self.future, self.history)
            if not source:
                raise UserError("没有可以撤销或重做的操作。")
            dest.append(self.bytes())
            restored = fitz.open(stream=source.pop(), filetype="pdf")
            self.doc.close()
            self.doc = restored
            self.revision += 1
            self.dirty = True
            return self.state()
        before = self.bytes()
        try:
            self._edit(action, payload)
        except Exception:
            self.doc.close()
            self.doc = fitz.open(stream=before, filetype="pdf")
            raise
        self.remember(before)
        self.revision += 1
        self.dirty = True
        return self.state()

    def indices(self, values):
        if not isinstance(values, list) or not values:
            raise UserError("请先选择页面。")
        if any(not isinstance(i, int) or i < 0 or i >= len(self.doc) for i in values):
            raise UserError("选择的页码不正确。")
        return sorted(set(values))

    def _edit(self, action, data):
        if action == "rotate":
            for i in self.indices(data.get("pages")):
                p = self.doc[i]
                p.set_rotation((p.rotation + 90) % 360)
        elif action == "delete":
            indices = self.indices(data.get("pages"))
            if len(indices) == len(self.doc):
                raise UserError("请至少保留一页。")
            self.doc.delete_pages(indices)
        elif action == "reorder":
            order = data.get("order", [])
            if sorted(order) != list(range(len(self.doc))):
                raise UserError("页面顺序不完整。")
            self.doc.select(order)
        elif action == "blank":
            if len(self.doc) >= MAX_PAGES:
                raise UserError("文档最多支持 1000 页。")
            index = data.get("page", len(self.doc) - 1)
            self.page(index)
            self.doc.new_page(pno=index + 1, width=595, height=842)
        elif action in {"crop", "text", "replace", "highlight", "draw", "image"}:
            p = self.page(data.get("page"))
            if action == "draw":
                raw = data.get("points", [])
                if not 2 <= len(raw) <= 10000:
                    raise UserError("请先在页面上画线。")
                points = []
                for x, y in raw:
                    if not all(math.isfinite(v) and 0 <= v <= 1 for v in [x, y]):
                        raise UserError("笔迹超出页面。")
                    points.append(fitz.Point(x * p.rect.width, y * p.rect.height) * p.derotation_matrix)
                p.draw_polyline(points, color=self.color(data.get("color", "#176443")), width=2, overlay=True)
                return
            r = self.rect(p, data.get("rect"))
            if min(r.width, r.height) < 3:
                raise UserError("选框太小，请重新框选。")
            if action == "crop":
                p.set_cropbox((r + (p.cropbox_position.x, p.cropbox_position.y, p.cropbox_position.x, p.cropbox_position.y)) & p.mediabox)
            elif action == "highlight":
                annot = p.add_rect_annot(r)
                annot.set_colors(stroke=None, fill=self.color(data.get("color", "#f4ca45")))
                annot.set_border(width=0)
                annot.set_opacity(0.3)
                annot.update()
            elif action == "image":
                _, image_data = unpack_file(data.get("file", {}))
                try:
                    p.insert_image(r, stream=image_data, keep_proportion=True, rotate=p.rotation)
                except Exception:
                    raise UserError("无法插入这张图片，请选择 PNG 或 JPG。")
            else:
                if action == "replace":
                    # Validate the target against the current text lines: never accept an arbitrary deletion box.
                    candidates = self.blocks(data["page"])
                    match = next((b for b in candidates if b["text"] == data.get("original") and all(abs(a - b_) < 0.0001 for a, b_ in zip(b["rect"], data["rect"]))), None)
                    if not match:
                        raise UserError("原文字已变化，请重新点击要修改的文字。")
                    p.add_redact_annot(r, fill=False)
                    p.apply_redactions(images=0, graphics=0, text=0)
                write_text(p, r, data.get("text", ""), data.get("size", 18), data.get("color", "#172820"), rotate=p.rotation if action == "text" else 0)
        else:
            raise UserError("不支持这个操作。")

    @staticmethod
    def color(value):
        try:
            if len(value) != 7 or value[0] != "#":
                raise ValueError()
            return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
        except (ValueError, TypeError):
            raise UserError("颜色格式不正确。")

    def export(self, pages=None):
        self.require()
        if pages is None:
            return self.bytes()
        selected = self.indices(pages)
        with fitz.open() as result:
            for i in selected:
                result.insert_pdf(self.doc, from_page=i, to_page=i, widgets=True)
            return result.tobytes(garbage=4, deflate=True)


def sample_pdf():
    doc = fitz.open()
    for index, (title, subtitle) in enumerate([
        ("让文档，自由一点。", "欢迎使用吉吉编辑软件"),
        ("每一页，都由你做主。", "裁剪 · 旋转 · 提取 · 合并"),
        ("好工具，不该有门槛。", "免费使用 / 本地处理 / 没有水印")]):
        p = doc.new_page(width=595, height=842)
        p.draw_rect(p.rect, fill=(0.98, 0.976, 0.95), color=None)
        p.draw_rect(fitz.Rect(40, 48, 93, 54), fill=(0.22, 0.40, 0.29), color=None)
        write_text(p, fitz.Rect(40, 75, 550, 110), "JIJI  /  A LITTLE MORE FREEDOM", 11, "#56705e")
        write_text(p, fitz.Rect(40, 160, 555, 250), title, 34)
        write_text(p, fitz.Rect(42, 248, 550, 292), subtitle, 16, "#5b6b60")
        p.draw_rect(fitz.Rect(40, 348, 555, 615), fill=(0.87, 0.91, 0.79), color=None)
        write_text(p, fitz.Rect(68, 380, 525, 440), f"0{index + 1}  /  你的第一份自由文档", 21)
        write_text(p, fitz.Rect(68, 452, 520, 576), "试着添加一段文字，圈出重要内容，\n或者剪掉多余的边距。\n完成后，导出一份属于你的 PDF。", 16)
        write_text(p, fitz.Rect(40, 742, 530, 785), f"吉吉编辑软件    ·    示例文档                                      {index + 1} / 3", 10, "#56705e")
    result = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return result
