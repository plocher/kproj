# KiCad Metadata Field Survey — Phase 1
**Agent:** `survey-kicad-fields` (Phase 1 ingestion researcher)
**Corpus root:** `/Users/jplocher/Dropbox/KiCad/projects/`
**Workspace:** `/tmp/kproj-phase1/survey-kicad-fields/`
**Intermediate artifacts:** `survey.json`, `survey.csv`, `analysis.json` (machine‑friendly, re‑greppable)

## 1. Executive Summary
- **Corpus**: 34 `*.kicad_pro` projects found; 10 sit under the `MRCS/` subtree (the representative cohort, including the Phase 7 target `cpNode-Xiao-68x90`).
- **Population rates against the front‑matter contract** (consensus = either `.kicad_sch` *or* `.kicad_pcb` populated; 34 projects):
  - `title` 19/34 (56%), `company` 19/34 (56%), `rev` 19/34 (56%), `date` 20/34 (59%)
  - `comment1` 15/34 (44%) — designer slot
  - `comment2` 11/34 (32%) — tagline slot
  - `comment3` 6/34 (18%) — overview‑continuation slot
  - `comment4` 3/34 (9%) — all of these are KiCad default template noise (`Sheet Title Line 3`, `cpNode Xiao`), not real data; `comment5..9` are 0/34.
