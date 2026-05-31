"""Local browser-based review server for a letter_set.v1 release candidate.

Serves a single-page review UI that lets you scroll through every variant in a
``letter_set.json``, mark each one as *accepted*, *rejected*, or *changes
requested*, add free-text comments, and persist the feedback to a JSON file.

Usage via the CLI::

    hletterscriptgen review path/to/letter_set.json [--port 8765]

Usage as a library::

    from hletterscriptgen.reviewer import serve
    from pathlib import Path
    serve(Path("out/my_writer/letter_set.json"), port=8765)

The feedback file (``.review_feedback.json`` next to the letter-set by
default, or the path passed as ``--feedback``) is auto-created on the first
``POST /feedback`` and read back on page load so a review session can be
resumed.
"""

from __future__ import annotations

import http.server
import json
import webbrowser
from html import escape as _esc
from pathlib import Path
from typing import Any

_FEEDBACK_FILENAME = ".review_feedback.json"

_MIME_MAP: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "tiff": "image/tiff",
}

_LETTER_NAMES: dict[str, str] = {
    "א": "Alef",
    "ב": "Bet",
    "ג": "Gimel",
    "ד": "Dalet",
    "ה": "He",
    "ו": "Vav",
    "ז": "Zayin",
    "ח": "Het",
    "ט": "Tet",
    "י": "Yod",
    "כ": "Kaf",
    "ך": "Kaf (final)",
    "ל": "Lamed",
    "מ": "Mem",
    "ם": "Mem (final)",
    "נ": "Nun",
    "ן": "Nun (final)",
    "ס": "Samekh",
    "ע": "Ayin",
    "פ": "Pe",
    "ף": "Pe (final)",
    "צ": "Tsadi",
    "ץ": "Tsadi (final)",
    "ק": "Qof",
    "ר": "Resh",
    "ש": "Shin",
    "ת": "Tav",
}


# ---------------------------------------------------------------------------
# HTML template pieces  (pure strings — no f-string so curly-braces are safe)
# ---------------------------------------------------------------------------

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;font-size:14px;
background:#f0f2f5;color:#1a1a2e;display:flex;flex-direction:column;min-height:100vh}
code{font-size:.82em;background:#f0f0f0;padding:1px 4px;border-radius:3px}

/* top header */
.top-header{background:#1a1a2e;color:#fff;padding:.75rem 1.5rem;
  display:flex;align-items:center;gap:1rem;flex-wrap:wrap;
  position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.35)}
