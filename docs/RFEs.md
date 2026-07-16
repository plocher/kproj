# kproj RFEs / Parking Lot
Loosely-held future ideas and requests that are not yet fleshed out enough to
be GitHub issues. Promote an entry to a `plocher/kproj` issue once it is
concrete enough to act on. Append new ideas at the bottom.
## Site reconciliation audit-and-fix mode
Core delete semantics are now implemented (`kproj project --list`, `kproj delete
<project> --version <rev>`, and `kproj delete <project> --force`), but kproj
still does not run a full reconciliation pass that detects and prunes all
orphaned site content automatically.
Future want: an "audit and fix" mode that compares current project/source state
to published site state and proposes/removes drifted artifacts in bulk (for
example orphaned assets no longer referenced by any published version).
## iBOM datasheet column (per-RefDes PDF links)
jBOM can emit a BOM.csv carrying RefDes + datasheet links, and iBOM renders an
annotated BOM, so it should be possible to add a datasheet column to the iBOM
HTML that links each part to its PDF.
Benefit: this moves datasheets from a single project-global "Documentation"
list into the per-version BOM table (where the part context already lives)
WITHOUT requiring per-version copies of the PDF files themselves. It could also
simplify the project `_index.md` front-matter, since datasheets would no longer
need to be a top-level project-global list.
