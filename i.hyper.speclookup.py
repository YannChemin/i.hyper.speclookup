#!/usr/bin/env python
##############################################################################
# MODULE:    i.hyper.speclookup
# AUTHOR(S): Spectral Feature Extraction and Interpretation Engine
# PURPOSE:   Query and search the shared spectral library built by the
#            i.hyper.lib_* harvesters (i.hyper.lib_ecosis, i.hyper.lib_usgs,
#            i.hyper.lib_relab) -- by metadata (source, category, free text,
#            wavelength range, geographic bounds) and/or by spectral
#            similarity to a query spectrum (Spectral Angle Mapper,
#            correlation, or Euclidean distance).
# COPYRIGHT: (C) 2026 by the GRASS Development Team
# SPDX-License-Identifier: GPL-2.0-or-later
##############################################################################

# %module
# % description: Query/search the shared spectral library built by i.hyper.lib_* harvesters, by metadata and/or by spectral similarity to a query spectrum
# % keyword: imagery
# % keyword: hyperspectral
# % keyword: spectral library
# % keyword: spectral matching
# %end

# %option
# % key: library
# % type: string
# % required: no
# % description: Shared spectral library root directory (default: $HOME/grassdata/hyperspeclib, as built by i.hyper.lib_ecosis/i.hyper.lib_usgs/i.hyper.lib_relab)
# % guisection: Library
# %end

# %option
# % key: format
# % type: string
# % required: no
# % options: auto,parquet,sqlite
# % answer: auto
# % description: Storage backend to read (auto: prefer a source_database=*/ Parquet tree if present, else hyperspeclib.sqlite)
# % guisection: Library
# %end

# %option
# % key: source_database
# % type: string
# % required: no
# % multiple: yes
# % description: Restrict to specific harvested sources (e.g. ecosis,usgs_splib07,relab; default: all)
# % guisection: Filter
# %end

# %option
# % key: dataset_id
# % type: string
# % required: no
# % multiple: yes
# % description: Restrict to specific dataset_id values (EcoSIS package ID, USGS chapter, or RELAB category; default: all)
# % guisection: Filter
# %end

# %option
# % key: search
# % type: string
# % required: no
# % description: Case-insensitive free-text search against dataset_title, record_id, and extra_metadata
# % guisection: Filter
# %end

# %option
# % key: min_wavelength
# % type: double
# % required: no
# % description: Only keep records whose spectrum covers at least this wavelength (same unit as wavelength_unit, nm by default)
# % guisection: Filter
# %end

# %option
# % key: max_wavelength
# % type: double
# % required: no
# % description: Only keep records whose spectrum covers up to at least this wavelength (same unit as wavelength_unit, nm by default)
# % guisection: Filter
# %end

# %option
# % key: min_bands
# % type: integer
# % required: no
# % description: Only keep records with at least this many bands
# % guisection: Filter
# %end

# %option
# % key: max_bands
# % type: integer
# % required: no
# % description: Only keep records with at most this many bands
# % guisection: Filter
# %end

# %option
# % key: n
# % type: double
# % required: no
# % description: Geographic filter: maximum latitude (degrees; only meaningful for georeferenced records, e.g. EcoSIS)
# % guisection: Filter
# %end

# %option
# % key: s
# % type: double
# % required: no
# % description: Geographic filter: minimum latitude (degrees)
# % guisection: Filter
# %end

# %option
# % key: e
# % type: double
# % required: no
# % description: Geographic filter: maximum longitude (degrees)
# % guisection: Filter
# %end

# %option
# % key: w
# % type: double
# % required: no
# % description: Geographic filter: minimum longitude (degrees)
# % guisection: Filter
# %end

# %option
# % key: query_vector
# % type: string
# % required: no
# % description: Point vector map with one or more wl_<wavelength> attribute columns (e.g. i.hyper.endmembers output) -- switches to spectral similarity matching, one ranked result set per point
# % guisection: Query
# %end

