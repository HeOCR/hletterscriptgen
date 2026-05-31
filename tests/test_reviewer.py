"""Tests for hletterscriptgen.reviewer — review app HTML builder and HTTP server."""

from __future__ import annotations

import http.client
import json
import struct
import threading
import zlib
from http.server import HTTPServer
from pathlib import Path
from typing import Any

import pytest

from hletterscriptgen.reviewer import (
    _build_html,
    _build_sections,
    _build_sidebar,
    _build_variant_card,
    _ink_quality,
    _letter_anchor,
    _ReviewHandler,
    serve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_png(width: int = 4, height: int = 4) -> bytes:
    """Return a tiny valid grayscale PNG for testing."""
    raw = b"".join(b"\x00" + bytes([128] * width) for _ in range(height))
    compressed = zlib.compress(raw, 1)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFF_FFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr_data = struct.pack(">II", width, height) + bytes([8, 0, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _make_letter_set(
    writer_id: str = "w1",
    letters: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if letters is None:
        letters = {
            "א": [
                {
                    "variant_id": "alef-0001",
                    "asset_path": "letters/alef/alef-0001.png",
                    "checksum_sha256": "a" * 64,
                    "image": {"width_px": 32, "height_px": 40, "format": "png"},
                    "quality": {"ink_ratio": 0.25},
                    "source": {
                        "scan_entry_id": "scan-001",
                        "license": "PDM-1.0",
                        "bbox_in_source": {"x": 10, "y": 20, "width": 32, "height": 40},
                    },
                }
            ]
        }
    return {
        "schema_version": "letter_set.v1",
        "writer_id": writer_id,
        "writer_label": "Test Writer",
        "generated_at": "2026-05-25T00:00:00Z",
        "letters": letters,
    }


def _start_one_shot_server(
    html: str,
    feedback_path: Path,
    images: dict[str, Path] | None = None,
) -> tuple[int, HTTPServer]:
    """Start an HTTPServer bound to a free port; return (port, server).

    Creates a fresh _ReviewHandler subclass per call so tests are isolated —
    no shared class-level state between invocations.
    """
    class _TestHandler(_ReviewHandler):
        pass

    _TestHandler._html = html
    _TestHandler._feedback_path = feedback_path
    _TestHandler._images = images if images is not None else {}

    srv = HTTPServer(("127.0.0.1", 0), _TestHandler)
    return srv.server_address[1], srv


# ---------------------------------------------------------------------------
# _letter_anchor
# ---------------------------------------------------------------------------


def test_letter_anchor_alef() -> None:
    assert _letter_anchor("א") == "u05d0"


def test_letter_anchor_resh() -> None:
    assert _letter_anchor("ר") == "u05e8"


def test_letter_anchor_tav() -> None:
    assert _letter_anchor("ת") == "u05ea"


# ---------------------------------------------------------------------------
# _ink_quality
# ---------------------------------------------------------------------------


def test_ink_quality_very_sparse() -> None:
    label, cls = _ink_quality(0.03)
    assert label == "Very sparse"
    assert cls == "quality-low"


def test_ink_quality_sparse() -> None:
    label, cls = _ink_quality(0.10)
    assert label == "Sparse"
    assert cls == "quality-warn"


def test_ink_quality_normal() -> None:
    label, cls = _ink_quality(0.30)
    assert label == "Normal"
    assert cls == "quality-ok"


def test_ink_quality_normal_upper_boundary() -> None:
    label, cls = _ink_quality(0.60)
    assert label == "Normal"
    assert cls == "quality-ok"


def test_ink_quality_dense() -> None:
    label, cls = _ink_quality(0.80)
    assert label == "Dense"
    assert cls == "quality-warn"


# ---------------------------------------------------------------------------
# _build_variant_card
# ---------------------------------------------------------------------------


def test_variant_card_contains_variant_id(tmp_path: Path) -> None:
    variant: dict[str, Any] = {
        "variant_id": "alef-0042",
        "asset_path": "letters/alef/alef-0042.png",
        "checksum_sha256": "a" * 64,
        "image": {"width_px": 30, "height_px": 40, "format": "png"},
        "quality": {"ink_ratio": 0.28},
        "source": {
            "scan_entry_id": "s001",
            "license": "PDM-1.0",
            "bbox_in_source": {"x": 5, "y": 10, "width": 30, "height": 40},
        },
    }
    images: dict[str, Path] = {}
    html = _build_variant_card(variant, "א", tmp_path, images)
    assert "alef-0042" in html
    assert 'id="card-alef-0042"' in html


def test_variant_card_missing_image_shows_fallback(tmp_path: Path) -> None:
    variant: dict[str, Any] = {
        "variant_id": "alef-0001",
        "asset_path": "letters/alef/missing.png",
        "checksum_sha256": "a" * 64,
        "image": {"width_px": 30, "height_px": 40, "format": "png"},
        "quality": {"ink_ratio": 0.25},
        "source": {
            "scan_entry_id": "s001",
            "license": "PDM-1.0",
            "bbox_in_source": {"x": 5, "y": 10, "width": 30, "height": 40},
        },
    }
    images: dict[str, Path] = {}
    html = _build_variant_card(variant, "א", tmp_path, images)
    assert "glyph-missing" in html
    assert "<img" not in html
    assert "alef-0001" not in images


def test_variant_card_with_image_shows_img_endpoint(tmp_path: Path) -> None:
    png_path = tmp_path / "letters" / "alef"
    png_path.mkdir(parents=True)
    (png_path / "alef-0001.png").write_bytes(_minimal_png())

    variant: dict[str, Any] = {
        "variant_id": "alef-0001",
        "asset_path": "letters/alef/alef-0001.png",
        "checksum_sha256": "a" * 64,
        "image": {"width_px": 4, "height_px": 4, "format": "png"},
        "quality": {"ink_ratio": 0.28},
        "source": {
            "scan_entry_id": "s001",
            "license": "PDM-1.0",
            "bbox_in_source": {"x": 5, "y": 10, "width": 4, "height": 4},
        },
    }
    images: dict[str, Path] = {}
    html = _build_variant_card(variant, "א", tmp_path, images)
    assert '<img' in html
    assert 'src="/image/alef-0001"' in html
    assert "data:image" not in html
    assert "alef-0001" in images


def test_variant_card_quality_badge_class(tmp_path: Path) -> None:
    """Dense ink_ratio should produce the 'quality-warn' class."""
    variant: dict[str, Any] = {
        "variant_id": "v1",
        "asset_path": "x.png",
        "checksum_sha256": "a" * 64,
        "image": {"width_px": 10, "height_px": 10, "format": "png"},
        "quality": {"ink_ratio": 0.90},
        "source": {"scan_entry_id": "s", "license": "PDM-1.0",
                   "bbox_in_source": {"x": 0, "y": 0, "width": 10, "height": 10}},
    }
    images: dict[str, Path] = {}
    html = _build_variant_card(variant, "ב", tmp_path, images)
    assert "quality-warn" in html


def test_variant_card_uses_data_attributes_not_inline_handlers(tmp_path: Path) -> None:
    variant: dict[str, Any] = {
        "variant_id": "alef-0001",
        "asset_path": "x.png",
        "checksum_sha256": "a" * 64,
        "image": {"width_px": 10, "height_px": 10, "format": "png"},
        "quality": {"ink_ratio": 0.25},
        "source": {"scan_entry_id": "s", "license": "PDM-1.0",
                   "bbox_in_source": {"x": 0, "y": 0, "width": 10, "height": 10}},
    }
    images: dict[str, Path] = {}
    html = _build_variant_card(variant, "א", tmp_path, images)
    assert 'onclick=' not in html
    assert 'oninput=' not in html
    assert 'data-vid=' in html
    assert 'data-verdict=' in html


def test_variant_card_malformed_variant_raises(tmp_path: Path) -> None:
    bad: dict[str, Any] = {
        "variant_id": "v1",
        "asset_path": "x.png",
        # missing "image" and "quality"
    }
    with pytest.raises(ValueError, match="Malformed variant"):
        _build_variant_card(bad, "א", tmp_path, {})


# ---------------------------------------------------------------------------
# _build_sidebar
# ---------------------------------------------------------------------------


def test_build_sidebar_contains_all_letters(tmp_path: Path) -> None:
    ls = _make_letter_set(
        letters={
            "א": [{"variant_id": "a1", "asset_path": "x.png",
                   "checksum_sha256": "a" * 64,
                   "image": {"width_px": 1, "height_px": 1, "format": "png"},
                   "quality": {"ink_ratio": 0.2},
                   "source": {"scan_entry_id": "s", "license": "PDM-1.0",
                               "bbox_in_source": {"x": 0, "y": 0, "width": 1, "height": 1}}}],
            "ב": [{"variant_id": "b1", "asset_path": "y.png",
                   "checksum_sha256": "b" * 64,
                   "image": {"width_px": 1, "height_px": 1, "format": "png"},
                   "quality": {"ink_ratio": 0.3},
                   "source": {"scan_entry_id": "s", "license": "PDM-1.0",
                               "bbox_in_source": {"x": 0, "y": 0, "width": 1, "height": 1}}}],
        }
    )
    html = _build_sidebar(ls)
    assert "u05d0" in html  # Alef anchor
    assert "u05d1" in html  # Bet anchor
    assert "letter-nav-item" in html


def test_build_sidebar_empty_letters() -> None:
    html = _build_sidebar({"letters": {}})
    assert html == ""


# ---------------------------------------------------------------------------
# _build_sections
# ---------------------------------------------------------------------------


def test_build_sections_returns_all_ids(tmp_path: Path) -> None:
    ls = _make_letter_set()
    _, ids, _ = _build_sections(ls, tmp_path)
    assert ids == ["alef-0001"]


def test_build_sections_html_contains_section_id(tmp_path: Path) -> None:
    ls = _make_letter_set()
    html, _, _ = _build_sections(ls, tmp_path)
    assert 'id="letter-u05d0"' in html


def test_build_sections_images_map_populated_when_file_exists(tmp_path: Path) -> None:
    png_dir = tmp_path / "letters" / "alef"
    png_dir.mkdir(parents=True)
    (png_dir / "alef-0001.png").write_bytes(_minimal_png())
    ls = _make_letter_set()
    _, _, images = _build_sections(ls, tmp_path)
    assert "alef-0001" in images


def test_build_sections_images_map_empty_when_file_missing(tmp_path: Path) -> None:
    ls = _make_letter_set()  # asset file does not exist in tmp_path
    _, _, images = _build_sections(ls, tmp_path)
    assert images == {}


# ---------------------------------------------------------------------------
# _build_html
# ---------------------------------------------------------------------------


def test_build_html_contains_writer_id(tmp_path: Path) -> None:
    ls = _make_letter_set(writer_id="my-writer-007")
    html, _ = _build_html(ls, tmp_path)
    assert "my-writer-007" in html


def test_build_html_contains_progress_elements(tmp_path: Path) -> None:
    ls = _make_letter_set()
    html, _ = _build_html(ls, tmp_path)
    assert "progress-fill" in html
    assert "progress-label" in html


def test_build_html_embeds_all_ids_in_script(tmp_path: Path) -> None:
    ls = _make_letter_set()
    html, _ = _build_html(ls, tmp_path)
    assert '"alef-0001"' in html  # variant_id appears in the JS ALL_IDS array


def test_build_html_no_writer_label_skips_label_div(tmp_path: Path) -> None:
    ls = _make_letter_set()
    del ls["writer_label"]
    html, _ = _build_html(ls, tmp_path)
    assert "Test Writer" not in html


def test_build_html_is_valid_html_scaffold(tmp_path: Path) -> None:
    ls = _make_letter_set()
    html, _ = _build_html(ls, tmp_path)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "<style>" in html
    assert "<script>" in html


def test_build_html_returns_images_map(tmp_path: Path) -> None:
    png_dir = tmp_path / "letters" / "alef"
    png_dir.mkdir(parents=True)
    (png_dir / "alef-0001.png").write_bytes(_minimal_png())
    ls = _make_letter_set()
    _, images = _build_html(ls, tmp_path)
    assert "alef-0001" in images


# ---------------------------------------------------------------------------
# _ReviewHandler — HTTP layer
# ---------------------------------------------------------------------------


def test_handler_get_root_returns_html(tmp_path: Path) -> None:
    port, srv = _start_one_shot_server("<html>hello</html>", tmp_path / "fb.json")

    t = threading.Thread(target=srv.handle_request)
    t.start()

    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    t.join()

    assert resp.status == 200
    assert b"hello" in body
    assert resp.getheader("Content-Type") == "text/html; charset=utf-8"


def test_handler_get_feedback_empty_when_no_file(tmp_path: Path) -> None:
    fb_path = tmp_path / "fb.json"  # does not exist
    port, srv = _start_one_shot_server("", fb_path)
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/feedback")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    t.join()
    assert resp.status == 200
    assert data == {}


def test_handler_get_feedback_returns_saved_data(tmp_path: Path) -> None:
    fb_path = tmp_path / "fb.json"
    fb_path.write_text(json.dumps({"v1": {"verdict": "accept"}}), encoding="utf-8")
    port, srv = _start_one_shot_server("", fb_path)
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/feedback")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    t.join()
    assert data == {"v1": {"verdict": "accept"}}


def test_handler_post_feedback_saves_json(tmp_path: Path) -> None:
    fb_path = tmp_path / "fb.json"
    port, srv = _start_one_shot_server("", fb_path)
    payload = json.dumps({"v2": {"verdict": "reject", "comment": "bad crop"}}).encode()
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/feedback", body=payload,
                 headers={"Content-Type": "application/json",
                          "Content-Length": str(len(payload))})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    t.join()
    assert resp.status == 204
    saved = json.loads(fb_path.read_text(encoding="utf-8"))
    assert saved["v2"]["verdict"] == "reject"


def test_handler_post_feedback_write_is_atomic(tmp_path: Path) -> None:
    """POST should not leave a .tmp file behind after a successful save."""
    fb_path = tmp_path / "fb.json"
    port, srv = _start_one_shot_server("", fb_path)
    payload = json.dumps({"v1": {"verdict": "accept"}}).encode()
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/feedback", body=payload,
                 headers={"Content-Type": "application/json",
                          "Content-Length": str(len(payload))})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    t.join()
    assert resp.status == 204
    assert fb_path.exists()
    assert not fb_path.with_suffix(".tmp").exists()


def test_handler_post_feedback_invalid_json_returns_400(tmp_path: Path) -> None:
    fb_path = tmp_path / "fb.json"
    port, srv = _start_one_shot_server("", fb_path)
    bad = b"NOT-JSON"
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/feedback", body=bad,
                 headers={"Content-Type": "application/json",
                          "Content-Length": str(len(bad))})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    t.join()
    assert resp.status == 400


def test_handler_get_unknown_path_returns_404(tmp_path: Path) -> None:
    port, srv = _start_one_shot_server("", tmp_path / "fb.json")
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/unknown/path")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    t.join()
    assert resp.status == 404


def test_handler_post_unknown_path_returns_404(tmp_path: Path) -> None:
    port, srv = _start_one_shot_server("", tmp_path / "fb.json")
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/unknown", body=b"{}",
                 headers={"Content-Type": "application/json", "Content-Length": "2"})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    t.join()
    assert resp.status == 404


