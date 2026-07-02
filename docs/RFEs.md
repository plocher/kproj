# kproj RFEs / Parking Lot
Loosely-held future ideas and requests that are not yet fleshed out enough to
be GitHub issues. Promote an entry to a `plocher/kproj` issue once it is
concrete enough to act on. Append new ideas at the bottom.
## Clean project/version deletion (unpublish / prune)
kproj is add/update-only: it regenerates and republishes, but never removes
site content when its source goes away. There is no clean way to unpublish a
whole project or a single version, and the Make-style "regenerate only what is
stale" rule is add-only, so a stale copy is never pruned when its source
disappears (e.g. a datasheet PDF removed from the project still leaves any
site-side copy behind).
Wants: an "audit and fix" mode that reconciles the site against the current
project state (remove orphaned versions / assets / datasheets), plus explicit
"delete one version" vs "delete the whole project" semantics. Generalises the
PRD out-of-scope note on retroactive unpublishing (Story 7).
## iBOM datasheet column (per-RefDes PDF links)
jBOM can emit a BOM.csv carrying RefDes + datasheet links, and iBOM renders an
annotated BOM, so it should be possible to add a datasheet column to the iBOM
HTML that links each part to its PDF.
Benefit: this moves datasheets from a single project-global "Documentation"
list into the per-version BOM table (where the part context already lives)
WITHOUT requiring per-version copies of the PDF files themselves. It could also
simplify the project `_index.md` front-matter, since datasheets would no longer
need to be a top-level project-global list.