# %option
# % key: query_csv
# % type: string
# % required: no
# % description: CSV file with wl_<wavelength> columns (e.g. i.hyper.endmembers CSV output) -- switches to spectral similarity matching, one ranked result set per row
# % guisection: Query
# %end

# %option
# % key: similarity_method
# % type: string
# % required: no
# % options: sam,correlation,euclidean
# % answer: sam
# % description: Spectral similarity metric. sam: Spectral Angle Mapper (degrees, lower=more similar). correlation: Pearson correlation over the overlapping bands (higher=more similar). euclidean: Euclidean distance (lower=more similar)
# % guisection: Query
# %end

# %option
# % key: min_overlap_bands
# % type: integer
# % required: no
# % answer: 5
# % description: Minimum number of overlapping bands required to score a candidate against the query spectrum (absolute floor)
# % guisection: Query
# %end

# %option
# % key: min_overlap_fraction
# % type: double
# % required: no
# % answer: 0.0
# % description: Minimum overlapping bands required, as a fraction (0-1) of the query spectrum's own band count -- both this and min_overlap_bands must be satisfied. An absolute floor alone does not scale: e.g. 13 overlapping bands is a weak, edge-of-range match for a 255-band hyperspectral query but would be unremarkable for a 20-band multispectral one. Default 0 (disabled) preserves the absolute-only behavior
# % guisection: Query
# %end

# %option
# % key: top_n
# % type: integer
# % required: no
# % answer: 10
# % description: Number of best matches to keep per query spectrum
# % guisection: Query
# %end

# %option
# % key: limit
# % type: integer
# % required: no
# % answer: 100
# % description: Cap on results printed/written in metadata-only mode (no query_vector/query_csv given)
# % guisection: Output
# %end

# %option
# % key: output
# % type: string
# % required: no
# % description: Write results to this CSV or JSON file (output_format)
# % guisection: Output
# %end

# %option
# % key: output_format
# % type: string
# % required: no
# % options: csv,json
# % answer: csv
# % description: Format for output
# % guisection: Output
# %end

# %flag
# % key: s
# % description: Include each matched record's full spectrum (wavelengths/values) in the output file
# % guisection: Output
# %end

from __future__ import annotations

import os
import re
import csv
import sys
import json
import math
import sqlite3
from typing import Optional

import grass.script as gs

DEFAULT_LIBRARY_ROOT = os.path.join(os.path.expanduser("~"), "grassdata", "hyperspeclib")

_LIGHT_COLUMNS = [
    "source_database", "dataset_id", "dataset_title", "record_id", "organization",
    "source_url", "source_api_url", "longitude", "latitude", "measurement_type",
    "wavelength_unit", "n_bands",
]
_FULL_COLUMNS = _LIGHT_COLUMNS + ["wavelengths", "values", "extra_metadata", "ingest_date"]

# ---------------------------------------------------------------------------
# Library backend detection and row iteration (Parquet / SQLite)
# ---------------------------------------------------------------------------


def detect_format(library_root: str, requested: str) -> str:
    has_parquet = any(
        name.startswith("source_database=")
        for name in os.listdir(library_root)
    ) if os.path.isdir(library_root) else False
    has_sqlite = os.path.isfile(os.path.join(library_root, "hyperspeclib.sqlite"))

    if requested != "auto":
        return requested
    if has_parquet:
        return "parquet"
    if has_sqlite:
        return "sqlite"
    gs.fatal(
        f"No spectral library found at {library_root} -- expected a "
        "source_database=*/ Parquet tree or hyperspeclib.sqlite, as built "
        "by i.hyper.lib_ecosis / i.hyper.lib_usgs / i.hyper.lib_relab."
    )