def test_handler_feedback_file_with_invalid_json_returns_empty(tmp_path: Path) -> None:
    fb_path = tmp_path / "fb.json"
    fb_path.write_text("{{invalid json}}", encoding="utf-8")
    port, srv = _start_one_shot_server("", fb_path)
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/feedback")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    t.join()
    assert data == {}


def test_handler_get_image_returns_png(tmp_path: Path) -> None:
    png_bytes = _minimal_png()
    img_path = tmp_path / "alef-0001.png"
    img_path.write_bytes(png_bytes)

    port, srv = _start_one_shot_server("", tmp_path / "fb.json",
                                       images={"alef-0001": img_path})
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/image/alef-0001")
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    t.join()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "image/png"
    assert body == png_bytes


def test_handler_get_image_unknown_vid_returns_404(tmp_path: Path) -> None:
    port, srv = _start_one_shot_server("", tmp_path / "fb.json", images={})
    t = threading.Thread(target=srv.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/image/no-such-variant")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    t.join()
    assert resp.status == 404


# ---------------------------------------------------------------------------
# serve() error paths
# ---------------------------------------------------------------------------


def test_serve_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        serve(tmp_path / "nonexistent.json", port=0)


def test_serve_raises_for_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "letter_set.json"
    bad.write_text("{bad json}", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        serve(bad, port=0)


# ---------------------------------------------------------------------------
# CLI integration — review subcommand
# ---------------------------------------------------------------------------


def test_cli_review_missing_file(tmp_path: Path) -> None:
    from hletterscriptgen.cli import main

    rc = main(["review", str(tmp_path / "nope.json")])
    assert rc != 0


def test_cli_review_invalid_json(tmp_path: Path) -> None:
    from hletterscriptgen.cli import main

    bad = tmp_path / "letter_set.json"
    bad.write_text("{bad json}", encoding="utf-8")
    rc = main(["review", str(bad)])
    assert rc != 0
