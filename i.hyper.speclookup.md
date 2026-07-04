# i.hyper.speclookup

## NAME

*i.hyper.speclookup* - Query and search the shared spectral library built
by the *i.hyper.lib_\** harvesters, by metadata and/or by spectral
similarity to a query spectrum.

## SYNOPSIS

**i.hyper.speclookup**
[**library**=*string*] [**format**=*string*]
[**source_database**=*string*[,*string*,...]]
[**dataset_id**=*string*[,*string*,...]] [**search**=*string*]
[**min_wavelength**=*value*] [**max_wavelength**=*value*]
[**min_bands**=*value*] [**max_bands**=*value*]
[**n**=*value*] [**s**=*value*] [**e**=*value*] [**w**=*value*]
[**query_vector**=*name*] [**query_csv**=*string*]
[**similarity_method**=*string*] [**min_overlap_bands**=*value*]
[**min_overlap_fraction**=*value*] [**top_n**=*value*] [**limit**=*value*]
[**output**=*string*] [**output_format**=*string*] [**-s**]

## DESCRIPTION

*i.hyper.speclookup* is the query-side counterpart to the *i.hyper.lib_\**
harvester family (*i.hyper.lib_ecosis*, *i.hyper.lib_usgs*,
*i.hyper.lib_relab*): it reads the shared spectral library those modules
build at `$HOME/grassdata/hyperspeclib` and answers two kinds of question
against it, in one module because they share the same filtering and
library-reading machinery:

1. **Metadata search** -- "what's in the library matching these
   criteria?" (source, category, free text, wavelength coverage, band
   count, geographic bounds). No query spectrum needed.
2. **Spectral similarity matching** -- "what in the library looks most
   like *this* spectrum?" -- given one or more query spectra (from a
   vector map or CSV, in the same `wl_<wavelength>` column convention
   *i.hyper.endmembers* writes), ranks every matching library record by
   Spectral Angle Mapper, Pearson correlation, or Euclidean distance and
   returns the best **top_n** per query spectrum.

Both modes work identically regardless of whether the library was built
with `format=parquet` or `format=sqlite`, and regardless of which
harvester(s) populated it -- **format=auto** (default) detects which
backend is present.

### Filtering (applies to both modes)

- **source_database=**, **dataset_id=**: restrict to specific harvested
  sources (`ecosis`, `usgs_splib07`, `relab`, or any future
  `i.hyper.lib_*` source) and/or specific dataset groupings (an EcoSIS
  package ID, a USGS chapter, or a RELAB `GeneralType1` category).
- **search=**: case-insensitive substring match against `dataset_title`,
  `record_id`, and the full `extra_metadata` JSON blob -- so it also
  matches on fields nested in per-source metadata (e.g. a USGS mineral's
  `mineral_type` classification group), not just the primary name.
