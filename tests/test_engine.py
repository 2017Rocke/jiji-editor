import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import pymupdf as fitz
from PIL import Image

from jiji.engine import Workspace, UserError, convert_file, sample_pdf
from server import LocalServer


def file_item(data, name="input.pdf"):
    return {"name": name, "data": base64.b64encode(data).decode()}


def fixture():
    d = fitz.open()
    for label in ["FIRST original", "SECOND original", "THIRD original"]:
        p = d.new_page(width=400, height=600)
        p.insert_text((50, 70), label, fontsize=18)
        p.insert_text((50, 140), "Preserved text", fontsize=14)
    b = d.tobytes()
    d.close()
    return b


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.work = Workspace()
        self.work.load([file_item(fixture())])

    def tearDown(self):
        self.work.doc.close()

    def edit(self, action, **kwargs):
        return self.work.edit({"action": action, "revision": self.work.revision, **kwargs})

    def test_delete_reorder_extract_and_undo(self):
        self.edit("reorder", order=[2, 0, 1])
        self.assertIn("THIRD", self.work.doc[0].get_text())
        self.edit("delete", pages=[1])
        self.assertEqual(len(self.work.doc), 2)
        with fitz.open(stream=self.work.export([1]), filetype="pdf") as d:
            self.assertEqual(len(d), 1)
            self.assertIn("SECOND", d[0].get_text())
        self.edit("undo")
        self.assertEqual(len(self.work.doc), 3)
        self.edit("redo")
        self.assertEqual(len(self.work.doc), 2)

    def test_last_page_protected(self):
        before = self.work.bytes()
        with self.assertRaises(UserError):
            self.edit("delete", pages=[0, 1, 2])
        self.assertEqual(self.work.doc[0].get_text(), fitz.open(stream=before, filetype="pdf")[0].get_text())
        self.assertEqual(len(self.work.history), 0)

    def test_crop_uses_rotated_display_coordinates(self):
        self.edit("rotate", pages=[0])
        self.edit("crop", page=0, rect=[.1, .2, .9, .8])
        self.assertAlmostEqual(self.work.doc[0].rect.width, 480)
        self.assertAlmostEqual(self.work.doc[0].rect.height, 240)
        self.edit("crop", page=0, rect=[.1, .1, .9, .9])
        self.assertAlmostEqual(self.work.doc[0].rect.width, 384)
        self.assertAlmostEqual(self.work.doc[0].rect.height, 192)
        with fitz.open(stream=self.work.export(), filetype="pdf") as d:
            self.assertAlmostEqual(d[0].rect.width, 384)
        self.edit("undo")
        self.assertAlmostEqual(self.work.doc[0].rect.width, 480)

    def test_batch_crop_mixed_pages_and_single_undo(self):
        self.work.doc[1].set_mediabox(fitz.Rect(0, 0, 800, 500))
        self.edit("rotate", pages=[1])
        before = [(p.rect.width, p.rect.height) for p in self.work.doc]
        history = len(self.work.history)
        self.edit("crop", pages=[0, 1, 1], rect=[.1, .2, .9, .8])
        for i in [0, 1]:
            self.assertAlmostEqual(self.work.doc[i].rect.width, before[i][0] * .8, places=3)
            self.assertAlmostEqual(self.work.doc[i].rect.height, before[i][1] * .6, places=3)
        self.assertEqual((self.work.doc[2].rect.width, self.work.doc[2].rect.height), before[2])
        self.assertEqual(len(self.work.history), history + 1)
        cropped = [(p.rect.width, p.rect.height) for p in self.work.doc]
        self.edit("undo")
        self.assertEqual([(p.rect.width, p.rect.height) for p in self.work.doc], before)
        self.edit("redo")
        self.assertEqual([(p.rect.width, p.rect.height) for p in self.work.doc], cropped)
        self.edit("crop", pages=[0, 1], rect=[.1, .1, .9, .9])
        with fitz.open(stream=self.work.export(), filetype="pdf") as d:
            for i in [0, 1]:
                self.assertAlmostEqual(d[i].rect.width, cropped[i][0] * .8, places=3)
                self.assertAlmostEqual(d[i].rect.height, cropped[i][1] * .8, places=3)

    def test_batch_crop_failure_rolls_back_all_pages(self):
        self.work.doc[1].set_mediabox(fitz.Rect(0, 0, 10, 10))
        before = [tuple(p.cropbox) for p in self.work.doc]
        revision = self.work.revision
        for pages in [[], [0, 99], [0, 1]]:
            with self.assertRaises(UserError):
                self.edit("crop", pages=pages, rect=[.1, .1, .2, .2])
            self.assertEqual([tuple(p.cropbox) for p in self.work.doc], before)
            self.assertEqual(self.work.revision, revision)
            self.assertEqual(len(self.work.history), 0)

    def test_chinese_added_and_saved(self):
        self.edit("text", page=0, rect=[.1, .3, .9, .6], text="吉吉编辑软件 免费办公", size=22)
        with fitz.open(stream=self.work.export(), filetype="pdf") as d:
            self.assertIn("吉吉编辑软件", d[0].get_text().replace(" ", ""))
            self.assertIn("FIRST original", d[0].get_text())

    def test_added_text_is_upright_on_rotated_page(self):
        self.edit("rotate", pages=[0])
        self.edit("text", page=0, rect=[.1, .3, .9, .6], text="UPRIGHT", size=22)
        p = self.work.doc[0]
        lines = [line for b in p.get_text("dict")["blocks"] for line in b.get("lines", []) if "UPRIGHT" in "".join(s["text"] for s in line["spans"])]
        direction = fitz.Point(lines[0]["dir"]) * fitz.Matrix(p.rotation)
        self.assertAlmostEqual(direction.x, 1)
        self.assertAlmostEqual(direction.y, 0)

    def test_replace_removes_original_and_keeps_other_lines(self):
        block = self.work.blocks(0)[0]
        self.edit("replace", page=0, rect=block["rect"], original=block["text"], text="NEW", size=16)
        with fitz.open(stream=self.work.export(), filetype="pdf") as d:
            text = d[0].get_text()
            self.assertNotIn("FIRST original", text)
            self.assertIn("NEW", text)
            self.assertIn("Preserved text", text)

    def test_long_replacement_is_atomic(self):
        block = self.work.blocks(0)[0]
        with self.assertRaises(UserError):
            self.edit("replace", page=0, rect=block["rect"], original=block["text"], text="too much text " * 500, size=24)
        self.assertIn("FIRST original", self.work.doc[0].get_text())
        self.assertEqual(len(self.work.history), 0)

    def test_replace_rotated_and_cropped(self):
        self.edit("crop", page=0, rect=[.05, .05, .95, .95])
        self.edit("rotate", pages=[0])
        block = self.work.blocks(0)[0]
        self.edit("replace", page=0, rect=block["rect"], original=block["text"], text="REVISED", size=15)
        self.assertIn("REVISED", self.work.doc[0].get_text())
        self.assertNotIn("FIRST", self.work.doc[0].get_text())

    def test_stale_revision_and_bad_coordinates_rejected(self):
        with self.assertRaises(UserError):
            self.work.edit({"action": "rotate", "pages": [0], "revision": -1})
        with self.assertRaises(UserError):
            self.edit("crop", page=0, rect=[float('nan'), 0, 1, 1])
        self.assertEqual(self.work.doc[0].rotation, 0)

    def test_merge_failure_preserves_current_document(self):
        self.work.load([file_item(fixture())], append=True)
        self.assertEqual(len(self.work.doc), 6)
        with self.assertRaises(UserError):
            self.work.load([file_item(b"broken", "bad.pdf")], append=True)
        self.assertEqual(len(self.work.doc), 6)
        self.edit("undo")
        self.assertEqual(len(self.work.doc), 3)

    def test_image_and_text_conversion(self):
        image = Image.new("RGB", (240, 160), "#cadba9")
        stream = io.BytesIO()
        image.save(stream, "PNG")
        with convert_file("photo.png", stream.getvalue()) as d:
            self.assertEqual(len(d), 1)
            self.assertEqual(len(d[0].get_images()), 1)
        with convert_file("test.txt", ("吉吉转换测试\n" * 100).encode()) as d:
            self.assertGreater(len(d), 1)
            self.assertIn("吉吉", d[0].get_text())

    def test_annotations_drawing_and_image_export(self):
        self.edit("highlight", page=0, rect=[.1, .1, .6, .15])
        self.edit("draw", page=0, points=[[.2, .5], [.5, .6], [.8, .4]])
        image = Image.new("RGB", (100, 50), "red")
        stream = io.BytesIO()
        image.save(stream, "PNG")
        self.edit("image", page=0, rect=[.1, .7, .5, .9], file=file_item(stream.getvalue(), "stamp.png"))
        with fitz.open(stream=self.work.export(), filetype="pdf") as d:
            self.assertEqual(len(list(d[0].annots())), 1)
            self.assertTrue(d[0].get_drawings())
            self.assertTrue(d[0].get_images())

    def test_password_protected_input(self):
        with fitz.open(stream=fixture(), filetype="pdf") as d:
            encrypted = d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="open", permissions=fitz.PDF_PERM_MODIFY)
        with self.assertRaises(UserError):
            convert_file("locked.pdf", encrypted)
        with convert_file("locked.pdf", encrypted, "open") as unlocked:
            self.assertEqual(len(unlocked), 3)

    def test_sample_has_chinese_and_three_pages(self):
        with fitz.open(stream=sample_pdf(), filetype="pdf") as d:
            self.assertEqual(len(d), 3)
            self.assertIn("自由", d[0].get_text())


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, payload=None, token=True, origin=None, host=None):
        headers = {"X-Jiji-Token": self.server.token} if token else {}
        if origin:
            headers["Origin"] = origin
        if host:
            headers["Host"] = host
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.server.origin + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        return urllib.request.urlopen(req)

    def test_session_and_cross_origin_protection(self):
        for kwargs, code in [({"token": False}, 401), ({"origin": "https://evil.example"}, 403), ({"host": "evil.example"}, 403)]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request("/api/state", **kwargs)
            self.assertEqual(ctx.exception.code, code)

    def test_full_http_workflow(self):
        with self.request("/api/open", {"files": [file_item(fixture())]}) as r:
            state = json.load(r)
        with self.request("/api/edit", {"action": "delete", "pages": [1], "revision": state["revision"]}) as r:
            self.assertEqual(len(json.load(r)["pages"]), 2)
        with self.request("/api/render?page=0&scale=.5") as r:
            self.assertTrue(r.read().startswith(b"\x89PNG"))
        with self.request("/api/export?pages=0") as r:
            with fitz.open(stream=r.read(), filetype="pdf") as d:
                self.assertEqual(len(d), 1)
                self.assertIn("FIRST", d[0].get_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
