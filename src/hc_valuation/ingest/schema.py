"""Column contract for the two input tabs.

Column names are the workbook's own. `REQUIRED_*` lists are what a refreshed file must
carry; anything else is recorded as an unknown column and surfaced in validation.
"""
from __future__ import annotations

from ..engine.inputs import (  # noqa: F401  re-exported for ingest callers
    KNOWN_EVENT_TYPES, ActivityFeed, Event, EventType, PortfolioSnapshot, Position, Status,
)

PORTFOLIO_COLUMNS: dict[str, str] = {
    "Company": "company",
    "Sector": "sector",
    "Fund": "fund",
    "Stage": "stage",
    "Status": "status",
    "First Investment": "first_investment",
    "Latest Round": "latest_round",
    "Latest Post-Money ($M)": "latest_post_money",
    "Invested ($M)": "invested",
    "Ownership (FD %)": "ownership",
    "Prior Mark ($M)": "prior_mark",
    "Realized ($M)": "realized",
    "MOIC (x)": "sheet_moic",
    "ARR ($M)": "arr",
    "ARR Growth (YoY %)": "arr_growth",
    "Gross Margin (%)": "gross_margin",
    "Net Burn ($M/mo)": "net_burn",
    "Cash ($M)": "cash",
    "Runway (mo)": "sheet_runway",
    "Headcount": "headcount",
}
REQUIRED_PORTFOLIO: tuple[str, ...] = (
    "Company", "Sector", "Fund", "Stage", "Status", "Latest Round",
    "Latest Post-Money ($M)", "Invested ($M)", "Ownership (FD %)", "Prior Mark ($M)", "Realized ($M)",
)

ACTIVITY_COLUMNS: dict[str, str] = {
    "Date": "date",
    "Company": "company",
    "Event": "event_type",
    "Detail": "detail",
    "Post-Money / Deal Value ($M)": "value",
    "HC Investment ($M)": "hc_investment",
    "HC Ownership After (FD %)": "ownership_after",
    "Proceeds to HC ($M)": "proceeds",
    "Notes": "notes",
}
REQUIRED_ACTIVITY: tuple[str, ...] = ("Date", "Company", "Event")

# ---------------------------------------------------------------- normalization contract (SPEC §2.2, §2.3)

# Header aliases, per tab. The same alias can mean different columns on different tabs
# ("post-money" is the book's last round on Portfolio but the deal value on Activity;
# "distributions" is Realized vs Proceeds), so the tables are kept apart.
PORTFOLIO_HEADER_ALIASES: dict[str, str] = {
    "company name": "Company", "portfolio company": "Company", "name": "Company", "co": "Company",
    "industry": "Sector", "vertical": "Sector",
    "vehicle": "Fund", "fund name": "Fund",
    "round": "Stage", "last round": "Stage", "latest stage": "Stage",
    "state": "Status",
    "initial investment date": "First Investment", "first invested": "First Investment", "entry date": "First Investment",
    "last round date": "Latest Round", "latest round date": "Latest Round", "last priced round": "Latest Round",
    "post-money": "Latest Post-Money ($M)", "post money": "Latest Post-Money ($M)", "latest post money": "Latest Post-Money ($M)",
    "post-money valuation": "Latest Post-Money ($M)", "last post": "Latest Post-Money ($M)",
    "invested capital": "Invested ($M)", "total invested": "Invested ($M)", "cost": "Invested ($M)", "cost basis": "Invested ($M)",
    "ownership": "Ownership (FD %)", "fd ownership": "Ownership (FD %)", "fully diluted ownership": "Ownership (FD %)",
    "ownership %": "Ownership (FD %)", "fd %": "Ownership (FD %)",
    "prior mark": "Prior Mark ($M)", "carrying value": "Prior Mark ($M)", "fair value": "Prior Mark ($M)", "fv": "Prior Mark ($M)",
    "mark": "Prior Mark ($M)", "current mark": "Prior Mark ($M)",
    "realized": "Realized ($M)", "realised": "Realized ($M)", "proceeds to date": "Realized ($M)", "distributions": "Realized ($M)",
    "moic": "MOIC (x)", "multiple": "MOIC (x)",
    "arr": "ARR ($M)", "revenue": "ARR ($M)", "annual recurring revenue": "ARR ($M)", "run-rate revenue": "ARR ($M)",
    "arr growth": "ARR Growth (YoY %)", "growth": "ARR Growth (YoY %)", "yoy growth": "ARR Growth (YoY %)",
    "revenue growth": "ARR Growth (YoY %)",
    "gross margin": "Gross Margin (%)", "gm": "Gross Margin (%)", "gm %": "Gross Margin (%)",
    "net burn": "Net Burn ($M/mo)", "burn": "Net Burn ($M/mo)", "monthly burn": "Net Burn ($M/mo)", "burn rate": "Net Burn ($M/mo)",
    "cash": "Cash ($M)", "cash on hand": "Cash ($M)", "cash balance": "Cash ($M)",
    "runway": "Runway (mo)", "runway months": "Runway (mo)", "months of runway": "Runway (mo)",
    "employees": "Headcount", "fte": "Headcount", "ftes": "Headcount", "team size": "Headcount",
}