- **`text_variables` is empty in every single project (34/34).** There is no `STATUS` (or any other) text variable populated anywhere in the corpus. The contract's `STATUS` source does **not** exist yet — kproj must either invent the convention or rely on a non‑KiCad source.
- **SPCoast COMMENT1/2/3 convention verdict: holds where populated, but populated only on a minority of projects.** Of the 15 projects with `comment1`, 11 are clear designer names (`John Plocher` / `JPlocher`), 4 are partial/template (`Designer Name`, `Cambria`). Of the 11 with `comment2`, 9 read as taglines. Of the 6 with `comment3`, all six read as overview continuations.
- **`${ISSUE_DATE}` format is heterogeneous and frequently dirty.** The PCB title block already uses `YYYY.MM` (11×) — the target contract format — while the SCH side prefers `YYYY-MM-DD` (12×). 8 values are unusable junk (literal `DATE`, `Fab Date`, `2024,09`, KiCad's default French string `sam. 04 avril 2015`).
- **SCH vs PCB diverge in 18 of 34 projects.** PCB title blocks tend to carry the release‑ready values (short canonical title, `YYYY.MM` date, MRCS company); SCH side tends to carry design‑time / human‑readable values. Any kproj reader needs an explicit precedence rule.
- **Recommendation summary for the architect:**
  - Treat all six contract fields as *fallback‑required*: a `release.yaml` sidecar (or per‑step CLI override) is mandatory until the corpus is cleaned up.
  - Default precedence: prefer `.kicad_pcb` title block, fall back to `.kicad_sch`, fall back to `release.yaml`/sidecar.
  - Lock `STATUS` to a sidecar source for Phase 6 — there is no in‑KiCad evidence to mine.
  - Normalize date to `YYYY.MM` in code; reject placeholder strings (`DATE`, `Fab Date`, anything non‑numeric).

## 2. Corpus Enumeration
Full list of 34 projects (sorted by file path). `MRCS` subtree is the representative sample called out separately. `(no SCH)` / `(no PCB)` flags files that are missing a sibling.

### Non‑MRCS (24 projects)
- `AltmillSwitchController/AltmillSwitchController.kicad_pro` (no PCB)
- `AltmillSwitchRemote/AltmillSwitchRemote.kicad_pro` (no PCB)
- `Brakeman-BLUE/Brakeman.kicad_pro`
- `Brakeman-RED/Brakeman.kicad_pro`
- `Core-ESP32/Core-ESP32.kicad_pro` (no SCH, no PCB — only `.kicad_pro` present)
- `Core-ESP32-Devkit/Core-ESP32.kicad_pro`
- `Core-wt32-eth0/Core-wt32-eth0.kicad_pro`
- `IOB-Baseboard/IOB-Baseboard.kicad_pro` (no SCH, no PCB)
- `IOX-Darlington/IOX-Darlington/IOX-Darlington/IOX-Darlington.kicad_pro` *(nested duplicate of the MRCS one)*
- `LEDStripDriver/I2C-LEDStripDriver.kicad_pro` (no SCH, no PCB)
- `LightDimmer/LightAdapter-6p6c/LightAdapter.kicad_pro` (no SCH, no PCB)
- `LightDimmer/LightAdapter-8p8c/LightAdapter.kicad_pro` (no SCH, no PCB)
- `LightDimmer/LightDimmer-v1/LightDimmer.kicad_pro` (no PCB)
- `LightDimmer/LightDimmer-v1B/LightDimmer.kicad_pro` (no PCB)
- `OneOfAll/Untitled/Untitled.kicad_pro` (no SCH, no PCB)
- `OneOfAll/allSPCoast-test/allSPCoast-test.kicad_pro` (no SCH, no PCB)
- `Signal-ColorLight-Dual/SignalMast-ColorLight-DualHead.kicad_pro`
- `Signal-ColorLight-Dwarf/SignalMast-ColorLight-Dwarf.kicad_pro`
- `Signal-ColorLight-Single/SignalMast-ColorLight-SingleHead.kicad_pro` (no SCH, no PCB)
- `cpNode-expander-23017/cpNode-expander-23017/cpNode-expander-23017/cpNode-expander-23017.kicad_pro` *(nested duplicate of the MRCS one; uses KiCad defaults)*
- `cpOD/cpOD.kicad_pro` (no SCH, no PCB)
- `cpOD-updated/cpOD.kicad_pro` (no SCH, no PCB)
- `templates/empty_project/empty/empty.kicad_pro` (no SCH, no PCB) — clearly a template skeleton
- `zzz/zzz/zzz.kicad_pro` — junk scratch project; date is KiCad's French default

### MRCS subtree (10 projects — representative sample)
- `MRCS/IOX-Darlington/IOX-Darlington.kicad_pro`
- `MRCS/IOX_Blank/IOX_Blank.kicad_pro`
- `MRCS/IOX_Monitor/IOX_Monitor.kicad_pro`
- `MRCS/IOX_Plugin_Footprint/IOX_Plugin_Footprint.kicad_pro`
- `MRCS/cpNode-ProMini/cpNode-ProMini.kicad_pro` (no SCH, no PCB)
- `MRCS/cpNode-Xiao-68x90/cpNode-Xiao-68x90.kicad_pro` **← Phase 7 target**
- `MRCS/cpNode-Xiao-80x70/cpNode-Xiao-80x70.kicad_pro`
- `MRCS/cpNode-Xiao-orig/cpNode-Xiao.kicad_pro` (no SCH, no PCB)
- `MRCS/cpNode-expander-23017/cpNode-expander-23017.kicad_pro`
- `MRCS/testfoot/testfoot.kicad_pro` (no SCH, no PCB)

Note: 12 of the 34 projects have *neither* a `.kicad_sch` nor `.kicad_pcb`. They are scaffolding (`OneOfAll/Untitled`, `templates/empty_project`, `cpOD`, `cpOD-updated`, `LightAdapter-*`, `IOB-Baseboard`, `I2C-LEDStripDriver`, `Core-ESP32` outside Devkit, MRCS `cpNode-ProMini`, MRCS `cpNode-Xiao-orig`, MRCS `testfoot`). Population denominators below include these because `kproj` will be invoked against them eventually.

## 3. Population Matrix
One row per project; `⚠` flags a sch≠pcb disagreement (`SCH=<x> / PCB=<y>` summary shown). `(empty)` means neither side carries a value. MRCS rows appear after the separator.

### Non‑MRCS

```
project                              title                          company             rev        date                       comment1                    comment2                   comment3
AltmillSwitchController              Altmill Remote Power Sequencer SPCoast             A          2025-12-03                  (empty)                     (empty)                    (empty)
AltmillSwitchRemote                  Altmill Power - Remote         SPCoast             A          2025-12-03                  (empty)                     (empty)                    (empty)
Brakeman (BLUE)                      Safety Sam the Brakeman        SPCoast / MRCS      A          ⚠ SCH='2024,09' / PCB='2024.09' (empty)                 (empty)                    (empty)
Brakeman (RED)                       Safety Sam the Brakeman        SPCoast / MRCS      A          ⚠ SCH='2024,09' / PCB='2024.09' (empty)                 (empty)                    (empty)
Core-ESP32 (top-level)               (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
Core-ESP32-Devkit/Core-ESP32         ⚠ SCH='I/O & I2C Adapter for ESP32-DEV' / PCB='Core-ESP32-DEV'  SPCoast             ⚠ 3.0/3.2  ⚠ 2026-04-06 / 2026.04   John Plocher                ⚠ SCH=tagline / PCB=(empty) ⚠ SCH=overview / PCB=(empty)
Core-wt32-eth0                       ⚠ SCH='WT32-ETH01 Processor' / PCB='Plexi Core'  FoMoCo              ⚠ 1.0/v1.0B ⚠ 2024-11-17 / 2024.11 ⚠ SCH='John Plocher' / PCB='Cambria' Cambria  (empty)
IOB-Baseboard                        (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
IOX-Darlington (nested duplicate)    ${PROJECTNAME}                 MRCS                ⚠ 1.0/A   ⚠ SCH='DATE' / PCB='Fab Date'  Designer Name              Sheet Title Line 1          Sheet Title Line 2  (comment4='Sheet Title Line 3')
I2C-LEDStripDriver                   (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
LightAdapter-6p6c                    (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
LightAdapter-8p8c                    (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
LightDimmer-v1 (sch only)            Light Dimmer                   SPCoast             1.0        2025-01-20                  John Plocher                (empty)                    (empty)
LightDimmer-v1B (sch only)           Light Dimmer                   SPCoast             1.0        2025-01-20                  John Plocher                (empty)                    (empty)
Untitled                             (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
allSPCoast-test                      (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
Signal-ColorLight-DualHead           ⚠ SCH='Simple Signal - Dual Head Color Light' / PCB='Signalmast-ColorLight-DualHead'  SPCoast    2.0    ⚠ 2025-04-07 / 2025-04-06  ⚠ SCH='JPlocher' / PCB='John Plocher'  Panel by JLC, White Silk with Black Soldermask  (empty)
Signal-ColorLight-Dwarf              Low Cost Signal Mast - single  MRCS / SPCoast      ⚠ 1.0/1.0-A  2024-09-14                JPlocher                    Fabrication Drawing        (empty)
Signal-ColorLight-Single             (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
cpNode-expander-23017 (nested dup)   ${PROJECTNAME}                 MRCS                ⚠ 1.0/A   ⚠ SCH='DATE' / PCB='Fab Date'  Designer Name              Sheet Title Line 1          Sheet Title Line 2  (comment4='Sheet Title Line 3')
cpOD                                 (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
cpOD (cpOD-updated)                  (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
empty (templates)                    (empty)                        (empty)             (empty)    (empty)                     (empty)                     (empty)                    (empty)
zzz                                  (empty)                        (empty)             (empty)    sam. 04 avril 2015         (empty)                     (empty)                    (empty)
```

### MRCS subtree (representative cohort)

```
project                              title                          company             rev        date                       comment1                    comment2                                            comment3
IOX-Darlington                       ULN2003 Driver (PCB only)      MRCS (PCB only)     1.0A (PCB) 2026.07 (PCB)              John Plocher (PCB)         (empty)                                             (empty)
IOX_Blank                            IOX Blank Plugin (PCB only)    MRCS (PCB only)     1.0A (PCB) 2026.07 (PCB)              John Plocher (PCB)         (empty)                                             (empty)
IOX_Monitor                          ⚠ SCH='cpNode IOX Monitor' / PCB='IOX-Monitor'  MRCS    ⚠ 1.0/1.0A  2026-07               John Plocher              ⚠ SCH='IOX Plugin' / PCB=(empty)                    (empty)
IOX_Plugin_Footprint                 ⚠ SCH='IOX Plugin footprint' / PCB='IOX Blank Plugin'  MRCS  1.0A  2026.07                John Plocher              ⚠ SCH='PCB Layout for daughterboard connectors' / PCB=(empty)  (empty)
cpNode-ProMini                       (empty)                        (empty)             (empty)    (empty)                     (empty)                    (empty)                                             (empty)
cpNode-Xiao-68x90  ★Phase 7 target★  ⚠ SCH='cpNode Xiao' / PCB='cpNode-Xiao-68x90'  ⚠ SCH='SPCoast' / PCB='MRCS' ⚠ 3.0/1.0B ⚠ 2026-04-06 / 2026.05  John Plocher  ⚠ SCH='Breaks out 5v I2C, IO4 style headers and I2C OLED Display' / PCB=(empty)  ⚠ SCH='Processor carrier board for ESP32-DEV' / PCB=(empty)
cpNode-Xiao-80x70                    ⚠ SCH='cpNode Xiao' / PCB='cpNode-Xiao-80x70'  ⚠ SCH='SPCoast' / PCB='MRCS'  ⚠ 3.0/1.0  ⚠ 2026-04-06 / 2026.04  John Plocher  ⚠ SCH='Breaks out 5v I2C, IO4 style headers and I2C OLED Display' / PCB=(empty)  ⚠ SCH='Processor carrier board for ESP32-DEV' / PCB=(empty)
cpNode-Xiao-orig (`cpNode-Xiao`)    (empty)                        (empty)             (empty)    (empty)                     (empty)                    (empty)                                             (empty)
cpNode-expander-23017                ${PROJECTNAME}                 MRCS                ⚠ 3.0/3.0A ⚠ 2026-07 / 2026.06        John Plocher              IOX-16                                              Updated for use with  (comment4='cpNode Xiao')
testfoot                             (empty)                        (empty)             (empty)    (empty)                     (empty)                    (empty)                                             (empty)
```

## 4. `${ISSUE_DATE}` Format Analysis
All raw `date` values found, grouped by detected format. **23 of 26 occurrences are numeric and normalisable.** The remaining 8 are placeholder/locale noise that any kproj reader must reject.

```
YYYY-MM-DD     12 occurrences  (mostly schematic side; design-time)
  2024-09-14, 2024-11-17, 2025-01-20 (x2), 2025-04-06, 2025-04-07,
  2025-12-03 (x2), 2026-04-06 (x3), 2026-04-06
YYYY.MM        11 occurrences  (mostly PCB side — already the contract target)
  2024.09 (x2), 2024.11, 2026.04 (x2), 2026.05, 2026.06,
  2026.07 (x4)
YYYY-MM         3 occurrences  (cpNode-expander-23017 SCH + IOX_Monitor SCH/PCB: "2026-07")
OTHER           8 occurrences  → unusable, see below
```

`OTHER` breakdown:
- `'2024,09'` (Brakeman SCH, BLUE & RED variants) — comma instead of dot/dash.
- `'DATE'` (IOX-Darlington SCH, cpNode-expander-23017 nested-dup SCH) — KiCad default placeholder, never edited.
- `'Fab Date'` (same two projects' PCB) — same placeholder, different side.
- `'sam. 04 avril 2015'` (zzz, both SCH and PCB) — KiCad's localized auto‑populated default.

**Normalisation rule kproj should adopt:** match `^(?P<y>\d{4})[-./,](?P<m>\d{1,2})` from the start of the string; reject any string that doesn't match a numeric `YYYY[sep]MM` prefix (so `DATE`, `Fab Date`, and the French default fail loudly). Output `f"{y}.{int(m):02d}"`. `YYYY-MM-DD` collapses cleanly to `YYYY.MM` via this rule.

## 5. SPCoast COMMENT1/2/3 Convention Verification
**Verdict: Holds where populated. Population is too thin to rely on it alone.**

Numbers come from the consensus value (sch‑or‑pcb populated). Classification is heuristic — see `analyze.py` for the rules. Counts sum to 34.

### `${COMMENT1}` — designer name
- `fit`: **11** (clear designer name)
- `partial`: **4** (placeholder, ambiguous, or sch≠pcb disagreement)
- `empty`: **19**

Example values (project → value):
- `Core-ESP32-Devkit` → `John Plocher`
- `LightDimmer-v1` / `LightDimmer-v1B` → `John Plocher`
- `MRCS/IOX-Darlington` → `John Plocher` (PCB only)
- `MRCS/cpNode-Xiao-68x90` → `John Plocher` (both)
- `Signal-ColorLight-Dwarf` → `JPlocher`
- *(partial)* `IOX-Darlington` nested dup → `Designer Name` (untouched KiCad template default)
- *(partial)* `cpNode-expander-23017` nested dup → `Designer Name` (same)
- *(partial)* `Core-wt32-eth0` → SCH `John Plocher`, PCB `Cambria` (PCB side has the *board name*, not the designer)
- *(partial)* `Signal-ColorLight-DualHead` → SCH `JPlocher`, PCB `John Plocher` (same person, different style)

### `${COMMENT2}` — tagline
- `fit`: **9**
- `partial`: **2** (single‑word values)
- `empty`: **23**

Example values:
- `Core-ESP32-Devkit` → `Breaks out 5v I2C, IO4 style headers and I2C OLED Display`
- `IOX_Plugin_Footprint` → `PCB Layout for daughterboard connectors`
- `MRCS/cpNode-Xiao-68x90` → `Breaks out 5v I2C, IO4 style headers and I2C OLED Display`
- `MRCS/cpNode-Xiao-80x70` → `Breaks out 5v I2C, IO4 style headers and I2C OLED Display`
- `Signal-ColorLight-DualHead` → `Panel by JLC, White Silk with Black Soldermask`
- `Signal-ColorLight-Dwarf` → `Fabrication Drawing` *(fab‑note, not a product tagline — borderline)*
- *(partial)* `Core-wt32-eth0` → `Cambria` (single word — looks like a code‑name)
- *(partial)* `cpNode-expander-23017` → `IOX-16` (single word — product line, not a tagline)
- *(template noise)* `IOX-Darlington` nested dup + `cpNode-expander-23017` nested dup → `Sheet Title Line 1`

### `${COMMENT3}` — overview continuation
- `fit`: **6**
- `empty`: **28**

Example values:
- `Core-ESP32-Devkit` → `Processor carrier board for ESP32-DEV`
- `MRCS/cpNode-Xiao-68x90` → `Processor carrier board for ESP32-DEV`
- `MRCS/cpNode-Xiao-80x70` → `Processor carrier board for ESP32-DEV`
- `MRCS/cpNode-expander-23017` → `Updated for use with` *(reads as a truncated/dangling phrase — implies COMMENT4 carries the continuation; in the data COMMENT4 = `cpNode Xiao`)*
- *(template noise)* `IOX-Darlington` nested dup + `cpNode-expander-23017` nested dup → `Sheet Title Line 2`

### Where the convention *does* hold cleanly
Every project where someone actually edited COMMENTs (i.e. not template defaults) fits the convention:
- `Core-ESP32-Devkit`, `MRCS/cpNode-Xiao-68x90`, `MRCS/cpNode-Xiao-80x70`, `LightDimmer-v1/-v1B`, `Signal-ColorLight-Dwarf`, `Signal-ColorLight-DualHead`, `MRCS/IOX_Plugin_Footprint`, `MRCS/IOX_Monitor`.

### Where it fails
- Two nested‑duplicate projects (`IOX-Darlington` outside MRCS, `cpNode-expander-23017` outside MRCS) carry the unedited KiCad template defaults `Designer Name` / `Sheet Title Line 1..3`. These are not real signal.
- `Core-wt32-eth0` PCB has the wrong slot semantics: `comment1='Cambria'` (board name, not designer), `comment2='Cambria'` (same board name, not a tagline). Looks like the user typed the board's marketing name into the wrong slots and never edited the schematic side.
- `MRCS/cpNode-expander-23017` `comment3='Updated for use with'` continues into `comment4='cpNode Xiao'` — the convention doesn't account for 4‑slot overflow.

### Conclusion
The SPCoast convention is real and consistent **when the user has actually filled in the COMMENT slots**, but only ~32% of projects (11/34) have a non‑empty designer slot and ~26% (9/34) have a tagline. kproj cannot assume populated COMMENTs and must fall back to `release.yaml` (or a CLI flag) for `designer`, `tagline`, and `overview`.

## 6. `${STATUS}` Candidate
**There is no in‑KiCad source for `STATUS`.** Hard evidence:
- All 34 `.kicad_pro` files contain `"text_variables": {}` — every one of them is the empty object literal. Confirmed both by my structured parse and by a raw `grep -A 5 '"text_variables"' …`.
- No `STATUS` / `STATE` / `PHASE` substring appears anywhere in any `.kicad_pro` file (case‑insensitive grep returned zero hits).
- No sidecar metadata files (`release.yaml`, `release.yml`, `STATUS*`, `status*`, `INFO`, `DESCRIPTION`) exist anywhere under the corpus.

There is also no convention encoded in title‑block fields that maps to status (no `comment*` slot is being used for it).

**Recommendation for the architect:** treat `STATUS` as a green‑field decision in Phase 2/3. Options the architect should weigh (none of which can be filled in from existing data):
1. **`release.yaml` sidecar field** — explicit, easy to enforce, doesn't require KiCad UI training. Closest to a `kproj`‑native convention.
2. **Project‑level KiCad text variable** — kproj documents `STATUS` as the canonical `text_variable` key; users add it via Project → Project Properties → Text Variables. Aligns with the contract's wording but requires every project to be migrated.
3. **Derived from filesystem signals** — git tag presence + `iskicad: 'obsolete'` rule + boolean override. Adequate to discriminate `active` vs `obsolete` but cannot express richer states.
4. **CLI flag override** — `--status=…` on the kproj invocation. Useful as a release‑time hatch regardless of the structural choice.

Whichever option wins, kproj needs to make `STATUS` *optional with a default*; the corpus cannot be relied on to provide it today.

## 7. Gap List — per Contract Field
Population denominator is 34. Numbers below count *any* sch‑or‑pcb populated value (the most generous count).

- **`title`** → `${TITLE}`: **19/34 (56%) populated, 7 of those have sch≠pcb mismatch**. Rely on KiCad title block **only with PCB‑precedence rule**, then fall back to sidecar/CLI. Mismatches like `cpNode Xiao` (SCH) vs `cpNode-Xiao-68x90` (PCB) suggest the PCB side carries the canonical/short identifier; SCH side carries the human prose.
- **`company`** → `${COMPANY}` → `tags: [<company>, kicad]`: **19/34 (56%) populated.** Distinct values: `MRCS` (14), `SPCoast` (10), `SPCoast / MRCS` (3), `MRCS / SPCoast` (2), `FoMoCo` (1). MRCS projects routinely have `SPCoast` in SCH and `MRCS` in PCB — the architect must pick a precedence rule. The `SPCoast / MRCS` slashed values would expand to two tags naturally if kproj splits on `/`. Needs sidecar fallback for the ~44% empty.
- **`rev` → `${REVISION}`**: **19/34 (56%) populated, 9 of those have sch≠pcb mismatch.** SCH often carries the schematic revision (`3.0`, `1.0`) while PCB carries the board revision (`1.0A`, `1.0B`, `3.2`). These are different concepts. Front‑matter `title: <revision>` should come from the PCB side (`1.0B`‑style) because that's what's actually getting fabricated and ordered.
- **`date` → `${ISSUE_DATE}`**: **20/34 (59%) populated**, but **8 of 26 raw values are unusable junk** (literal `DATE`, `Fab Date`, comma‑separated `2024,09`, French default). PCB side already emits `YYYY.MM` (the contract format) in 11 cases. With the normalisation rule in §4, dates from the PCB side land cleanly; SCH dates need format coercion; the 8 junk values must error or fall back to a sidecar.
- **`comment1` (designer)**: **15/34 (44%) populated**, only **11** clean. Insufficient on its own — fall back to sidecar.
- **`comment2` (tagline)**: **11/34 (32%) populated**, **9** clean. Insufficient — fall back to sidecar.
- **`comment3` (overview cont)**: **6/34 (18%) populated**, **6** clean (all that are populated are real). Mostly empty — fall back to sidecar or `README.md` body (the plan already lists `README.md` as the alternative path).
- **`comment4..9`**: **3/34 (9%) populated, all of those are KiCad template noise** (`Sheet Title Line 3`, or the cpNode‑expander overflow `cpNode Xiao`). Do not bind to any contract field.
- **`text_variables` (any key)**: **0/34 (0%) populated**. `STATUS` has no current KiCad source; sidecar/CLI/derived‑from‑filesystem are the only options.

**Net recommendation:** treat the KiCad title block as a *populated‑optimistic* source. Every contract field needs a sidecar fallback (`release.yaml`) until the corpus is cleaned up. The architect's plan to make `release.yaml` optional and KiCad‑first is correct in shape but should not be relaxed.

## 8. `cpNode-Xiao-68x90` Deep Dive (Phase 7 Validation Target)
**Path:** `/Users/jplocher/Dropbox/KiCad/projects/MRCS/cpNode-Xiao-68x90/`
**`.kicad_pro`:** `cpNode-Xiao-68x90.kicad_pro`
**`text_variables`:** `{}` (empty)

### Schematic title block (`cpNode-Xiao-68x90.kicad_sch`)

```sexp path=/Users/jplocher/Dropbox/KiCad/projects/MRCS/cpNode-Xiao-68x90/cpNode-Xiao-68x90.kicad_sch start=null
(title_block
    (title "cpNode Xiao")
    (date "2026-04-06")
    (rev "3.0")
    (company "SPCoast")
    (comment 1 "John Plocher")
    (comment 2 "Breaks out 5v I2C, IO4 style headers and I2C OLED Display")
    (comment 3 "Processor carrier board for ESP32-DEV")
)
```

### PCB title block (`cpNode-Xiao-68x90.kicad_pcb`)

```sexp path=null start=null
(title_block
    (title "cpNode-Xiao-68x90")
    (date "2026.05")
    (rev "1.0B")
    (company "MRCS")
    (comment 1 "John Plocher")
)
```

### Contract field consensus for this project (PCB‑precedence rule applied)

```
project           cpNode-Xiao-68x90
basename          cpNode-Xiao-68x90      ← matches PCB title (canonical short form)
title (front)    1.0B                    ← from PCB rev; the orderable revision label
date              2026.05                 ← from PCB; already in YYYY.MM
designer          John Plocher            ← from comment1 (both sides agree)
tagline           Breaks out 5v I2C, IO4 style headers and I2C OLED Display   ← from SCH comment2 (PCB has no comment2)
overview          tagline + "Processor carrier board for ESP32-DEV"          ← from SCH comment3 (PCB has no comment3)
tags              [MRCS, kicad]           ← from PCB company; (sch would say [SPCoast, kicad])
status            (unknown)               ← no source; must come from sidecar/CLI
```

### Notes the architect must reconcile
- **`title` field is split**: SCH `cpNode Xiao` is the prose name; PCB `cpNode-Xiao-68x90` matches the project basename. The contract says `project: <basename of .kicad_pro>` and `title: <revision>`, so the SCH title‑string is *not* needed for the contract — but it might be useful as a `display_title` field if the architect wants prose. Worth surfacing in Phase 2.
- **`company` is split**: SCH `SPCoast`, PCB `MRCS`. For the MRCS subtree the canonical tag is presumably MRCS; the rest of SPCoast keeps `SPCoast`. PCB‑precedence is consistent with what's actually fabricated.
- **`rev` is split**: SCH `3.0` (schematic version), PCB `1.0B` (board revision). The orderable artifact is the PCB, so `1.0B` is the right `<Revision>` for `_versions/cpNode-Xiao-68x90/1.0B.md`.
- **All COMMENTs live on the SCH side**; PCB only carries `comment1` (designer). If kproj wants tagline/overview, it has to read the SCH file even when PCB‑precedence is the default. The architect needs to decide whether the contract is "PCB‑first across all fields" or "PCB‑first for board metadata, SCH‑first for COMMENTs" (the cleaner semantic).
- **`text_variables: {}`** — no STATUS, no overrides. Until kproj fills it, status must come from a sidecar.

## 9. Surprises and Open Questions
- **SURPRISE 1 — `text_variables` is empty everywhere.** The plan's "likely `STATUS`" wording in `text_variables` is aspirational. Either kproj defines the convention and migrates existing projects, or the architect must accept a sidecar (`release.yaml`) as the only viable Phase 6 status source. There is currently nothing to mine.
- **SURPRISE 2 — SCH and PCB title blocks routinely disagree.** 18 of 34 projects have at least one field where SCH ≠ PCB. The split is not random: SCH carries design‑time / human‑readable data; PCB carries fab‑ready / canonical data. The contract needs an *explicit precedence rule*. My recommendation: PCB wins for `title`, `company`, `rev`, `date`; SCH wins for `comment2`/`comment3` (because PCB title blocks routinely lack them). Designer (`comment1`) should be SCH OR PCB (either side acceptable, since they almost always match).
- **SURPRISE 3 — Default placeholder text leaks through.** Two projects carry KiCad's untouched defaults (`Designer Name`, `Sheet Title Line 1..3`, `DATE`, `Fab Date`). Any kproj reader must reject these literally, or they will end up in front‑matter and on the site.
- **SURPRISE 4 — Nested‑duplicate project directories exist.** `projects/IOX-Darlington/IOX-Darlington/IOX-Darlington/IOX-Darlington.kicad_pro` and `projects/cpNode-expander-23017/cpNode-expander-23017/cpNode-expander-23017/cpNode-expander-23017.kicad_pro` look like accidental nestings (3 levels deep). kproj's project selector should de‑duplicate by `realpath` or by canonical basename, or the user will publish the same project twice.
- **SURPRISE 5 — `${PROJECTNAME}` appears as a literal string in the `title` field of 3 projects.** Those projects never had a real title typed in; KiCad's default page layout uses `${PROJECTNAME}` and the user left it. kproj should treat any field whose value starts with `${` as "unresolved/empty" and fall back.
- **SURPRISE 6 — Date format is *almost* split cleanly by side.** PCB favours `YYYY.MM` (the contract target — 11/13 PCB dates), SCH favours `YYYY-MM-DD` (9/13 SCH dates). If kproj defaults to PCB‑precedence, ~85% of populated date values already match the target format. Normalisation only matters for the SCH fall‑back path and the OTHER junk.
- **SURPRISE 7 — `comment4..9` are unused except as KiCad template overflow.** Treat `comment4` and higher as not part of the contract; if anyone wants more text, the contract should grow via sidecar/`README.md`, not by adding `comment4` semantics.
- **OPEN QUESTION 1 — Precedence rule.** Does the architect want PCB‑first across the board, or SCH‑first for COMMENT fields only? Phase 2 should decide and lock this.
- **OPEN QUESTION 2 — `company`‑with‑slash handling.** Five projects have `SPCoast / MRCS` or `MRCS / SPCoast`. Splitting on `/` would yield `tags: [SPCoast, MRCS, kicad]` — a richer tag set. Does the contract want that?
- **OPEN QUESTION 3 — Multi‑variant projects.** `Brakeman-BLUE` and `Brakeman-RED` share a `Brakeman.kicad_pro` basename (in different directories) but represent different boards; `LightAdapter-6p6c` and `LightAdapter-8p8c` likewise. The contract's `project: <basename>` rule would merge them. kproj may need a directory‑name disambiguation step, or each variant needs an explicit override.
- **OPEN QUESTION 4 — `iskicad` discriminator for stale/template projects.** A dozen projects in the corpus are clearly scaffolding (`templates/empty_project`, `Untitled`, `allSPCoast-test`, `zzz`, `testfoot`, `cpNode-Xiao-orig`). kproj will need a way to skip these — probably a `.kproj-ignore` marker file or a "must have both `.kicad_sch` and `.kicad_pcb`" pre‑check.

---
*Intermediate artifacts in this workspace (re‑greppable for follow‑up questions):*
- `survey.json` — per‑project structured record (the source of truth for §3–§8).
- `survey.csv` — flat one‑row‑per‑project view for spreadsheets.
- `analysis.json` — aggregate counters used in §1, §4, §5, §7.
- `survey.py`, `analyze.py`, `drill.py`, `query_companies.py` — the scripts used.
