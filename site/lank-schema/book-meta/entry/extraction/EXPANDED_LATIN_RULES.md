# `expanded_latin` — shared expansion rulebook (all OPR registers)

**Status:** LOCKED 2026-09-25 (Stephen approval relayed by Chief).  
**Amended 2026-09-29 (Schema Steward):** §2.5 run-together groups are now spaced in Stage A (Stephen's rule). The marker, `q;` and superscript text in §2.6, §3 and §6 describes checker v2 and is **pending Stephen approval**. The §5 examples were updated.  
**Source text:** hist-notes CSVs use `transcription` where the other registers use `transcription_latin`; apply the same rules to it.  
**Applies to:** every Stage B record schema — baptism (`opr-baptism-record` ≥ 1.0.3), death (`opr-death-record` ≥ 1.0.1), communion (`opr-communion-record` ≥ 1.0.2), marriage (`opr-marriage-record` ≥ 1.0.0, DRAFT), and hist-notes records when their Stage B schema is drafted (the field name is reserved now). German-script registers (e.g. Osterath) use the **same field name** and the same rules.  
**Owner of this file:** Schema Steward. Register owners follow it; propose changes via Chief.

## 1. The three text fields

| Field | What it is | Who edits it |
|-------|------------|--------------|
| `diplomatic_text` / Stage A diplomatic | Exactly as written: line breaks as ` / `, abbreviations, ligatures, `[?]` marks | Stage A only; never rewritten in Stage B |
| `transcription_latin` | `margin \| diplomatic body` (diplomatic copy, unchanged) | Stage B copy |
| **`expanded_latin`** | Reading + search form of the same text (rules below). Nullable: `null` = not yet produced | Stage B, register owner |

`expanded_latin` never replaces the other two, and never feeds person fields back into Stage A.

## 2. Rules

1. **Start from `transcription_latin`**, character for character, then apply only rules 2–8.
2. **Margin prefix:** keep the margin exactly as `transcription_latin` has it, then ` | `, then the body. No margin → no ` | `.
3. **Line breaks:** delete every ` / ` line-break marker, leaving a single space.
4. **Wrapped words:** a hyphen at line end followed by the continuation joins into one word, hyphen removed: `februa- / rii` → `februarii`, `infan- / tem` → `infantem`. A hyphen that is part of the word (e.g. `Proto-Martyris`) or a closing flourish/dash at the very end of the entry stays.
5. **Supplied letters in square brackets** (Leiden): expand an abbreviation only where the page marks it — a period or colon (`Wilh:`, `curr.`, `Gen.`), a tilde/macron/bar (`Dñi`, `Joēs`, `Nov̄s`), a superscript or raised letters (`Sti` for S^ti), a standard contraction symbol, or the chi/X for Christ-. Write only the missing letters inside `[ ]`:
   - `Prænob.` → `Prænob[ilis]`; `Gen.` → `Gen[erosus]`; `L. B.` → `L[iber] B[aro]`
   - `Dñi` → `D[omi]ni`; `Sti` → `S[anc]ti`; `Wilh:` → `Wilh[elmus]`; `curr.` → `curr[entis]`
   - **The mark goes away when its letters are supplied.** The abbreviation period or colon is replaced by the bracketed letters (`Gen.` → `Gen[erosus]`, `Wilh:` → `Wilh[elmus]`). A period that also ends the sentence stays after the bracket: `… Dom.` at the end → `Dom[inus].`
   - **Run-together abbreviation groups: spaced in Stage A, expanded word by word in Stage B (Stephen, 2026-09-29; supersedes the 2026-09-25 wording).** When a group such as `L.B.` stands for separate words, the Stage A diplomatic text records it **spaced**, `L. B.` (Stage A rule: ENTRY_TRANSCRIBER_SPEC.md, "Abbreviation groups"). Stage B then expands each word in place: `L. B.` → `L[iber] B[aro][?]`. So the space already exists in `transcription_latin`, and Stage B adds nothing but bracketed letters. The same applies to `s. v.`, `f. l.`, `R. D.`, `L: B:` and similar. If the group can't be expanded confidently, keep it exactly as Stage A has it (`L. B.`) and explain it in `notes`. Don't put in a half expansion. *Legacy:* a record whose locked Stage A still reads `L.B.` (no space) may be expanded `L[iber] B[aro]`. The checker ignores whitespace, so it passes, but the Stage A text should be spaced at its next amendment.

6. **Uncertain expansion:** add `[?]` directly after the closing bracket: `L[iber] B[aro][?]`. (A `[?]` after unbracketed letters is an uncertain *reading* carried over from Stage A; keep it as is. Stage A alternates like `Kothen[?|Kotten]` or `foo[?]/bar]`, and `[*]`, are also carried over unchanged.)
   - **Stage A editorial markers are carried over, too:** `[struck: X]`, `[struck?: X]`, `[interlinear: X]`, `[interlinear, above line N: X]`, `[later note: X]` keep their label. The content `X` is diplomatic text and may receive supplied letters like any other text (`[interlinear: Brinkhoff d[ic]ta]`), or be left unexpanded. Label-only markers (`[interlinear]`, `[interlinear, above 'Maria', underlined]`, `[later_note (under baptizati)]`, `[later addition]`, `[margin 1]`, `[sic]`) and column labels (`[margin_date]`, `[place]`, `[main_text]`, `[testes]`, …) are copied as they stand in `transcription_latin`. Never drop struck or interlinear content from `expanded_latin`.
7. **Keep the spelling:** no classicizing, no case changes, no umlaut/ÿ additions or removals, and æ/œ stay as ligatures (`Ecclesiæ`, `Prænobilis`). `-ij` stays `-ij` (`februarij`). Lowercase surnames stay lowercase here (capitalizing belongs to person fields). Search folds æ to ae and removes brackets, so no normalized copy is stored.
8. **Add nothing** that isn't implied by an abbreviation mark or a wrap: no missing words, no grammar fixes, no `[sic]`, no punctuation.

## 3. Case, numerals, special forms

- **Expand in the case written.** `Joīs` stays genitive: `Jo[hann]is`. `Joēs` → `Jo[ann]es` even when grammar wants a genitive. (Nominative forms belong in person fields, not here.)
- **Locked forename expansions** follow Stephen's Stage B locks: `Joīs` → `Jo[hann]is`; `Joēs` → `Jo[ann]es`; `Xtina` / `Χtina` → `[Chris]tina` and `Xtinæ` → `[Chris]tinæ` (the X/chi is the abbreviation sign, so it is replaced by the bracketed letters).
- **Numeral dates stay as written:** `9nâ 8bris`, `5tâ`, `16ta`, `8bris`, `1584. 17.` are not expanded (no supplied letters behind a numeral). Normalized dates live in `*_date_iso`. Written month abbreviations with a mark are expanded: `Nov:` → `Nov[embris]`, `Jan.` → `Jan[uarii]` (genitive after a day number).
- **`N.`** (unknown surname) stays `N.` — it is not an abbreviation to expand.
- **`q;`** (the *-que* sign, e.g. `doctissimoq;`) → `q[ue]`, replacing the `;`. **Superscript letters** such as `dtʸ` → `d[ic]t[us]` (the raised letter goes away like a macron); `gebʳ.` → `geb[orene]`.
- **`cond.`** → `cond[ictus]`; **`vulg.`** → `vulg[o]`; **`gh.`** stays `gh.` until Stephen locks an expansion (flag in notes).
- **Titles:** `Adm. R. Dñus` → `Adm[odum] R[everendus] D[omi]nus`; `Dñæ L. Baronesse` → `D[omi]næ L[iberæ] Baronesse` (mark `[?]` if the ending is unclear).
- **When unsure** whether something is an abbreviation at all, leave it as written. When unsure of the expansion, expand and add `[?]`.

## 4. German-script registers (Osterath, later German entries)

Same rules and same field name. Abbreviations such as `K.` or `Tauf.` are expanded with supplied letters in `[ ]` once the register owner has checked the reading against the page; until a form is settled, leave it as written and record it in `notes`. Keep `ſ`, umlauts and the original spelling. Settled German expansions get added to a table here (none locked yet).

## 5. Worked examples (Stephen/Chief)

| Entry | `expanded_latin` |
|-------|------------------|
| KB999_4 p6 e3 | `1584. 17. februarii \| Prænob[ilis] et Gen[erosus] vir Wilhelmus de Baukum Dominus in Hamm.` |
| KB999_4 p6 e2: Stage A diplomatic (spaced group, amended 2026-09-25): `Prænobilis ac Generosus L. B. Rutger / de Baukum Dominus in Hamm.` | `1566 \| Prænobilis ac Generosus L[iber] B[aro][?] Rutger de Baukum Dominus in Hamm.` |
| KB1000 p15 e1 | `9nâ 8bris Anno D[omi]ni 1779 Ego Wilh[elmus] Jacobs parochus hujus parochialis Ecclesiæ Proto-Martyris S[anc]ti Stephani in Lanck baptizavi infantem 6tâ curr[entis] natam …` (full text in `examples/KB1000_s003_p15_e1.baptism.json`) |
| KB999_4 s010 p16 e3 | `15. februarij Petrus Heijes cond[ictus] Brauns in Lank [?]` |
| Horn KB005-02-H H0135 e2 (`doctissimoq;`) | `… ā plurim[um] R[everen]do doctissimoq[ue] D[omi]no parocho Schlinkert …` |
| Horn KB005-02-H H0135 e3 (markers) | `22 diē 8bris \| ex Schall[ern] [struck: obt] \| … M[aria] Sybilla = [interlinear: Brinkhoff dtā] Herweg ob[i]torum C[on]j[u]gum filius …` |
| Horn KB005-02-H H0135 e4 (`dtʸ`) | `… J[oan][?] Henrich Koch d[ic]t[us] Schulte, Antonii Koch, Ffti, …` |

## 6. QC checklist (per record)

Run `python3 /workspace/lank-schema/tools/check_expanded_latin.py <record>.json` (or `--pair "<transcription_latin>" "<expanded_latin>"`; add `-v` to print both skeletons). Checker **v2 (2026-09-29)** reduces both texts to a skeleton with **the same tokenizer**, and the two skeletons must match. Tests: `tools/test_check_expanded_latin.py`.
- **Stage A markers, identical on both sides.** In *content markers* (`[struck: X]`, `[struck?: X]`, `[interlinear: X]`, `[interlinear, above line N: X]`, `[later note: X]`, `[above: X]`, …) the label is dropped and the content `X` is kept and compared. Inside `X` the expanded side may supply letters. If one side drops the content, the check fails. *Label markers* (`[interlinear]`, `[interlinear, above …, underlined]`, `[later_note (…)]`, `[later addition]`, `[margin …]`, `[sic]`, `[illegible]`, `[small mark …]`) and column labels (`[margin_date]`, `[place]`, `[main_text]`, `[testes]`, `[date_place]`, `[baptizati]`, `[patrini]`, `[parentes]`) are dropped on both sides. The label wording may therefore differ (e.g. `[interlinear, above line 4: X]` vs `[interlinear: X]`); only the content counts. *Reading marks* `[?]`, `X[?|Y]` and `[*]` are kept verbatim on both sides.
- **Supplied letters.** `[Chris]` counts as `X`. Every other `[supplied]` group is dropped, and so is a `[?]` **directly** after it (uncertain expansion). Stage A's own supplied digits (`[1]803`) are treated the same way on both sides. A reading `[?]` after plain letters is kept.
- **Abbreviation signs the expanded side may drop.** These are optional on the source side and stripped on the expanded side:
  - `q;` (the *-que* sign) followed by a non-letter: `doctissimoq;` pairs with `doctissimoq[ue]`, or stays `doctissimoq;`. A `;` anywhere else is punctuation and must match.
  - The et/*-que* sign `ꝫ` and `ꝰ`.
  - Superscript / raised letters `ᵃ ᵇ ᶜ ᵈ ᵉ ᶠ ᵍ ʰ ⁱ ʲ ᵏ ˡ ᵐ ⁿ ᵒ ᵖ ʳ ˢ ᵗ ᵘ ᵛ ʷ ˣ ʸ ᶻ` and combining letters U+0363–U+036F. They are stripped like a combining mark: `dtʸ` pairs with `d[ic]t[us]`, and `Mʸ` pairs with `M[aria]`. They may instead be written as the plain letter: `Sᵗⁱ` pairs with `S[anc]ti`.
- **Both sides.** Line breaks ` / ` and wrap hyphens are removed. Greek chi counts as X. Combining abbreviation marks are removed: tilde, macron, overline, breve, stroke, and (new) macron-below U+0331 / low line U+0332, as in the Horn `No̱`, `dta̱`, `ds̱`. Abbreviation dots and colons are removed, and **all whitespace is ignored**. That is why `L. B.` (or legacy `L.B.`) and `L[iber] B[aro][?]` both reduce to `LB` and pass.
- **Limits.** The checker does not decide whether an expansion is *right*. It also cannot tell a dropped optional sign from a legitimately expanded one: `q;` → `q` passes. Special letters such as `ꝯ` (con-) or `ꝑ` (per-) are not handled yet and would need `[supplied]` pairing rules.

Also check by eye:
- No ` / ` is left over, and no wrap hyphen sits in the middle of a word.
- Every `[` has a closing `]`, and every uncertain expansion carries `[?]`.
- The margin prefix matches `transcription_latin`.
- Stage A markers and their content are all still there.
- Nothing is added beyond bracketed letters.

## 7. Search / DB

Postgres: `expanded_latin text` (nullable) on every `stg_*` table, plus an immutable `lank.fold_search_text()` (lowercase, æ/Æ to ae, œ/Œ to oe, ſ to s, brackets and `[?]` stripped; capital Œ added by `05_expanded_latin_fixes.sql`, which also REINDEXes the FTS indexes) and a GIN full-text index using the `simple` config over `coalesce(expanded_latin, transcription_latin)`. See `../../postgres/04_expanded_latin.sql`.