ACTIVITY_HEADER_ALIASES: dict[str, str] = {
    "event date": "Date", "transaction date": "Date", "close date": "Date",
    "company name": "Company", "portfolio company": "Company", "name": "Company", "co": "Company",
    "event type": "Event", "activity": "Event", "transaction": "Event", "type": "Event",
    "details": "Detail", "description": "Detail", "round name": "Detail",
    "post-money": "Post-Money / Deal Value ($M)", "deal value": "Post-Money / Deal Value ($M)",
    "valuation": "Post-Money / Deal Value ($M)", "post money / deal value": "Post-Money / Deal Value ($M)",
    "value": "Post-Money / Deal Value ($M)", "post-money/deal value": "Post-Money / Deal Value ($M)",
    "hc investment": "HC Investment ($M)", "new investment": "HC Investment ($M)", "invested this round": "HC Investment ($M)",
    "hc participation": "HC Investment ($M)", "our investment": "HC Investment ($M)",
    "ownership after": "HC Ownership After (FD %)", "hc ownership after": "HC Ownership After (FD %)",
    "fd % after": "HC Ownership After (FD %)", "post-round ownership": "HC Ownership After (FD %)",
    "ownership post": "HC Ownership After (FD %)",
    "proceeds": "Proceeds to HC ($M)", "proceeds to hc": "Proceeds to HC ($M)", "cash received": "Proceeds to HC ($M)",
    "cash to hc": "Proceeds to HC ($M)", "distributions": "Proceeds to HC ($M)",
    "note": "Notes", "comments": "Notes", "commentary": "Notes", "remarks": "Notes",
}

# Columns carrying $M. A value far above any plausible $M figure was typed in dollars (X-916).
MUSD_COLUMNS: frozenset[str] = frozenset({
    "Latest Post-Money ($M)", "Invested ($M)", "Prior Mark ($M)", "Realized ($M)", "ARR ($M)",
    "Net Burn ($M/mo)", "Cash ($M)",
    "Post-Money / Deal Value ($M)", "HC Investment ($M)", "Proceeds to HC ($M)",
})
# Fractions that a human may type in percentage points (55 for 55%). Ownership and margin
# cannot legitimately exceed 1, so > 1 is read as points (X-916).
PERCENT_COLUMNS: frozenset[str] = frozenset({"Ownership (FD %)", "HC Ownership After (FD %)", "Gross Margin (%)"})
# Growth legitimately exceeds 100% (the Q3 book carries 1.08 .. 3.0), so the points heuristic
# cannot apply; an explicit "%" sign and the > percent_block_above refusal still do.
GROWTH_COLUMNS: frozenset[str] = frozenset({"ARR Growth (YoY %)"})
# Date columns, by tab.
DATE_COLUMNS: frozenset[str] = frozenset({"First Investment", "Latest Round", "Date"})