- **min_wavelength=**/**max_wavelength=**: keep only records whose own
  spectrum's wavelength range covers at least the requested bound (i.e.
  the record's first wavelength is at or below **min_wavelength** and its
  last wavelength is at or above **max_wavelength**) -- useful for e.g.
  "must include the SWIR" without caring exactly how many bands.
- **min_bands=**/**max_bands=**: restrict by band count.
- **n=**/**s=**/**e=**/**w=**: geographic bounding box on
  latitude/longitude (degrees) -- only meaningful for georeferenced
  records (chiefly EcoSIS field spectra; USGS and RELAB lab samples have
  no coordinates and are simply excluded by any bbox filter).

All filters combine with AND. Parquet-backed filters (source_database,
dataset_id, band count, bbox, free text) are pushed down into the scan
itself (`pyarrow.dataset` predicate pushdown / SQLite `WHERE`); the
wavelength-coverage filter is applied just after, per candidate row, since
coverage is derived from the `wavelengths` array rather than a plain
scalar column.

### Metadata search mode (no query_vector/query_csv given)

Scans the library with the given filters, printing up to **limit**
matches (source/category/record ID/title/band count) and, if
**output=** is given, writing the same (lightweight, no spectra by
default) rows to CSV or JSON. Add **-s** to include each matched record's
full `wavelengths`/`values` arrays in the output file too.

### Spectral similarity matching mode

Triggered by **query_vector=** (a GRASS point vector map, e.g.
*i.hyper.endmembers*'s vector output) and/or **query_csv=** (a CSV file,
e.g. *i.hyper.endmembers*'s CSV output) -- both read `wl_<wavelength>`
attribute/column names (the exact naming convention
*i.hyper.endmembers* writes: `wl_2265_19` for 2265.19, `wl_neg_5_2` for
-5.2) and treat each row/point as one independent query spectrum.

For every candidate library record (after the filters above), the
record's own spectrum is linearly interpolated (`numpy.interp`) onto the
query spectrum's wavelength grid, restricted to the wavelengths actually
**overlapping** the candidate's own native range (no extrapolation) --
candidates with fewer overlapping points than *either* **min_overlap_bands**
(default 5, an absolute floor) or **min_overlap_fraction** (default 0,
disabled) are skipped as not comparable. An absolute floor alone does not
scale: 13 overlapping bands is a weak, edge-of-range match for a
255-band hyperspectral query (e.g. some USGS NIC4/Nicolet mineral records
are only measured from ~2400nm onward, overlapping a typical VNIR/SWIR
scene in just a narrow sliver at its very end) but would be unremarkable
for a 20-band multispectral one -- **min_overlap_fraction** expresses the
requirement relative to the query's own band count instead (e.g. 0.15 =
at least 15% of the query's bands must be covered), and both thresholds
apply together when set. The resampled pair is then scored by
**similarity_method**:

- **sam** (default): Spectral Angle Mapper, the angle in degrees between
  the two spectra as vectors -- 0 is an exact match, lower is more
  similar. Insensitive to a uniform brightness/albedo scaling difference
  between query and candidate, which is usually desirable when comparing
  a real scene pixel against a clean lab/library reference.
- **correlation**: Pearson correlation coefficient over the overlapping
  bands -- 1.0 is a perfect match, higher is more similar.
- **euclidean**: Euclidean distance -- 0 is an exact match, lower is more
  similar. Sensitive to absolute brightness differences (unlike SAM), so
  best when query and candidate are already on a comparable scale.

The **top_n** best-scoring candidates per query spectrum are printed and,
if **output=** is given, written to CSV or JSON (one row per (query, rank)
pair, with **-s** again controlling whether the matched spectra themselves
are included).

### Performance

The whole matching scan streams the library in batches (bounded memory
regardless of how many candidates match, the same batching discipline the
harvesters use when writing), so narrowing with **source_database=**/
**dataset_id=** mainly saves *time*, not memory -- matching one query
spectrum against all ~2,450 USGS splib07a records takes a few seconds;
matching against the full ~266,000-record library (no source/category
filter) will scan proportionally longer. Filter to the source(s) most
likely to contain what you're looking for when you can.

## NOTES

**query_vector** and **query_csv** can both be given at once -- their
query spectra are simply concatenated (each still matched and ranked
independently).

A CSV or vector map's non-`wl_*` columns (`cat`, `x`/`y`, `lon`/`lat`) are
ignored for matching purposes; they exist only to identify each query
point (used to label its result set) or for downstream reprojection in
whichever module produced them.

## EXAMPLES

### Metadata search: free text, restricted to one source

```sh
i.hyper.speclookup search=Kaolinite source_database=usgs_splib07 limit=5
```

```text
Library: /home/yann/grassdata/hyperspeclib (format=parquet)
Searching library metadata…
10 matching record(s) (limit=5).
[usgs_splib07/ChapterM_Minerals] splib07a_Antigorite_NMNH17958_BECKb_AREF: Minerals (476 bands, nm)
...
```

Note that `search=Kaolinite` also matches *Antigorite* here -- USGS's own
metadata classifies it under the "Kaolinite-Serpentine group" mineral
family, and `search=` matches the full `extra_metadata` text, not just the
primary sample name. Add `dataset_id=ChapterM_Minerals` to also restrict
by chapter, or tighten `search=` to a more specific phrase if only the
exact mineral name is wanted.

### Metadata search with geographic + wavelength filters, JSON output

```sh
i.hyper.speclookup source_database=ecosis n=40 s=30 e=-100 w=-125 \
    min_wavelength=400 max_wavelength=2400 limit=5 \
    output=matches.json output_format=json
```

