#!/usr/bin/env python3
"""Round-trip check for expanded_latin (EXPANDED_LATIN_RULES.md §6).  v2 2026-09-29.
Usage: check_expanded_latin.py FILE.json [...]   (Stage B JSON records)
   or: check_expanded_latin.py --pair "<transcription_latin>" "<expanded_latin>"
   or: check_expanded_latin.py -v ...            (also print both skeletons)

Both sides are reduced to a skeleton by the SAME tokenizer, and the skeletons must match:
  Stage A editorial markers (identical treatment on both sides):
    content markers  [struck: X] [struck?: X] [interlinear: X] [interlinear, above line N: X]
                     [later note: X] [above: X] ...  -> label dropped, content X kept and
                     compared (X may carry [supplied] letters on the expanded side)
    label markers    [interlinear] [interlinear, above 'Maria', underlined] [later_note (...)]
                     [later addition] [margin 1] [sic] [illegible] [small mark …] and column labels
                     [margin_date] [place] [main_text] [testes] [date_place] [baptizati]
                     [patrini] [parentes] ...  -> dropped entirely
    reading marks    [?]  X[?|Y]  [*]  -> kept verbatim (carried over from Stage A)
  [Chris] counts as X; any other [supplied] group is dropped, together with a [?] that
  directly follows it (uncertain expansion); Stage A supplied digits like [1]803 likewise.
  ' / ' line breaks and wrap hyphens removed; Greek chi -> X; combining abbreviation marks
  (tilde, macron, overline, breve, stroke, macron-below, low line) stripped; '.' ':' removed;
  all whitespace removed.
  Abbreviation signs the expanded side may drop (optional on the source side, stripped on
  the expanded side): 'q;' (-que), the et/-que sign ꝫ, ꝰ, superscript/raised letters
  (ʸ ʳ ⁱ ᵗ ᵒ ... and combining letters U+0363-036F). A superscript letter may instead be
  written as its plain letter on the expanded side (Sᵗⁱ -> S[anc]ti or Sti).
"""
import sys, json, re, unicodedata

MARKS = {'\u0303', '\u0304', '\u0305', '\u0306', '\u0336', '\u0331', '\u0332'}
SUPER = dict(zip('ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ', 'abcdefghijklmnoprstuvwxyz'))
SUPER.update(dict(zip([chr(c) for c in range(0x363, 0x370)], 'aeioucdhmrtvx')))
OPT_SIGNS = {'\ua76b', '\ua770'}          # ꝫ (et/-que sign), ꝰ (-us)
OPT = '\ue000'                               # sentinel: next char is optional (source side)
KW = (r'struck\??|interlinear|later[ _]?note|later[ _]addition|later|inserted|insert|above|'
      r'below|margin\w*|note|sic|illegible|gap|blot|erased|faded|lacuna|main_text|place|'
      r'testes|date_place|baptizati|patrini|parentes|proles|parents|witnesses|sponsors|'
      r'small mark|mark|flourish|cross|symbol|stamp|unclear')
MARKER = re.compile(r'^\s*(?:' + KW + r')(?=[\s,:(\]]|$)', re.I)

def _match(s, i):
    """index of the ']' closing the '[' at s[i], or -1."""
    depth = 0
    for k in range(i, len(s)):
        if s[k] == '[': depth += 1
        elif s[k] == ']':
            depth -= 1
            if depth == 0: return k
    return -1

def tokens(s):
    """Resolve bracket groups. Returns text with protected reading marks as \x01..\x02."""
    out, i, dropped = [], 0, False
    while i < len(s):
        c = s[i]
        if c != '[':
            out.append(c); i += 1; dropped = False
            continue
        j = _match(s, i)
        if j < 0:
            out.append(c); i += 1; continue
        inner = s[i + 1:j]
        if inner == '?':
            if not dropped: out.append('\x01?\x02')      # reading [?] (else: uncertain expansion)
            dropped = False
        elif inner.startswith('?|') or inner == '*':
            out.append('\x01' + inner + '\x02'); dropped = False
        elif MARKER.match(inner):
            head, sep, content = inner.partition(':')
            if sep and '[' not in head:
                out.append(' ' + tokens(content) + ' ')   # content marker: keep content
            dropped = False                              # label marker: drop entirely
        elif inner == 'Chris':
            out.append('X'); dropped = False
        else:
            dropped = True                               # [supplied] letters / digits
        i = j + 1
    return ''.join(out)

def base(s, source):
    s = s.replace('Χ', 'X').replace('χ', 'X')
    s = tokens(s)
    s = re.sub(r'-\s*/\s*', '', s)                   # wrap hyphen + line break
    s = s.replace('/', ' ')
    s = ''.join(ch for ch in unicodedata.normalize('NFD', s) if ch not in MARKS)
    s = unicodedata.normalize('NFC', s)
    if source:
        s = re.sub(r'q;(?![A-Za-zÀ-ÿ])', 'q' + OPT + ';', s)
        s = ''.join(OPT + SUPER[ch] if ch in SUPER else OPT + ch if ch in OPT_SIGNS else ch for ch in s)
    else:
        s = ''.join(ch for ch in s if ch not in SUPER and ch not in OPT_SIGNS)
    s = re.sub(r'[.:]', '', s)
    return re.sub(r'\s+', '', s)

def _regex(src):
    parts, i = [], 0
    while i < len(src):
        if src[i] == OPT and i + 1 < len(src):
            parts.append('(?:' + re.escape(src[i + 1]) + ')?'); i += 2
        else:
            parts.append(re.escape(src[i])); i += 1
    return re.compile(''.join(parts))

def show(s): return s.replace(OPT, '').replace('\x01', '[').replace('\x02', ']')

def skeletons(t, e): return base(t, True), base(e, False)

def check(t, e):
    a, b = skeletons(t, e)
    if _regex(a).fullmatch(b): return None
    amin = re.sub(OPT + '.', '', a)                   # source without optional signs
    i = next((k for k in range(min(len(amin), len(b))) if amin[k] != b[k]), min(len(amin), len(b)))
    return f"mismatch at skeleton char {i}: src …{show(amin[max(0,i-15):i+15])}… vs exp …{show(b[max(0,i-15):i+15])}…"

if __name__ == '__main__':
    args = sys.argv[1:]
    verbose = '-v' in args
    args = [a for a in args if a != '-v']
    if args[:1] == ['--pair']:
        r = check(args[1], args[2])
        if verbose:
            a, b = skeletons(args[1], args[2]); print('src:', show(a)); print('exp:', show(b))
        print(r or 'OK'); sys.exit(bool(r))
    bad = 0
    for f in args:
        d = json.load(open(f)); e = d.get('expanded_latin')
        if not e: print('SKIP (null)', f); continue
        r = check(d.get('transcription_latin') or '', e)
        print(('OK   ' if not r else 'FAIL ') + f + ('' if not r else '  ' + r)); bad += bool(r)
    sys.exit(bad)