def _build_pyarrow_filter(source_databases, dataset_ids, min_bands, max_bands,
                          bbox, search_text):
    import pyarrow.dataset as ds
    import pyarrow.compute as pc

    expr = None

    def add(e):
        nonlocal expr
        expr = e if expr is None else (expr & e)

    if source_databases:
        add(ds.field("source_database").isin(source_databases))
    if dataset_ids:
        add(ds.field("dataset_id").isin(dataset_ids))
    if min_bands is not None:
        add(ds.field("n_bands") >= min_bands)
    if max_bands is not None:
        add(ds.field("n_bands") <= max_bands)
    if bbox.get("n") is not None:
        add(ds.field("latitude") <= bbox["n"])
    if bbox.get("s") is not None:
        add(ds.field("latitude") >= bbox["s"])
    if bbox.get("e") is not None:
        add(ds.field("longitude") <= bbox["e"])
    if bbox.get("w") is not None:
        add(ds.field("longitude") >= bbox["w"])
    if search_text:
        pattern = search_text.lower()
        text_expr = (
            pc.match_substring(pc.utf8_lower(ds.field("dataset_title")), pattern)
            | pc.match_substring(pc.utf8_lower(ds.field("record_id")), pattern)
            | pc.match_substring(pc.utf8_lower(ds.field("extra_metadata")), pattern)
        )
        add(text_expr)
    return expr


def iter_candidate_rows(library_root: str, fmt: str, columns: list[str], *,
                         source_databases=None, dataset_ids=None, search_text=None,
                         min_bands=None, max_bands=None, bbox=None):
    """Yields dict rows matching the given filters, one dataset file/table
    scanned in streaming batches at a time -- peak memory during a
    library-wide spectral match is bounded by one batch, not the whole
    (potentially 250k+ record) library."""
    bbox = bbox or {}
    if fmt == "parquet":
        import pyarrow.dataset as ds
        dataset = ds.dataset(library_root, format="parquet")  # no Hive
        # partitioning: source_database is already a real column in every
        # file, so letting pyarrow also infer it from the directory name
        # causes a dictionary-vs-string schema clash across files.
        expr = _build_pyarrow_filter(source_databases, dataset_ids, min_bands,
                                     max_bands, bbox, search_text)
        scanner = dataset.scanner(columns=columns, filter=expr)
        for batch in scanner.to_batches():
            cols = {name: batch.column(i).to_pylist() for i, name in enumerate(columns)}
            for i in range(batch.num_rows):
                yield {name: cols[name][i] for name in columns}
    else:
        db_path = os.path.join(library_root, "hyperspeclib.sqlite")
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        where, params = [], []
        if source_databases:
            where.append(f"source_database IN ({','.join('?' * len(source_databases))})")
            params.extend(source_databases)
        if dataset_ids:
            where.append(f"dataset_id IN ({','.join('?' * len(dataset_ids))})")
            params.extend(dataset_ids)
        if min_bands is not None:
            where.append("n_bands >= ?"); params.append(min_bands)
        if max_bands is not None:
            where.append("n_bands <= ?"); params.append(max_bands)
        if bbox.get("n") is not None:
            where.append("latitude <= ?"); params.append(bbox["n"])
        if bbox.get("s") is not None:
            where.append("latitude >= ?"); params.append(bbox["s"])
        if bbox.get("e") is not None:
            where.append("longitude <= ?"); params.append(bbox["e"])
        if bbox.get("w") is not None:
            where.append("longitude >= ?"); params.append(bbox["w"])
        if search_text:
            like = f"%{search_text}%"
            where.append("(dataset_title LIKE ? OR record_id LIKE ? OR extra_metadata LIKE ?)")
            params.extend([like, like, like])
        sql = f"SELECT {', '.join(_sqlite_column(c) for c in columns)} FROM spectra"
        if where:
            sql += " WHERE " + " AND ".join(where)
        cur = con.execute(sql, params)
        for row in cur:
            out = dict(zip(columns, row))
            if "wavelengths" in out and out["wavelengths"] is not None:
                out["wavelengths"] = json.loads(out["wavelengths"])
            if "values" in out and out["values"] is not None:
                out["values"] = json.loads(out["values"])
            yield out
        con.close()