```text
Library: /home/yann/grassdata/hyperspeclib (format=parquet)
Searching library metadata…
5 matching record(s) (limit=5).
[ecosis/0c23c6f5-6fdc-48a7-8977-40354c9f948d] 676479c0cc8e84e775975af7:
Fresh Leaf Spectra and Measured Traits from the Sierra Nevada (CA) in July 2023 (2151 bands, nm)
...
Wrote 5 record(s) → matches.json
```

### Spectral similarity matching against a query CSV

Given a query CSV in *i.hyper.endmembers*'s own wide format (first two
columns are coordinates, the rest are `wl_<wavelength>` reflectance
values -- here built from a resampled real USGS Kaolinite spectrum, as a
verification case):

```sh
i.hyper.speclookup query_csv=query_kaolinite.csv \
    source_database=usgs_splib07 dataset_id=ChapterM_Minerals top_n=3
```

```text
Library: /home/yann/grassdata/hyperspeclib (format=parquet)
Matching 1 query spectrum/spectra against the library (method=sam)…
Scanned 1276 candidate record(s).
Top 3 match(es) for 'row1':
  1. [usgs_splib07/ChapterM_Minerals] splib07a_Kaolinite_CM5_BECKb_AREF (Minerals) -- sam=2e-06 (96 overlapping bands)
  2. [usgs_splib07/ChapterM_Minerals] splib07a_Kaolinite_CM3_BECKa_AREF (Minerals) -- sam=0.80745 (96 overlapping bands)
  3. [usgs_splib07/ChapterM_Minerals] splib07a_Kaolinite_GDS11_lt63um_BECKb_AREF (Minerals) -- sam=0.845591 (94 overlapping bands)
```

The query spectrum *is* (a coarsened resample of) `Kaolinite_CM5`'s own
real spectrum, and it correctly comes back as the top match at
`sam=2e-06` degrees (floating-point-level agreement) -- with the next two
matches being other real Kaolinite specimens in the library, confirming
both the resampling/overlap logic and that SAM correctly favors
genuinely similar mineralogy over unrelated samples.

### Same query, against a vector map instead, with full-spectra CSV output

```sh
v.in.ascii input=query_kaolinite.txt output=query_pts \
    columns="x double precision, y double precision, wl_221_1 double precision, ..." \
    separator=pipe x=1 y=2
i.hyper.speclookup query_vector=query_pts source_database=usgs_splib07 \
    dataset_id=ChapterM_Minerals top_n=3 output=matches.csv -s
```

```text
Matching 1 query spectrum/spectra against the library (method=sam)…
Scanned 1276 candidate record(s).
Top 3 match(es) for 'cat1':
  1. [usgs_splib07/ChapterM_Minerals] splib07a_Kaolinite_CM5_BECKb_AREF (Minerals) -- sam=2e-06 (96 overlapping bands)
  ...
Wrote 3 match(es) → matches.csv
```

`matches.csv` includes each match's rank, similarity score, full
`extra_metadata` (mineral name, formula, locality, ...), and -- because
of **-s** -- the matched record's own `wavelengths`/`values` arrays, ready
for direct overplotting against the query spectrum.

### Comparing the similarity methods on the same query

```sh
i.hyper.speclookup query_csv=query_kaolinite.csv source_database=usgs_splib07 \
    dataset_id=ChapterM_Minerals top_n=1 similarity_method=correlation
i.hyper.speclookup query_csv=query_kaolinite.csv source_database=usgs_splib07 \
    dataset_id=ChapterM_Minerals top_n=1 similarity_method=euclidean
```

```text
1. ... splib07a_Kaolinite_CM5_BECKb_AREF (Minerals) -- correlation=1.0 (96 overlapping bands)
1. ... splib07a_Kaolinite_CM5_BECKb_AREF (Minerals) -- euclidean=0.0 (96 overlapping bands)
```

All three metrics agree on the exact match, as expected; they differ in
how sharply they penalize partial mismatches among the runners-up (SAM
and correlation are shape-sensitive and albedo-tolerant, Euclidean is
not).

## SEE ALSO

*[i.hyper.lib_ecosis](i.hyper.lib_ecosis.md),
[i.hyper.lib_usgs](i.hyper.lib_usgs.md),
[i.hyper.lib_relab](i.hyper.lib_relab.md),
[i.hyper.endmembers](i.hyper.endmembers.md),
[i.hyper.spectroscopy](i.hyper.spectroscopy.md)*

## AUTHOR

Spectral Feature Extraction and Interpretation Engine
