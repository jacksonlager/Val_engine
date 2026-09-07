"""Write variant Q3 2026 workbooks — a *new version* of the mock portfolio, same schema, different content.

    python3 scripts/make_variant_workbooks.py [out_dir]        # default training/variants/

Every variant is derived deterministically from data/HC_Mock_Portfolio_Data.xlsx, so the test suite
regenerates them into a temp folder (tests/test_variant_workbooks.py) and nothing binary is committed.

    v1_renamed.xlsx     every company renamed; sectors reshuffled, one the comps baskets do not know;
                        funds "Fund IV" / "Opportunity Fund"; stages "Pre-Seed" and "Series E"
    v2_renumbered.xlsx  marks, post-moneys, ownerships and metrics scaled; blanks (pre-revenue), zero
                        burn (breakeven), negative growth; four prior marks deliberately off (X-904)
    v3_busy.xlsx        44 activity rows across every event type the engine knows, companies with two
                        or three events, a new company, two unknown event types, one unknown company
    v4_messy.xlsx       a title row above the header, headers re-cased, columns reordered, an extra
                        column, blank rows, values typed as text, dates as strings, a Total row
    v5_small.xlsx       20 companies, 3 events
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "HC_Mock_Portfolio_Data.xlsx"
DEFAULT_OUT = ROOT / "training" / "variants"

PORTFOLIO_HEADERS = ["Company", "Sector", "Fund", "Stage", "Status", "First Investment", "Latest Round",
                     "Latest Post-Money ($M)", "Invested ($M)", "Ownership (FD %)", "Prior Mark ($M)", "Realized ($M)",
                     "MOIC (x)", "ARR ($M)", "ARR Growth (YoY %)", "Gross Margin (%)", "Net Burn ($M/mo)", "Cash ($M)",
                     "Runway (mo)", "Headcount"]
ACTIVITY_HEADERS = ["Date", "Company", "Event", "Detail", "Post-Money / Deal Value ($M)", "HC Investment ($M)",
                    "HC Ownership After (FD %)", "Proceeds to HC ($M)", "Notes"]

_PREFIX = ["Ash", "Bram", "Cor", "Dun", "Elm", "Fen", "Gal", "Hol", "Ivo", "Jar", "Kel", "Lor", "Mor", "Nes", "Orl",
           "Pen", "Quen", "Ros", "Sil", "Tar", "Ulm", "Vel", "Wyn", "Xan", "Yor", "Zel"]
_SUFFIX = ["haven", "worth", "field", "crest", "mere", "bridge", "gate", "stone", "wick", "dale", "ford", "moor"]
_TAIL = ["", "", " Labs", " Systems", " Bio", " AI", " Robotics", " Analytics"]


def _read(path: Path = SOURCE):
    wb = openpyxl.load_workbook(path, data_only=True)
    port = [list(r) for r in wb["Portfolio"].iter_rows(values_only=True)]
    act = [list(r) for r in wb["Q3 2026 Activity"].iter_rows(values_only=True)]
    fdef = [list(r) for r in wb["Field Definitions"].iter_rows(values_only=True)]
    return port, act, fdef


def _write(path: Path, port: list[list], act: list[list], fdef: list[list], *, activity_sheet: str = "Q3 2026 Activity") -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio"
    for row in port:
        ws.append(row)
    wa = wb.create_sheet(activity_sheet)
    for row in act:
        wa.append(row)
    wd = wb.create_sheet("Field Definitions")
    for row in fdef:
        wd.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _new_name(i: int) -> str:
    return f"{_PREFIX[i % len(_PREFIX)]}{_SUFFIX[(i * 7) % len(_SUFFIX)]}{_TAIL[(i * 3) % len(_TAIL)]}"


def _col(headers: list, name: str) -> int:
    return headers.index(name)


# ----------------------------------------------------------------------------- v1 renamed

def v1_renamed(out: Path) -> Path:
    port, act, fdef = _read()
    h = port[0]
    names = {}
    for i, row in enumerate(port[1:]):
        if row[0]:
            names[row[0]] = _new_name(i)
    sectors = {"AI/ML": "Applied AI", "Developer Tools": "DevOps & Tooling", "Enterprise SaaS": "Vertical SaaS",
               "Fintech": "Payments & Lending", "Cybersecurity": "Security", "Data & Analytics": "Data Platforms",
               "Infrastructure": "Cloud Infrastructure", "Healthcare": "Digital Health", "Robotics": "Quantum Hardware",
               "Climate & Energy": "Energy Transition", "Space & Defense": "Aerospace", "Consumer": "Consumer Apps"}
    funds = {"Fund I": "Fund IV", "Fund II": "Opportunity Fund", "Fund III": "Fund III"}
    stages = {"Seed": "Pre-Seed", "Series D+": "Series E"}
    for row in port[1:]:
        if not row[0]:
            continue
        row[_col(h, "Company")] = names[row[0]]
        row[_col(h, "Sector")] = sectors.get(row[_col(h, "Sector")], row[_col(h, "Sector")])
        row[_col(h, "Fund")] = funds.get(row[_col(h, "Fund")], row[_col(h, "Fund")])
        row[_col(h, "Stage")] = stages.get(row[_col(h, "Stage")], row[_col(h, "Stage")])
    ah = act[0]
    for row in act[1:]:
        if row[_col(ah, "Company")] in names:
            row[_col(ah, "Company")] = names[row[_col(ah, "Company")]]
    return _write(out / "v1_renamed.xlsx", port, act, fdef)


# ----------------------------------------------------------------------------- v2 renumbered

def v2_renumbered(out: Path) -> Path:
    port, act, fdef = _read()
    h = port[0]
    c = {k: _col(h, k) for k in h if k}
    off_by = {"Beltrix", "Quindle", "Xalorin", "Fenwright"}      # deliberately unreconciled prior marks -> X-904
    pre_revenue = {"Emberfold", "Lumetra", "Gablewood", "Underbough", "Yewbranch Security"}
    breakeven = {"Fernwave", "Vexmoor", "Mossbriar Bio"}
    for row in port[1:]:
        if not row[0]:
            continue
        post = row[c["Latest Post-Money ($M)"]]; own = row[c["Ownership (FD %)"]]
        if isinstance(post, (int, float)) and isinstance(own, (int, float)):
            post = round(post * 1.3, 1); own = round(min(own * 0.9, 0.99), 3)
            row[c["Latest Post-Money ($M)"]] = post; row[c["Ownership (FD %)"]] = own
            if row[c["Status"]] == "Active":
                row[c["Prior Mark ($M)"]] = round(own * post, 2) + (0.5 if row[0] in off_by else 0.0)
        if isinstance(row[c["Invested ($M)"]], (int, float)):
            row[c["Invested ($M)"]] = round(row[c["Invested ($M)"]] * 1.1, 2)
        if row[c["Status"]] == "Active":
            if row[0] in pre_revenue:
                row[c["ARR ($M)"]] = None; row[c["ARR Growth (YoY %)"]] = None
            else:
                if isinstance(row[c["ARR ($M)"]], (int, float)):
                    row[c["ARR ($M)"]] = round(row[c["ARR ($M)"]] * 0.8, 2)
                if isinstance(row[c["ARR Growth (YoY %)"]], (int, float)):
                    row[c["ARR Growth (YoY %)"]] = round(row[c["ARR Growth (YoY %)"]] - 0.1, 3)
            if row[0] in breakeven:
                row[c["Net Burn ($M/mo)"]] = 0
                row[c["Runway (mo)"]] = "-"
            elif isinstance(row[c["Cash ($M)"]], (int, float)) and isinstance(row[c["Net Burn ($M/mo)"]], (int, float)) and row[c["Net Burn ($M/mo)"]]:
                row[c["Runway (mo)"]] = row[c["Cash ($M)"]] / row[c["Net Burn ($M/mo)"]]
        # the sheet's live MOIC formula, recomputed: a new version of the file carries consistent formulas
        inv = row[c["Invested ($M)"]]; pm = row[c["Prior Mark ($M)"]]; rz = row[c["Realized ($M)"]]
        if isinstance(inv, (int, float)) and inv and isinstance(pm, (int, float)):
            row[c["MOIC (x)"]] = (pm + (rz or 0)) / inv
    ah = act[0]
    ac = {k: _col(ah, k) for k in ah if k}
    for row in act[1:]:
        if isinstance(row[ac["Post-Money / Deal Value ($M)"]], (int, float)):
            row[ac["Post-Money / Deal Value ($M)"]] = round(row[ac["Post-Money / Deal Value ($M)"]] * 1.3, 1)
        if isinstance(row[ac["HC Ownership After (FD %)"]], (int, float)):
            row[ac["HC Ownership After (FD %)"]] = round(row[ac["HC Ownership After (FD %)"]] * 0.9, 3)
    return _write(out / "v2_renumbered.xlsx", port, act, fdef)


# ----------------------------------------------------------------------------- v3 busy

def v3_busy(out: Path) -> Path:
    port, act, fdef = _read()
    h = port[0]
    c = {k: _col(h, k) for k in h if k}
    book = {row[0]: row for row in port[1:] if row[0]}
    act = [act[0]]
    d = lambda m, day: datetime(2026, m, day)   # noqa: E731

    def ev(date, company, event, detail, value=None, inv=None, own=None, proceeds=None, notes=""):
        act.append([date, company, event, detail, value, inv, own, proceeds, notes])

    own = lambda n: float(book[n][c["Ownership (FD %)"]])   # noqa: E731
    post = lambda n: float(book[n][c["Latest Post-Money ($M)"]])   # noqa: E731

    # ---- priced rounds of every shape
    ev(d(7, 2), "Aravine", "Priced Equity Round", "Series B", 128.5, None, 0.108, None, "$26.4M round led by a new investor. HC did not participate.")
    ev(d(7, 3), "Jettamar", "Priced Equity Round", "Series A", 43.0, 1.3, 0.111, None, "$10.8M round led by a new investor. HC participated pro rata.")
    ev(d(7, 6), "Pellagrin", "Priced Equity Round", "Series B extension (same terms)", 176.3, 1.1, 0.079, None, "Extension of the prior round at the same post-money.")
    ev(d(7, 8), "Oakenvale", "Priced Equity Round", "Series B (recap)", 37.0, None, 0.063, None, "$7.8M insider-led round. HC did not participate.")
    ev(d(7, 9), "Tarnwick Aerospace", "Priced Equity Round", "Series A (recap)", 14.2, 0.3, 0.08, None, "$4.1M insider-led round. HC participated.")
    ev(d(7, 10), "Covebright", "Priced Equity Round", "Series C", 900.0, 2.0, 0.058, None, "$120M round led by HC.")
    ev(d(7, 13), "Lumetra", "Priced Equity Round", "Series A", 13.0, None, 0.085, None, "$3.0M insider-led round. No new investor.")
    ev(d(7, 14), "Zephrine", "Priced Equity Round", "Series A", 30.0, None, 0.130, None, "$8.0M round led by a new investor. HC did not participate.")
    ev(d(7, 15), "Kilnbrook", "Priced Equity Round", "Series B", 120.0, 1.5, 0.079, None, "$24.0M round led by a new investor. HC participated.")
    ev(d(7, 16), "Wildebrook", "Priced Equity Round", "Series B", 120.0, None, 0.100, None, "$25.0M round led by a new investor. HC did not participate.")
    # ---- notes, then conversions and repayments
    ev(d(7, 20), "Emberfold", "Convertible Note", "$8.5M bridge note, $32.0M valuation cap", None, None, None, None, "Uncapped interest, converts at next priced round.")
    ev(d(8, 20), "Emberfold", "Priced Equity Round", "Series A", 40.0, None, 0.065, None, "$9.0M round led by a new investor. The note rolled in at its cap.")
    ev(d(7, 21), "Duskfern", "Convertible Note", "$4.7M bridge note, $133.0M valuation cap", None, 0.5, None, None, "Uncapped interest, converts at next priced round. HC participated in the note.")
    ev(d(7, 22), "Yarrowbank", "Convertible Note", "$1.0M bridge note, $45.0M valuation cap", None, 0.3, None, None, "HC participated in the note.")
    ev(d(9, 22), "Yarrowbank", "Note Repaid", "Bridge note repaid with interest", None, None, None, 0.31, "Repaid from operating cash.")
    ev(d(7, 23), "Tidewell Health", "Convertible Note", "$2.0M bridge note, $20.0M valuation cap", None, None, None, None, "HC did not participate.")
    # ---- exits, announcements, terminations, distributions
    ev(d(8, 12), "Cindral", "Acquisition (Closed)", "All-cash acquisition", 324.0, None, None, 28.2, "Transaction closed and cash received during the quarter.")
    ev(d(9, 20), "Cindral", "Distribution", "Escrow release", None, None, None, 1.0, "First escrow tranche released.")
    ev(d(8, 13), "Knollward", "Acquisition (Closed)", "All-cash acquisition", 30.0, None, None, None, "Transaction closed.")
    ev(d(8, 14), "Arcfoundry", "Acquisition (Closed)", "All-cash acquisition", 200.0, None, None, round(own("Arcfoundry") * 200 * 0.9, 4), "Closed; 10% of the consideration is held back for 12 months.")
    ev(d(8, 15), "Halcyra", "Acquisition (Closed)", "Acquired for stock of the buyer", 65.0, None, None, None, "All-stock consideration; the buyer is privately held.")
    ev(d(9, 8), "Gryphonel", "Acquisition (Announced)", "Definitive agreement signed, all cash", 133.0, None, None, None, "Expected to close in Q4 2026, subject to regulatory approval. No cash received.")
    ev(d(9, 9), "Pinwhistle", "Acquisition (Announced)", "Definitive agreement signed, all cash", 60.0, None, None, None, "Expected to close in Q4 2026. No cash received.")
    ev(d(9, 25), "Pinwhistle", "Acquisition (Terminated)", "Buyer walked away", None, None, None, None, "Regulatory approval denied; the agreement was terminated.")
    ev(d(9, 10), "Elmsworth Data", "Acquisition (Announced)", "Non-binding letter of intent", 900.0, None, None, None, "Non-binding LOI only; no signed definitive agreement.")
    ev(d(9, 11), "Kolvani Health", "Distribution", "Escrow release", None, None, None, 0.9, "Final escrow distribution after the prior acquisition.")
    # ---- secondaries and adjustments
    ev(d(8, 19), "Marrowick Bio", "Secondary Sale", "HC sold 30% of its position", 516.0, None, 0.017, 3.9, "Buyer paid a price consistent with the latest round.")
    ev(d(8, 21), "Fernwave", "Secondary Sale", "HC sold 25% of its position", 1930.0, None, 0.030, 19.3, "Buyer paid 5% above the Series D price.")
    ev(d(8, 22), "Mirthstone", "Secondary Purchase", "HC bought from a departing angel", 122.5, 0.245, 0.056, None, "Bought at the Series B price.")
    ev(d(8, 24), "Vexmoor", "Ownership Adjustment", "Warrant exercise", None, 0.2, 0.060, None, "HC exercised warrants attached to the Series C.")
    # ---- listings and reorganisations
    ev(d(9, 20), "Drayvenn", "IPO", "Listed on Nasdaq", 3931.0, None, 0.028, None, "Priced at the top of the range. HC shares subject to a 180-day lock-up.")
    ev(d(9, 21), "Thornmill Systems", "Direct Listing", "Listed on Nasdaq", 2500.0, None, 0.013, None, "Direct listing; no lock-up.")
    ev(d(9, 12), "Umberly", "Bankruptcy (Chapter 11)", "Filed for Chapter 11 reorganisation", None, None, None, None, "Debtor-in-possession financing from existing lenders.")
    # ---- shutdowns
    ev(d(9, 14), "Larkspell", "Shutdown", "Ceased operations", None, None, None, 0.4, "Board voted to wind down. Residual cash distributed to investors.")
    ev(d(9, 22), "Islewind", "Shutdown", "Ceased operations", None, None, None, None, "Board voted to wind down. No recovery expected.")
    ev(d(9, 23), "Wrenfield Data", "Shutdown", "Ceased operations; assets sold", None, None, None, 14.0, "Asset sale returned more than the carrying value.")
    # ---- term sheets, one closing in the quarter
    ev(d(9, 17), "Redgrove Health", "Term Sheet Signed", "Series B term sheet at ~$40.0M post", 40.0, None, None, None, "Not closed; diligence underway.")
    ev(d(9, 18), "Dovelane Systems", "Term Sheet Signed", "Series C term sheet at ~$83.0M post", 83.0, None, None, None, "Not closed; expected to close Q4.")
    ev(d(9, 24), "Dovelane Systems", "Priced Equity Round", "Series C", 83.0, None, 0.050, None, "$15.0M round led by a new investor at the term-sheet price. HC did not participate.")
    # ---- a new company, unknown event types, an unknown company
    ev(d(8, 3), "Quillbrook Labs", "New Investment", "Seed — Fund III, Cybersecurity", 18.0, 1.5, 0.083, None, "First cheque from Fund III into a Cybersecurity seed round.")
    ev(d(8, 5), "Brumewell", "Operating Update", "Revenue contraction confirmed", None, None, None, None, "June reporting: ARR down 21% year on year.")
    ev(d(8, 6), "Nettlebay", "Stock Split", "Two-for-one split of every share class", None, None, 0.052, None, "No new cash, dilution or economic value change.")
    ev(d(8, 7), "Nonesuch Ventures", "Term Sheet Signed", "Series A term sheet", 10.0, None, None, None, "Not a portfolio company.")
    ev(d(9, 29), "Quillbrook Labs", "Term Sheet Signed", "Series A term sheet at ~$40M post", 40.0, None, None, None, "Signed six weeks after the seed.")
    return _write(out / "v3_busy.xlsx", port, act, fdef)


# ----------------------------------------------------------------------------- v4 messy

def v4_messy(out: Path) -> Path:
    port, act, fdef = _read()
    h = port[0]
    # re-case and pad headers, reorder columns, add one
    order = ["Company", "Status", "Sector", "Fund", "Stage", "Latest Round", "First Investment", "Latest Post-Money ($M)",
             "Ownership (FD %)", "Invested ($M)", "Prior Mark ($M)", "Realized ($M)", "MOIC (x)", "ARR ($M)",
             "ARR Growth (YoY %)", "Gross Margin (%)", "Net Burn ($M/mo)", "Cash ($M)", "Runway (mo)", "Headcount"]
    recased = {"Company": "COMPANY ", "Sector": " sector", "Fund": "Fund", "Stage": "Stage ", "Status": "STATUS",
               "Ownership (FD %)": "ownership (fd %)", "Prior Mark ($M)": "Prior mark ($M)", "Cash ($M)": " Cash ($M) "}
    new_port = [["HC Mock Portfolio — Q3 2026 refresh (v4)"] + [None] * 20, [None] * 21,
                [recased.get(k, k) for k in order] + ["Analyst Notes"]]
    idx = {k: _col(h, k) for k in h if k}
    n = 0
    for row in port[1:]:
        if not row[0]:
            continue
        r = [row[idx[k]] for k in order] + [f"note {n}"]
        # a few cells typed as text
        if n % 9 == 0 and isinstance(r[order.index("Prior Mark ($M)")], (int, float)):
            r[order.index("Prior Mark ($M)")] = f"${r[order.index('Prior Mark ($M)')]:.1f}M"
        if n % 11 == 0 and isinstance(r[order.index("Ownership (FD %)")], (int, float)):
            r[order.index("Ownership (FD %)")] = f"{r[order.index('Ownership (FD %)')] * 100:.1f}%"
        if n % 13 == 0 and isinstance(r[order.index("Latest Round")], datetime):
            r[order.index("Latest Round")] = r[order.index("Latest Round")].strftime("%d-%b-%Y")
        new_port.append(r)
        n += 1
        if n % 25 == 0:
            new_port.append([None] * 21)          # a blank row inside the data
    new_port.append(["Total"] + [None] * 9 + [sum(float(r[idx["Prior Mark ($M)"]] or 0) for r in port[1:] if r[0])] + [None] * 10)
    ah = act[0]
    new_act = [[None] * 9, ["date", "COMPANY", "Event ", "Detail", "Post-Money / Deal Value ($M)", "HC Investment ($M)",
                            "HC Ownership After (FD %)", "Proceeds to HC ($M)", "Notes"]]
    for i, row in enumerate(act[1:]):
        r = list(row)
        if i % 4 == 0 and isinstance(r[0], datetime):
            r[0] = r[0].strftime("%d-%b-%Y")
        if i % 5 == 0 and isinstance(r[4], (int, float)):
            r[4] = f"${r[4]}M"
        if i % 6 == 0 and isinstance(r[6], (int, float)):
            r[6] = f"{r[6] * 100:.1f}%"
        new_act.append(r)
        if i == 7:
            new_act.append([None] * 9)
    return _write(out / "v4_messy.xlsx", new_port, new_act, fdef)


# ----------------------------------------------------------------------------- v5 small

def v5_small(out: Path) -> Path:
    port, act, fdef = _read()
    keep = [row for row in port[1:] if row[0]][:20]
    names = {row[0] for row in keep}
    small_act = [act[0]] + [row for row in act[1:] if row[1] in names][:3]
    return _write(out / "v5_small.xlsx", [port[0]] + keep, small_act, fdef)


VARIANTS = {"v1_renamed": v1_renamed, "v2_renumbered": v2_renumbered, "v3_busy": v3_busy, "v4_messy": v4_messy, "v5_small": v5_small}


def write_all(out: Path = DEFAULT_OUT) -> dict[str, Path]:
    return {name: fn(out) for name, fn in VARIANTS.items()}


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    for name, path in write_all(out).items():
        print(f"wrote {path}")