def _sqlite_column(name: str) -> str:
    # values_json is the on-disk column name for the schema's "values"
    # field; the result tuple is re-keyed with our own `columns` list
    # (not sqlite's own returned names) so no SQL alias is needed here.
    return "values_json" if name == "values" else name

# ---------------------------------------------------------------------------
# Query spectrum parsing (i.hyper.endmembers-compatible wl_<wavelength> columns)
# ---------------------------------------------------------------------------

_NON_SPECTRAL_COLS = {"cat", "x", "y", "lon", "lat", "longitude", "latitude"}


def _parse_wl_colname(name: str) -> Optional[float]:
    if not name.startswith("wl_"):
        return None
    body = name[3:]
    negative = body.startswith("neg_")
    if negative:
        body = body[4:]
    parts = body.split("_")
    if len(parts) == 1:
        s = parts[0]
    elif len(parts) == 2:
        s = parts[0] + "." + parts[1]
    else:
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if negative else val


def load_query_spectra_from_csv(path: str) -> list[tuple[str, list[float], list[float]]]:
    """Returns a list of (label, wavelengths, values), one per CSV row,
    reading wl_<wavelength> columns produced by i.hyper.endmembers (or any
    other i.hyper.* module following the same naming convention)."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        wl_cols = [(c, _parse_wl_colname(c)) for c in reader.fieldnames or []]
        wl_cols = [(c, wl) for c, wl in wl_cols if wl is not None]
        if not wl_cols:
            gs.fatal(f"No wl_<wavelength> columns found in {path}.")
        queries = []
        for i, row in enumerate(reader):
            pairs = []
            for col, wl in wl_cols:
                try:
                    v = float(row[col])
                except (TypeError, ValueError):
                    continue
                pairs.append((wl, v))
            pairs.sort(key=lambda p: p[0])
            if pairs:
                queries.append((f"row{i + 1}", [p[0] for p in pairs], [p[1] for p in pairs]))
        return queries


def load_query_spectra_from_vector(map_name: str) -> list[tuple[str, list[float], list[float]]]:
    """Same as load_query_spectra_from_csv but reading a GRASS point vector
    map's attribute table (e.g. i.hyper.endmembers's vector output)."""
    result = gs.vector_db_select(map_name)
    columns = result["columns"]
    wl_cols = [(idx, name, _parse_wl_colname(name)) for idx, name in enumerate(columns)]
    wl_cols = [(idx, name, wl) for idx, name, wl in wl_cols if wl is not None]
    if not wl_cols:
        gs.fatal(f"No wl_<wavelength> attribute columns found on vector map {map_name}.")
    cat_idx = columns.index("cat") if "cat" in columns else None
    queries = []
    for cat, values in result["values"].items():
        pairs = []
        for idx, name, wl in wl_cols:
            try:
                v = float(values[idx])
            except (TypeError, ValueError, IndexError):
                continue
            pairs.append((wl, v))
        pairs.sort(key=lambda p: p[0])
        if pairs:
            label = f"cat{values[cat_idx]}" if cat_idx is not None else f"cat{cat}"
            queries.append((label, [p[0] for p in pairs], [p[1] for p in pairs]))
    return queries

# ---------------------------------------------------------------------------
# Spectral similarity (resample candidate onto the query's wavelength grid,
# restricted to the overlapping range, via linear interpolation)
# ---------------------------------------------------------------------------


def _resample_overlap(query_wl, query_val, cand_wl, cand_val, min_overlap_bands,
                      min_overlap_fraction=0.0):
    """A handful of harvested records carry a literal "NaN"/"Inf" string in
    a datapoint that Python's float() parses without raising (unlike a
    genuinely unparseable value), so it isn't caught by the harvesters'
    own parsing. np.interp silently propagates such non-finite values into
    otherwise-valid neighboring output points, and an unguarded SAM
    computation downstream can turn a NaN cosine into a bogus "perfect
    match" of exactly 0 degrees (Python's max(-1, min(1, nan)) resolves to
    1.0, not a sentinel) -- so non-finite (wavelength, value) pairs are
    dropped from the candidate here, before interpolation, same as if
    they had been unparseable to begin with."""
    import numpy as np
    cand_wl = np.asarray(cand_wl, dtype=float)
    cand_val = np.asarray(cand_val, dtype=float)
    finite = np.isfinite(cand_wl) & np.isfinite(cand_val)
    if not finite.all():
        cand_wl, cand_val = cand_wl[finite], cand_val[finite]
    if cand_wl.size < 2:
        return None
    lo, hi = cand_wl[0], cand_wl[-1]
    query_wl = np.asarray(query_wl)
    mask = (query_wl >= lo) & (query_wl <= hi)
    required = max(min_overlap_bands, int(np.ceil(min_overlap_fraction * query_wl.size)))
    if mask.sum() < required:
        return None
    qwl = np.asarray(query_wl)[mask]
    qval = np.asarray(query_val)[mask]
    cval_resampled = np.interp(qwl, cand_wl, cand_val)
    if not (np.isfinite(qval).all() and np.isfinite(cval_resampled).all()):
        return None
    return qval, cval_resampled


def _score(method, qval, cval):
    import numpy as np
    if method == "sam":
        denom = (np.linalg.norm(qval) * np.linalg.norm(cval))
        if denom == 0:
            return None
        cosang = float(np.dot(qval, cval) / denom)
        if math.isnan(cosang):
            return None
        cosang = max(-1.0, min(1.0, cosang))
        return math.degrees(math.acos(cosang))  # lower = more similar
    if method == "correlation":
        if qval.size < 2 or np.std(qval) == 0 or np.std(cval) == 0:
            return None
        corr = float(np.corrcoef(qval, cval)[0, 1])
        return None if math.isnan(corr) else corr  # higher = more similar
    if method == "euclidean":
        return float(np.linalg.norm(qval - cval))  # lower = more similar
    return None


_LOWER_IS_BETTER = {"sam": True, "correlation": False, "euclidean": True}

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _write_output(path: str, fmt: str, rows: list[dict]):
    if not rows:
        return
    if fmt == "json":
        with open(path, "w") as f:
            json.dump(rows, f, indent=2, default=str)
    else:
        fieldnames = list(rows[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(options, flags):
    library_root = options.get("library") or DEFAULT_LIBRARY_ROOT
    fmt = detect_format(library_root, options.get("format", "auto") or "auto")

    source_databases = [s for s in (options.get("source_database", "") or "").split(",") if s] or None
    dataset_ids = [s for s in (options.get("dataset_id", "") or "").split(",") if s] or None
    search_text = options.get("search") or None
    min_bands = int(options["min_bands"]) if options.get("min_bands") else None
    max_bands = int(options["max_bands"]) if options.get("max_bands") else None
    min_wavelength = float(options["min_wavelength"]) if options.get("min_wavelength") else None
    max_wavelength = float(options["max_wavelength"]) if options.get("max_wavelength") else None
    bbox = {k: float(options[k]) for k in ("n", "s", "e", "w") if options.get(k)}
    limit = int(options.get("limit", "100") or "100")

    query_vector = options.get("query_vector")
    query_csv = options.get("query_csv")
    similarity_method = options.get("similarity_method", "sam") or "sam"
    min_overlap_bands = int(options.get("min_overlap_bands", "5") or "5")
    min_overlap_fraction = float(options.get("min_overlap_fraction", "0.0") or "0.0")
    top_n = int(options.get("top_n", "10") or "10")

    output = options.get("output")
    output_format = options.get("output_format", "csv") or "csv"
    include_spectra = flags["s"]

    gs.message(f"Library: {library_root} (format={fmt})")

    queries = []
    if query_vector:
        queries.extend(load_query_spectra_from_vector(query_vector))
    if query_csv:
        queries.extend(load_query_spectra_from_csv(query_csv))

    common_kwargs = dict(
        source_databases=source_databases, dataset_ids=dataset_ids,
        search_text=search_text, min_bands=min_bands, max_bands=max_bands, bbox=bbox,
    )

    if not queries:
        # --- Metadata-only search ------------------------------------------
        gs.message("Searching library metadata…")
        needs_wl_check = min_wavelength is not None or max_wavelength is not None
        base_columns = _FULL_COLUMNS if include_spectra else _LIGHT_COLUMNS
        scan_columns = base_columns if ("wavelengths" in base_columns or not needs_wl_check) \
            else base_columns + ["wavelengths"]

        results = []
        for row in iter_candidate_rows(library_root, fmt, scan_columns, **common_kwargs):
            if needs_wl_check:
                wl = row.get("wavelengths")
                if not wl:
                    continue
                if min_wavelength is not None and wl[0] > min_wavelength:
                    continue
                if max_wavelength is not None and wl[-1] < max_wavelength:
                    continue
                if "wavelengths" not in base_columns:
                    row = {k: v for k, v in row.items() if k != "wavelengths"}
            results.append(row)
            if len(results) >= limit:
                break
        gs.message(f"{len(results)} matching record(s) (limit={limit}).")
        for r in results[:min(limit, 50)]:
            gs.message(
                f"[{r['source_database']}/{r['dataset_id']}] {r['record_id']}: "
                f"{r['dataset_title']} ({r['n_bands']} bands, {r['wavelength_unit']})"
            )
        if output:
            _write_output(output, output_format, results)
            gs.message(f"Wrote {len(results)} record(s) → {output}")
        return

    # --- Spectral similarity matching ---------------------------------------
    gs.message(f"Matching {len(queries)} query spectrum/spectra against the library "
              f"(method={similarity_method})…")
    lower_better = _LOWER_IS_BETTER[similarity_method]
    best: dict[str, list[tuple[float, dict]]] = {label: [] for label, _, _ in queries}

    n_scanned = 0
    for row in iter_candidate_rows(library_root, fmt, _FULL_COLUMNS, **common_kwargs):
        n_scanned += 1
        cand_wl, cand_val = row.get("wavelengths"), row.get("values")
        if not cand_wl or not cand_val:
            continue
        if min_wavelength is not None and (cand_wl[0] > min_wavelength):
            continue
        if max_wavelength is not None and (cand_wl[-1] < max_wavelength):
            continue
        for label, qwl, qval in queries:
            resampled = _resample_overlap(qwl, qval, cand_wl, cand_val, min_overlap_bands,
                                          min_overlap_fraction)
            if resampled is None:
                continue
            qv, cv = resampled
            score = _score(similarity_method, qv, cv)
            if score is None:
                continue
            heap = best[label]
            heap.append((score, {
                "query": label, "source_database": row["source_database"],
                "dataset_id": row["dataset_id"], "dataset_title": row["dataset_title"],
                "record_id": row["record_id"], "organization": row["organization"],
                "n_bands": row["n_bands"], "n_overlap_bands": int(qv.size),
                "similarity_method": similarity_method, "score": round(score, 6),
                "extra_metadata": row.get("extra_metadata"),
                **({"wavelengths": cand_wl, "values": cand_val} if include_spectra else {}),
            }))
            heap.sort(key=lambda t: t[0], reverse=not lower_better)
            del heap[top_n:]

    gs.message(f"Scanned {n_scanned} candidate record(s).")

    all_rows = []
    for label, _, _ in queries:
        gs.message(f"Top {min(top_n, len(best[label]))} match(es) for '{label}':")
        for rank, (score, r) in enumerate(best[label], start=1):
            gs.message(
                f"  {rank}. [{r['source_database']}/{r['dataset_id']}] {r['record_id']} "
                f"({r['dataset_title']}) -- {similarity_method}={r['score']} "
                f"({r['n_overlap_bands']} overlapping bands)"
            )
            all_rows.append({"rank": rank, **r})

    if output:
        _write_output(output, output_format, all_rows)
        gs.message(f"Wrote {len(all_rows)} match(es) → {output}")


if __name__ == "__main__":
    options, flags = gs.parser()
    sys.exit(main(options, flags))