.top-header h1{font-size:1rem;font-weight:600;white-space:nowrap}
.subtitle{font-size:.78rem;color:#aaa;margin-top:1px}
.progress-wrap{flex:1;min-width:180px}
.progress-label{font-size:.73rem;color:#bbb;margin-bottom:3px}
.progress-bar{height:6px;background:#333;border-radius:3px;overflow:hidden}
.progress-fill{height:100%;background:#4caf50;border-radius:3px;transition:width .3s}
.header-actions{display:flex;gap:.5rem}
.hdr-btn{padding:.3rem .75rem;font-size:.78rem;border-radius:4px;
  cursor:pointer;border:none;font-weight:500}
.btn-export{background:#4a90d9;color:#fff}
.btn-export:hover{background:#357ab8}
.btn-accept-all{background:#2e7d32;color:#fff}
.btn-accept-all:hover{background:#1b5e20}

/* layout */
.main-layout{display:flex;flex:1}

/* sidebar */
.sidebar{width:195px;min-width:195px;background:#fff;border-right:1px solid #dde;
  position:sticky;top:53px;height:calc(100vh - 53px);overflow-y:auto;
  padding:.75rem .4rem}
.sidebar-title{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;
  color:#aaa;padding:.25rem .6rem .5rem}
.letter-nav-item{display:flex;align-items:center;gap:.4rem;padding:.38rem .6rem;
  border-radius:5px;text-decoration:none;color:inherit;margin-bottom:1px;
  transition:background .12s;cursor:pointer}
.letter-nav-item:hover{background:#f0f2f8}
.letter-nav-item.active{background:#e8edf8;color:#1a3a7a;font-weight:600}
.lni-char{font-size:1.15rem;min-width:22px;text-align:center;direction:rtl}
.lni-name{flex:1;font-size:.78rem;color:#666;overflow:hidden;
  white-space:nowrap;text-overflow:ellipsis}
.lni-count{font-size:.68rem;background:#eee;color:#777;
  padding:1px 5px;border-radius:8px;flex-shrink:0}
.lni-dots{display:flex;gap:2px;margin-left:2px;flex-shrink:0}
.dot{width:7px;height:7px;border-radius:50%;background:#ccc;display:inline-block}
.dot.accept{background:#4caf50}
.dot.reject{background:#f44336}
.dot.changes{background:#ff9800}

/* content */
.content{flex:1;padding:1.25rem 1.5rem;min-width:0}

/* letter sections */
.letter-section{margin-bottom:2.25rem}
.letter-section-header{display:flex;align-items:center;gap:.75rem;
  margin-bottom:1rem;padding-bottom:.5rem;border-bottom:2px solid #d0d4e8}
.lsh-char{font-size:2rem;direction:rtl;color:#1a1a2e;line-height:1}
.lsh-name{font-size:1.1rem;font-weight:600;color:#1a1a2e}
.lsh-count{font-size:.78rem;color:#888;background:#eee;
  padding:2px 8px;border-radius:10px}

/* variant cards */
.variant-card{background:#fff;border-radius:8px;padding:1rem;
  margin-bottom:.85rem;box-shadow:0 1px 3px rgba(0,0,0,.08);
  border:2px solid transparent;transition:border-color .15s}
.variant-card.verdict-accept{border-color:#4caf50}
.variant-card.verdict-reject{border-color:#f44336}
.variant-card.verdict-changes{border-color:#ff9800}
.variant-card.dirty{border-style:dashed}

.card-header{display:flex;align-items:center;gap:.6rem;
  margin-bottom:.75rem;flex-wrap:wrap}
.card-id{font-family:monospace;font-size:.83rem;color:#555}
.card-letter{font-size:.88rem;color:#444;direction:rtl}
.quality-badge{font-size:.7rem;padding:2px 7px;border-radius:10px;
  font-weight:600;margin-left:auto;flex-shrink:0}
.quality-ok{background:#e8f5e9;color:#2e7d32}
.quality-warn{background:#fff8e1;color:#e65100}
.quality-low{background:#fce4ec;color:#c62828}
.verdict-badge{font-size:.72rem;padding:2px 8px;border-radius:10px;
  font-weight:600;flex-shrink:0}
.vb-accept{background:#4caf50;color:#fff}
.vb-reject{background:#f44336;color:#fff}
.vb-changes{background:#ff9800;color:#fff}

.card-body{display:flex;gap:1.25rem;flex-wrap:wrap}

.card-image{display:flex;flex-direction:column;align-items:center;
  gap:.4rem;min-width:80px}
.glyph-img{image-rendering:pixelated;max-width:180px;min-width:48px;
  border:1px solid #ddd;background:#fff;width:auto;height:auto}
.glyph-missing{width:80px;height:80px;background:#f5f5f5;border:1px dashed #ccc;
  display:flex;align-items:center;justify-content:center;font-size:.7rem;
  color:#aaa;text-align:center;padding:.5rem;border-radius:4px}
.image-dims{font-size:.68rem;color:#aaa}

.card-meta{flex:1;min-width:180px}
.meta-table{border-collapse:collapse;width:100%;font-size:.8rem}
.meta-table th{text-align:left;color:#999;padding:2px 8px 2px 0;
  white-space:nowrap;font-weight:500;vertical-align:top}
.meta-table td{padding:2px 0;color:#333;word-break:break-all}

.card-review{flex:1;min-width:210px;display:flex;flex-direction:column;gap:.5rem}
.verdict-btns{display:flex;gap:.4rem;flex-wrap:wrap}
.verdict-btn{flex:1;padding:.38rem .5rem;font-size:.8rem;
  border:2px solid transparent;border-radius:5px;cursor:pointer;
  font-weight:500;background:#f5f5f5;color:#333;transition:all .15s;
  min-width:80px}
.verdict-btn:hover{transform:translateY(-1px);box-shadow:0 2px 5px rgba(0,0,0,.15)}
.btn-accept{border-color:#4caf50}
.btn-accept:hover,.btn-accept.active{background:#4caf50;color:#fff}
.btn-reject{border-color:#f44336}
.btn-reject:hover,.btn-reject.active{background:#f44336;color:#fff}
.btn-changes{border-color:#ff9800}
.btn-changes:hover,.btn-changes.active{background:#ff9800;color:#fff}

.comment-box{width:100%;font-size:.8rem;border:1px solid #ddd;border-radius:4px;
  padding:.38rem .5rem;resize:vertical;font-family:inherit;color:#333}
.comment-box:focus{outline:none;border-color:#4a90d9}
.card-actions{display:flex;align-items:center;gap:.75rem}
.save-btn{padding:.3rem .9rem;font-size:.78rem;border:none;border-radius:4px;
  background:#4a90d9;color:#fff;cursor:pointer;font-weight:500}
.save-btn:hover{background:#357ab8}
.saved-ok{font-size:.73rem;color:#4caf50}

.variant-card.highlight{animation:hl .8s ease-out}
@keyframes hl{0%{box-shadow:0 0 0 4px #4a90d9}100%{box-shadow:none}}

#toast{position:fixed;bottom:1.5rem;right:1.5rem;background:#222;color:#fff;
  padding:.45rem 1rem;border-radius:6px;font-size:.8rem;z-index:999;
  opacity:0;transition:opacity .25s;pointer-events:none}
#toast.show{opacity:1}
"""

# Note: all JS curly braces are literal — this is NOT an f-string.
# Dynamic values are spliced in via .replace() calls in _build_html().
_SCRIPT = r"""
const ALL_IDS = __ALL_IDS__;
let feedback = {};
let dirty = new Set();
let _currentVerdict = {};

// --- Feedback persistence ---
async function loadFeedback() {
  try {
    const r = await fetch('/feedback');
    if (r.ok) { feedback = await r.json(); restoreUI(); }
  } catch(e) {}
}

function restoreUI() {
  for (const [vid, fb] of Object.entries(feedback)) {
    if (fb.verdict) _applyVerdict(vid, fb.verdict);
    const box = document.getElementById('comment-' + vid);
    if (box && fb.comment) box.value = fb.comment;
    markSaved(vid);
  }
  updateProgress();
  updateSidebar();
}

async function _persistFeedback() {
  try {
    await fetch('/feedback', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(feedback),
    });
    dirty.clear();
  } catch(e) { showToast('Save failed: ' + e.message, true); }
}

// --- Verdict ---
function setVerdict(vid, verdict) {
  const prev = _currentVerdict[vid];
  if (prev === verdict) {
    delete _currentVerdict[vid];
    _applyVerdict(vid, null);
    if (feedback[vid]) delete feedback[vid].verdict;
  } else {
    _currentVerdict[vid] = verdict;
    _applyVerdict(vid, verdict);
    feedback[vid] = feedback[vid] || {};
    feedback[vid].verdict = verdict;
  }
  updateProgress();
  updateSidebar();
  dirty.add(vid);
}

function _applyVerdict(vid, verdict) {
  _currentVerdict[vid] = verdict;
  const card = document.getElementById('card-' + vid);
  if (!card) return;
  card.classList.remove('verdict-accept', 'verdict-reject', 'verdict-changes');
  if (verdict) card.classList.add('verdict-' + verdict);

  card.querySelectorAll('.verdict-btn').forEach(b => b.classList.remove('active'));
  if (verdict) {
    const btn = card.querySelector('.verdict-btn[data-verdict="' + verdict + '"]');
    if (btn) btn.classList.add('active');
  }

  const badge = document.getElementById('verdict-badge-' + vid);
  if (badge) {
    const labels = {accept: '✅ Accepted', reject: '❌ Rejected', changes: '🔄 Changes'};
    badge.textContent = verdict ? (labels[verdict] || verdict) : '';
    badge.className = 'verdict-badge' + (verdict ? ' vb-' + verdict : '');
  }
}

function markDirty(vid) {
  dirty.add(vid);
  const card = document.getElementById('card-' + vid);
  if (card && !feedback[vid]?.verdict) card.classList.add('dirty');
}

// --- Save card ---
async function saveCard(vid) {
  const box = document.getElementById('comment-' + vid);
  const comment = (box && box.value.trim()) || null;
  feedback[vid] = feedback[vid] || {};
  if (comment) feedback[vid].comment = comment;
  else delete feedback[vid].comment;
  if (_currentVerdict[vid]) feedback[vid].verdict = _currentVerdict[vid];
  if (!Object.keys(feedback[vid]).length) delete feedback[vid];
  await _persistFeedback();
  markSaved(vid);
  const card = document.getElementById('card-' + vid);
  if (card) card.classList.remove('dirty');
  showToast('Saved ' + vid);
}

function markSaved(vid) {
  const el = document.getElementById('saved-' + vid);
  if (el) { el.textContent = '✓ saved'; setTimeout(() => { if(el) el.textContent=''; }, 2500); }
}

// --- Progress ---
function updateProgress() {
  const reviewed = ALL_IDS.filter(id => feedback[id]?.verdict).length;
  const total = ALL_IDS.length;
  const pct = total ? (reviewed / total * 100).toFixed(0) : 0;
  const lbl = document.getElementById('progress-label');
  const fill = document.getElementById('progress-fill');
  if (lbl) lbl.textContent = reviewed + ' / ' + total + ' reviewed';
  if (fill) fill.style.width = pct + '%';
}

// --- Sidebar dots ---
function _letterAnchorId(char) {
  const pts = [...char].map(c => 'u' + c.codePointAt(0).toString(16).padStart(4, '0'));
  return 'letter-' + pts.join('');
}
function updateSidebar() {
  document.querySelectorAll('.letter-nav-item').forEach(nav => {
    const letter = nav.dataset.letter;
    const dotsEl = nav.querySelector('.lni-dots');
    if (!dotsEl || !letter) return;
    const sid = _letterAnchorId(letter);
    const section = document.getElementById(sid);
    if (!section) return;
    const cards = section.querySelectorAll('.variant-card');
    dotsEl.innerHTML = '';
    cards.forEach(card => {
      const vid = card.dataset.variantId;
      const v = feedback[vid]?.verdict;
      const dot = document.createElement('span');
      dot.className = 'dot' + (v ? ' ' + v : '');
      dotsEl.appendChild(dot);
    });
  });
}

// --- Accept all unreviewed ---
async function acceptAllUnreviewed() {
  const unrev = ALL_IDS.filter(id => !feedback[id]?.verdict);
  if (!unrev.length) { showToast('All variants already reviewed'); return; }
  unrev.forEach(vid => {
    _currentVerdict[vid] = 'accept';
    feedback[vid] = { ...(feedback[vid] || {}), verdict: 'accept' };
    _applyVerdict(vid, 'accept');
  });
  await _persistFeedback();
  updateProgress();
  updateSidebar();
  showToast('Accepted ' + unrev.length + ' unreviewed variant(s)');
}

// --- Export ---
function exportFeedback() {
  const blob = new Blob([JSON.stringify(feedback, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'review_feedback.json'; a.click();
  URL.revokeObjectURL(url);
}

// --- Toast ---
let _toastTimer = null;
function showToast(msg, err=false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.style.background = err ? '#c00' : '#222';
  el.classList.add('show');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

// --- Event delegation (replaces inline onclick/oninput) ---
document.addEventListener('click', e => {
  const vbtn = e.target.closest('.verdict-btn[data-vid]');
  if (vbtn) { setVerdict(vbtn.dataset.vid, vbtn.dataset.verdict); return; }
  const sbtn = e.target.closest('.save-btn[data-vid]');
  if (sbtn) { saveCard(sbtn.dataset.vid); }
});
document.addEventListener('input', e => {
  const box = e.target.closest('.comment-box[data-vid]');
  if (box) markDirty(box.dataset.vid);
});

// --- Active sidebar highlight on scroll ---
const _io = new IntersectionObserver(entries => {
  for (const e of entries) {
    if (e.isIntersecting) {
      document.querySelectorAll('.letter-nav-item').forEach(n => n.classList.remove('active'));
      const nav = document.querySelector('.letter-nav-item[href="#' + e.target.id + '"]');
      if (nav) nav.classList.add('active');
    }
  }
}, {rootMargin: '-5% 0px -85% 0px'});
document.querySelectorAll('.letter-section').forEach(s => _io.observe(s));

// Warn on unsaved changes
window.addEventListener('beforeunload', e => {
  if (dirty.size > 0) { e.preventDefault(); e.returnValue = ''; }
});

loadFeedback();
"""


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


def _letter_anchor(char: str) -> str:
    """Stable ASCII anchor for a Hebrew Unicode character, e.g. 'u05d0'."""
    return "".join(f"u{ord(c):04x}" for c in char)


def _ink_quality(ink_ratio: float) -> tuple[str, str]:
    """(label, css_class) for an ink_ratio in [0, 1]."""
    if ink_ratio < 0.08:
        return "Very sparse", "quality-low"
    if ink_ratio < 0.15:
        return "Sparse", "quality-warn"
    if ink_ratio <= 0.60:
        return "Normal", "quality-ok"
    return "Dense", "quality-warn"


def _build_variant_card(
    variant: dict[str, Any],
    letter_char: str,
    base_dir: Path,
    images: dict[str, Path],
) -> str:
    """Build HTML for one variant card.

    Populates *images* with ``{variant_id: absolute_path}`` for variants whose
    asset file exists; the HTTP handler serves them at ``/image/<variant_id>``.
    """
    vid = variant["variant_id"]
    vid_attr = _esc(vid)

    try:
        w = variant["image"]["width_px"]
        h = variant["image"]["height_px"]
        fmt = variant["image"]["format"]
        ink_ratio: float = variant["quality"]["ink_ratio"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Malformed variant {vid!r}: missing field {exc}") from exc

    q_label, q_cls = _ink_quality(ink_ratio)

    source = variant.get("source", {})
    scan_id = _esc(str(source.get("scan_entry_id", "—")))
    lic = _esc(str(source.get("license", "—")))
    bbox = source.get("bbox_in_source", {})
    bbox_str = (
        f"x={bbox.get('x')}, y={bbox.get('y')}, "
        f"w={bbox.get('width')}, h={bbox.get('height')}"
        if bbox
        else "—"
    )
    letter_name = _esc(_LETTER_NAMES.get(letter_char, letter_char))

    asset_path = base_dir / variant["asset_path"]
    if asset_path.exists():
        images[vid] = asset_path
        img_html = (
            f'<img src="/image/{vid_attr}" alt="{_esc(letter_char)}" class="glyph-img" '
            f'title="Original: {w}\xd7{h} px">'
        )
    else:
        img_html = '<div class="glyph-missing">Image not found</div>'

    return (
        f'<div class="variant-card" id="card-{vid_attr}" data-variant-id="{vid_attr}">\n'
        f'  <div class="card-header">\n'
        f'    <span class="card-id">{vid_attr}</span>\n'
        f'    <span class="card-letter">{_esc(letter_char)} {letter_name}</span>\n'
        f'    <span class="quality-badge {q_cls}">{q_label} ({ink_ratio:.2f})</span>\n'
        f'    <span class="verdict-badge" id="verdict-badge-{vid_attr}"></span>\n'
        f'  </div>\n'
        f'  <div class="card-body">\n'
        f'    <div class="card-image">{img_html}'
        f'      <div class="image-dims">{w}\xd7{h}&thinsp;px</div></div>\n'
        f'    <div class="card-meta"><table class="meta-table">\n'
        f'      <tr><th>Format</th><td>{_esc(str(fmt))}</td></tr>\n'
        f'      <tr><th>Size</th><td>{w}\xd7{h}&thinsp;px</td></tr>\n'
        f'      <tr><th>Ink ratio</th><td>{ink_ratio:.3f}</td></tr>\n'
        f'      <tr><th>Source</th><td><code>{scan_id}</code></td></tr>\n'
        f'      <tr><th>License</th><td>{lic}</td></tr>\n'
        f'      <tr><th>Bbox</th><td>{bbox_str}</td></tr>\n'
        f'    </table></div>\n'
        f'    <div class="card-review">\n'
        f'      <div class="verdict-btns">\n'
        f'        <button class="verdict-btn btn-accept"'
        f' data-vid="{vid_attr}" data-verdict="accept"'
        f' title="Accept">&#x2705; Accept</button>\n'
        f'        <button class="verdict-btn btn-reject"'
        f' data-vid="{vid_attr}" data-verdict="reject"'
        f' title="Reject">&#x274c; Reject</button>\n'
        f'        <button class="verdict-btn btn-changes"'
        f' data-vid="{vid_attr}" data-verdict="changes"'
        f' title="Request changes">&#x1f504; Changes</button>\n'
        f'      </div>\n'
        f'      <textarea id="comment-{vid_attr}" class="comment-box" rows="2"'
        f' data-vid="{vid_attr}"'
        f' placeholder="Optional comment…"></textarea>\n'
        f'      <div class="card-actions">\n'
        f'        <button class="save-btn" data-vid="{vid_attr}">Save</button>\n'
        f'        <span class="saved-ok" id="saved-{vid_attr}"></span>\n'
        f'      </div>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'</div>\n'
    )


def _build_sidebar(letter_set: dict[str, Any]) -> str:
    parts: list[str] = []
    for char, variants in letter_set.get("letters", {}).items():
        name = _LETTER_NAMES.get(char, char)
        anchor = _letter_anchor(char)
        count = len(variants)
        dots = "".join('<span class="dot"></span>' for _ in variants)
        parts.append(
            f'<a class="letter-nav-item" href="#letter-{anchor}"'
            f' data-letter="{_esc(char)}">'
            f'<span class="lni-char">{_esc(char)}</span>'
            f'<span class="lni-name">{_esc(name)}</span>'
            f'<span class="lni-count">{count}</span>'
            f'<span class="lni-dots">{dots}</span>'
            f'</a>'
        )
    return "\n".join(parts)


def _build_sections(
    letter_set: dict[str, Any], base_dir: Path
) -> tuple[str, list[str], dict[str, Path]]:
    """Return (sections_html, all_variant_ids, images_map).

    *images_map* maps variant_id → absolute asset path for every variant whose
    file exists on disk; used by the HTTP handler to serve ``/image/<vid>``.
    """
    sections: list[str] = []
    all_ids: list[str] = []
    images: dict[str, Path] = {}

    for char, variants in letter_set.get("letters", {}).items():
        name = _LETTER_NAMES.get(char, char)
        anchor = _letter_anchor(char)
        n = len(variants)
        s_label = "variant" if n == 1 else "variants"
        cards = "".join(_build_variant_card(v, char, base_dir, images) for v in variants)
        all_ids.extend(v["variant_id"] for v in variants)
        sections.append(
            f'<section class="letter-section" id="letter-{anchor}">\n'
            f'  <h2 class="letter-section-header">'
            f'<span class="lsh-char">{_esc(char)}</span>'
            f'<span class="lsh-name">{_esc(name)}</span>'
            f'<span class="lsh-count">{n} {s_label}</span>'
            f'</h2>\n{cards}</section>\n'
        )
    return "".join(sections), all_ids, images


def _build_html(
    letter_set: dict[str, Any],
    base_dir: Path,
) -> tuple[str, dict[str, Path]]:
    """Build the review page HTML and return ``(html_str, images_map)``."""
    writer_id = letter_set.get("writer_id", "")
    writer_label = letter_set.get("writer_label", "")
    generated_at = letter_set.get("generated_at", "")
    date_str = generated_at[:10] if generated_at else "—"

    letters = letter_set.get("letters", {})
    total = sum(len(v) for v in letters.values())

    sidebar_html = _build_sidebar(letter_set)
    sections_html, all_ids, images = _build_sections(letter_set, base_dir)

    script = _SCRIPT.replace("__ALL_IDS__", json.dumps(all_ids))

    label_line = (
        f'<div class="subtitle">{_esc(writer_label)}</div>\n' if writer_label else ""
    )
    title_esc = _esc(writer_id)

    html_str = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>Review — {title_esc}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        '<header class="top-header">\n'
        "  <div>\n"
        f'    <h1>\U0001f50c Review — {title_esc}</h1>\n'
        f"    {label_line}"
        f'    <div class="subtitle">Generated: {date_str}'
        f" &middot; {total} variant{'s' if total != 1 else ''}</div>\n"
        "  </div>\n"
        '  <div class="progress-wrap">\n'
        '    <div class="progress-label" id="progress-label">'
        f'0 / {total} reviewed</div>\n'
        '    <div class="progress-bar">'
        '<div class="progress-fill" id="progress-fill"></div></div>\n'
        "  </div>\n"
        '  <div class="header-actions">\n'
        '    <button class="hdr-btn btn-export" onclick="exportFeedback()">'
        "⬇ Export</button>\n"
        '    <button class="hdr-btn btn-accept-all" onclick="acceptAllUnreviewed()">'
        "✅ Accept unreviewed</button>\n"
        "  </div>\n"
        "</header>\n"
        '<div class="main-layout">\n'
        '  <nav class="sidebar">\n'
        '    <div class="sidebar-title">Letters</div>\n'
        f"    {sidebar_html}\n"
        "  </nav>\n"
        '  <main class="content">\n'
        f"    {sections_html}\n"
        "  </main>\n"
        "</div>\n"
        '<div id="toast"></div>\n'
        f"<script>{script}</script>\n"
        "</body>\n</html>\n"
    )
    return html_str, images


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _ReviewHandler(http.server.BaseHTTPRequestHandler):
    """Minimal handler: serves pre-built HTML, images, and manages feedback JSON.

    Concrete values for ``_html``, ``_feedback_path``, and ``_images`` must be
    provided by a subclass (``serve()`` creates one per invocation to avoid
    shared class-level state).
    """

    _html: str
    _feedback_path: Path
    _images: dict[str, Path]

    def log_message(self, fmt: str, *args: object) -> None:  # silence request log
        pass

    def do_GET(self) -> None:
        if self.path == "/":
            body = self._html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/feedback":
            data: dict[str, Any] = {}
            fp = self._feedback_path
            if fp.exists():
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/image/"):
            # Strip query string / fragment; dict lookup prevents path traversal.
            vid = self.path[len("/image/"):].split("?")[0].split("#")[0]
            img_path = self._images.get(vid)
            if img_path is None or not img_path.exists():
                self.send_response(404)
                self.end_headers()
                return
            ext = img_path.suffix.lower().lstrip(".")
            mime = _MIME_MAP.get(ext, "image/png")
            body = img_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if self.path == "/feedback":
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return
            # Atomic write: write to a sibling .tmp file then replace().
            # Prevents a corrupt feedback file if the process is killed mid-write.
            tmp = self._feedback_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self._feedback_path)
            self.send_response(204)
            self.end_headers()
        else:
            if length > 0:
                self.rfile.read(length)  # drain body before responding to avoid TCP RST
            self.send_response(404)
            self.end_headers()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def serve(
    path: Path,
    *,
    port: int = 8765,
    feedback_path: Path | None = None,
) -> None:
    """Build a review page from *path* and serve it on *localhost:port*.

    Parameters
    ----------
    path:
        Absolute or relative path to a ``letter_set.json`` file.  PNG assets
        are resolved relative to ``path.parent``.
    port:
        TCP port to listen on (default: 8765).
    feedback_path:
        Where to read/write feedback JSON.  Defaults to
        ``.review_feedback.json`` next to *path*.
    """
    path = Path(path).resolve()
    base_dir = path.parent
    if feedback_path is None:
        feedback_path = base_dir / _FEEDBACK_FILENAME

    try:
        letter_set: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"letter_set file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"letter_set file is not valid JSON: {exc}") from exc

    html_str, images = _build_html(letter_set, base_dir)

    # Create a fresh handler subclass per invocation so each server has its own
    # isolated state rather than mutating shared class attributes.
    class _Handler(_ReviewHandler):
        _html = html_str
        _feedback_path = feedback_path  # type: ignore[assignment]
        _images = images

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://localhost:{port}/"
    writer_id = letter_set.get("writer_id", path.name)
    total = sum(len(v) for v in letter_set.get("letters", {}).values())

    print(f"Review server: {url}")
    print(f"Writer:        {writer_id}  ({total} variant(s))")
    print(f"Feedback file: {feedback_path}")
    print("Press Ctrl-C to stop.")
    print()

    # The socket is bound and listening after HTTPServer.__init__(), so the
    # browser can connect immediately without a timing delay.
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


__all__ = ["serve"]
