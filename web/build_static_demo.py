"""Build the static GitHub Pages demo from the product playground.

The hosted demo is a backend-free "gallery of real certificates": each
preset renders the actual Ed25519-signed verdict that Veritas's Lean
kernel produced (captured offline via scripts/gen_demo_verdicts.py).
Custom inputs show a note pointing to the local one-command run.

Usage:
    # 1. boot the server, then capture fresh verdicts:
    #    python -m python.api.run &
    #    python web/gen_demo_verdicts.py   # writes web/demo_verdicts.json
    # 2. build the static page:
    python web/build_static_demo.py        # writes web/index.html

Single self-contained HTML (Tailwind via CDN); deploy to gh-pages root.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "python/api/static/index.html"
VERDICTS = ROOT / "web/demo_verdicts.json"
OUT = ROOT / "web/index.html"

REPO_URL = "https://github.com/lizjq66/Veritas"

html = SRC.read_text()
data = json.loads(VERDICTS.read_text())
verdicts = {k: v["cert"] for k, v in data.items()}
verdicts_js = json.dumps(verdicts, separators=(",", ":"))

# ── 1. Inject the embedded verdicts + static flag at the top of the script ──
html = html.replace(
    "<script>\nconst $ = (id) => document.getElementById(id);",
    "<script>\n"
    "const STATIC = true;\n"
    f"const DEMO_VERDICTS = {verdicts_js};\n"
    "window.__preset = null;\n"
    "const $ = (id) => document.getElementById(id);",
    1,
)

# ── 2. Banner explaining the gallery is real signed output ──────────────────
html = html.replace(
    '<body class="bg-slate-50 text-slate-800 min-h-screen">',
    '<body class="bg-slate-50 text-slate-800 min-h-screen">\n'
    '  <div class="bg-slate-900 text-slate-100 text-xs sm:text-sm px-6 py-2.5 text-center">'
    '\U0001F512 Live gallery · every certificate below is the real, Ed25519-signed verdict the '
    'Veritas <span class="mono text-emerald-300">veritas-core</span> Lean kernel produced. '
    f'Pick a scenario. · <a href="{REPO_URL}" class="underline hover:text-white">source &amp; one-command local run ↗</a>'
    '</div>',
    1,
)

# ── 3. Track the active preset on click (need the index, not the object) ────
html = html.replace(
    'c.querySelectorAll(".preset").forEach(b => b.addEventListener("click", () => applyPreset(PRESETS[+b.dataset.i])));',
    'c.querySelectorAll(".preset").forEach(b => b.addEventListener("click", () => { window.__preset = +b.dataset.i; applyPreset(PRESETS[+b.dataset.i]); }));',
    1,
)

# ── 4. A real manual edit invalidates the preset (custom input) ─────────────
html = html.replace(
    'document.querySelectorAll("input, select").forEach(el => el.addEventListener("change", updatePreview));',
    'document.querySelectorAll("input, select").forEach(el => el.addEventListener("change", () => { window.__preset = null; updatePreview(); }));',
    1,
)

# ── 5. Initial auto-run is preset 0 ─────────────────────────────────────────
html = html.replace(
    "// Kick off the first preset so the page isn't empty on load.\napplyPreset(PRESETS[0]);",
    "// Kick off the first preset so the page isn't empty on load.\nwindow.__preset = 0; applyPreset(PRESETS[0]);",
    1,
)

# ── 6. verify(): serve the embedded real cert; note for custom inputs ───────
OLD_VERIFY = '''async function verify() {
  const body = buildBody();
  $("verify-btn").disabled = true;
  $("verify-btn").textContent = "verifying…";
  try {
    const r = await fetch("/verify/proposal", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const cert = await r.json();
    renderCert(cert);
  } catch (e) {
    $("verdict-line").textContent = "error: " + e.message;
    $("verdict-line").className = "text-lg font-semibold text-red-600";
  } finally {
    $("verify-btn").disabled = false;
    $("verify-btn").textContent = "POST /verify/proposal";
  }
}'''

NEW_VERIFY = '''function resetGates() {
  ["gate1", "gate2", "gate3"].forEach(id => renderGate(id, null));
  $("assumptions-block").classList.add("hidden");
  $("raw-json").textContent = "";
  $("final-notional").querySelector(".text-xl").textContent = "—";
  $("final-notional").querySelector(".text-xl").className = "text-xl font-bold mono text-slate-400";
}
function verify() {
  const idx = window.__preset;
  if (idx === null || idx === undefined || !(idx in DEMO_VERDICTS)) {
    // Custom input: this hosted gallery has no Lean kernel behind it.
    resetGates();
    $("verdict-line").innerHTML = 'Hosted gallery — pick a preset above. For arbitrary proposals, run Veritas locally: <a href="' + "''' + REPO_URL + '''" + '" class="underline text-slate-600">github.com/lizjq66/Veritas</a>';
    $("verdict-line").className = "text-sm font-medium text-slate-500";
    return;
  }
  renderCert(DEMO_VERDICTS[idx]);
}'''

assert OLD_VERIFY in html, "verify() anchor not found — did index.html change?"
html = html.replace(OLD_VERIFY, NEW_VERIFY, 1)

# ── 7. Drop the example-runner dashboard links ──────────────────────────────
# The runner is a backend example with no static deployment; on the hosted
# gallery both /runner links would 404. Strip them (header + footer).
RUNNER_HEADER = '\n        <a href="/runner" class="underline hover:text-slate-600">example runner &rarr;</a>'
RUNNER_HEADER_ALT = '\n        <a href="/runner" class="underline hover:text-slate-600">example runner →</a>'
RUNNER_FOOTER = ' · <a href="/runner" class="underline hover:text-slate-600">example runner dashboard</a>'
header_hit = RUNNER_HEADER if RUNNER_HEADER in html else RUNNER_HEADER_ALT
assert header_hit in html, "runner header link anchor not found — did index.html change?"
assert RUNNER_FOOTER in html, "runner footer link anchor not found — did index.html change?"
html = html.replace(header_hit, "", 1)
html = html.replace(RUNNER_FOOTER, "", 1)
assert "/runner" not in html, "a /runner link survived the static build"

OUT.write_text(html)
print(f"wrote {OUT} ({len(html):,} bytes, {len(verdicts)} embedded certificates)")
