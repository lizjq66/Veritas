"""POST each playground preset to the live Veritas server and capture the
real signed certificate. Mirrors the v0.4 PRESETS in index.html exactly."""
import json
import urllib.request

URL = "http://127.0.0.1:8000/verify/proposal"

PRESETS = [
    ("Clean approve (funding only)",            "LONG",  1500, 0.0012, 68000, 0,     0,        16, 4,  None),
    ("All 3 strategies agree",                  "LONG",  1500, 0.0012, 67700, 68000, -100e6,   16, 4,  None),
    ("Cascade alone fires SHORT",               "SHORT", 1500, 0,      68000, 0,      100e6,   16, 4,  None),
    ("3-way conflict (2 SHORT, 1 LONG)",        "SHORT", 1500, 0.0012, 68300, 68000,  100e6,   16, 4,  None),
    ("Strategies contradict (funding vs basis)","LONG",  1500, 0.0012, 68300, 68000, 0,        16, 4,  None),
    ("Only basis fires -> SHORT",               "SHORT", 1500, 0,      68300, 68000, 0,        16, 4,  None),
    ("Direction conflict (vs funding)",         "LONG",  1500, -0.0008,68000, 0,     0,        16, 4,  None),
    ("No signal under any policy",              "LONG",  1500, 0.0001, 68000, 0,     0,        16, 4,  None),
    ("Oversize -> resize",                      "LONG",  9000, 0.0012, 68000, 0,     0,        27, 3,  None),
    ("No edge (posterior <= 1/2)",              "LONG",  1000, 0.0012, 68000, 0,     0,        15, 15, None),
    ("Portfolio conflict",                      "LONG",  1000, 0.0012, 68000, 0,     0,        16, 4,  ("SHORT", 67500, 0.03)),
]


def build_body(p):
    label, d, notional, funding, price, spot, liq, succ, fail, pos = p
    body = {
        "proposal": {
            "direction": d, "notional_usd": notional, "funding_rate": funding,
            "price": price, "timestamp": 0, "open_interest": 0,
            "spot_price": spot, "liquidations24h": liq,
        },
        "constraints": {
            "equity": 10000, "successes": succ, "failures": fail,
            "max_leverage": 1.0, "max_position_fraction": 0.25, "stop_loss_pct": 5.0,
        },
    }
    if pos:
        pd, entry, size = pos
        body["portfolio"] = {
            "positions": [{"direction": pd, "entry_price": entry, "size": size}],
            "max_gross_exposure_fraction": 0.50,
        }
    return body


def post(body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


out = {}
print(f"{'#':>2}  {'label':42}  {'final':>9}  g1/g2/g3")
for i, p in enumerate(PRESETS):
    body = build_body(p)
    cert = post(body)
    out[str(i)] = {"label": p[0], "body": body, "cert": cert}
    g = lambda k: (cert.get(k) or {}).get("verdict", "-")
    fin = cert.get("final_notional_usd")
    fin_s = f"${fin:,.0f}" if isinstance(fin, (int, float)) else "-"
    appr = "APPROVE" if cert.get("approves") else "REJECT "
    print(f"{i:>2}  {p[0]:42}  {fin_s:>9}  {g('gate1')}/{g('gate2')}/{g('gate3')}  {appr}")

with open("web/demo_verdicts.json", "w") as f:
    json.dump(out, f, indent=2)
print("\nsaved -> web/demo_verdicts.json")
# sanity: confirm signatures are present & non-empty
sig0 = out["0"]["cert"].get("attestation", {}).get("signature", "")
print("attestation.signature present on #0:", bool(sig0), f"(len={len(sig0)})")
