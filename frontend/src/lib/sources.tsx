// Cell provenance for the detail panel: turns an input name into `'Q3 2026 Activity'!E18`.
//
// Everything here degrades to `null` rather than guessing. A reference that points at the
// wrong cell is worse than no reference at all, so an unknown input name, a missing column
// letter or an unknown row all return nothing and the UI shows the value on its own.
//
// The Queue never uses any of this — provenance belongs in the detail panel.
import { createContext, useContext, type ReactNode } from "react";
import type { Sources } from "../types";

const SourcesCtx = createContext<Sources | undefined>(undefined);

export function SourcesProvider({ value, children }: { value?: Sources; children: ReactNode }) {
  return <SourcesCtx.Provider value={value}>{children}</SourcesCtx.Provider>;
}

/** undefined when the run was loaded without provenance — every caller must tolerate it. */
export function useSources(): Sources | undefined {
  return useContext(SourcesCtx);
}

/** Excel quotes a sheet name that is not a bare identifier; an apostrophe doubles. */
export function sheetToken(sheet: string): string {
  return /^[A-Za-z_][A-Za-z0-9_.]*$/.test(sheet) ? sheet : `'${sheet.replace(/'/g, "''")}'`;
}

/** `'Q3 2026 Activity'!E18` */
export function cellRef(sheet: string, letter: string, row: number): string {
  return `${sheetToken(sheet)}!${letter}${row}`;
}

/** `'Q3 2026 Activity'!18` — a whole row, used when citing an event. */
export function rowRef(sheet: string, row: number): string {
  // Anchor on column A: "'Q3 2026 Activity'!18" is not a reference Excel accepts, so a row
  // citation nobody can paste would be worse than none.
  return `${sheetToken(sheet)}!A${row}`;
}

/** The row an event was read from, as a reference; null if we cannot name the sheet. */
export function eventRowRef(s: Sources | undefined, row: number | null | undefined): string | null {
  if (!s || row === null || row === undefined) return null;
  const sheet = s.sheets?.activity;
  return sheet ? rowRef(sheet, row) : null;
}

/** The portfolio row this company was read from, as a reference. */
export function portfolioRowRef(s: Sources | undefined, company: string): string | null {
  if (!s) return null;
  const row = s.companies?.[company]?.portfolio_row;
  const sheet = s.sheets?.portfolio;
  const letter = s.columns?.portfolio?.["Company"];
  if (!sheet || !letter || row === null || row === undefined) return null;
  return cellRef(sheet, letter, row);
}

/**
 * The cell a named step input was read from.
 * Activity-side inputs need the event row from `step.evidence.row_index`; portfolio-side
 * inputs use the company's row. Names absent from `input_columns` are engine-computed and
 * deliberately have no cell.
 */
export function inputRef(
  s: Sources | undefined,
  key: string,
  company: string,
  eventRow: number | null | undefined,
): { ref: string; column: string } | null {
  if (!s) return null;
  const spec = s.input_columns?.[key];
  if (!spec) return null;
  const sheet = s.sheets?.[spec.sheet];
  const letter = s.columns?.[spec.sheet]?.[spec.column];
  if (!sheet || !letter) return null;
  const row = spec.sheet === "activity" ? eventRow : s.companies?.[company]?.portfolio_row;
  if (row === null || row === undefined) return null;
  return { ref: cellRef(sheet, letter, row), column: spec.column };
}
