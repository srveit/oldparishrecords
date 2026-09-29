#!/usr/bin/env python3
"""Tests for check_expanded_latin.py (v2, 2026-09-29).  Run: python3 test_check_expanded_latin.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_expanded_latin import check

PASS = [  # (name, transcription_latin, expanded_latin)
    # --- worked examples, EXPANDED_LATIN_RULES.md §5 ---
    ('§5 KB999_4 p6 e3', '1584. 17. februa- / rii | Prænob. et Gen. vir Wilhelmus de Baukum / Dominus in Hamm.',
     '1584. 17. februarii | Prænob[ilis] et Gen[erosus] vir Wilhelmus de Baukum Dominus in Hamm.'),
    ('§5 KB999_4 p6 e2 (L. B. spaced)', '1566 | Prænobilis ac Generosus L. B. Rutger / de Baukum Dominus in Hamm.',
     '1566 | Prænobilis ac Generosus L[iber] B[aro][?] Rutger de Baukum Dominus in Hamm.'),
    ('legacy run-together L.B.', '1566 | Prænobilis ac Generosus L.B. Rutger', '1566 | Prænobilis ac Generosus L[iber] B[aro][?] Rutger'),
    ('§5 KB999_4 s010 p16 e3', '15. februarij Petrus Heijes cond. Brauns in Lank [?]',
     '15. februarij Petrus Heijes cond[ictus] Brauns in Lank [?]'),
    ('Dñi / Wilh: / Sti / curr.', '9nâ 8bris Anno Dñi 1779 Ego Wilh: Jacobs … Sti Stephani … 6tâ curr. natam',
     '9nâ 8bris Anno D[omi]ni 1779 Ego Wilh[elmus] Jacobs … S[anc]ti Stephani … 6tâ curr[entis] natam'),
    ('Xtinæ / Χtina', 'Xtinæ et Χtina', '[Chris]tinæ et [Chris]tina'),
    ('sentence-final Dom.', 'a me Dom.', 'a me Dom[inus].'),
    # --- Stage A markers, identical on both sides ---
    ('[struck: X] carried', 'ex / Schall. / [struck: obt] | obtentā', 'ex Schall[ern] [struck: obt] | obtentā'),
    ('[struck?: X] carried', 'et [struck?: fil] filius', 'et [struck?: fil] filius'),
    ('[interlinear: X] content expanded', 'M. Sybilla = [interlinear: Brinkhoff dtā] Herweg',
     'M[aria] Sybilla = [interlinear: Brinkhoff d[ic]ta] Herweg'),
    ('[interlinear: X] content unexpanded', 'Sybilla = [interlinear: Brinkhoff dtā] Herweg', 'Sybilla = [interlinear: Brinkhoff dtā] Herweg'),
    ('[interlinear, above line N: X]', 'Anna [interlinear, above line 2: Maria] Kruse', 'Anna [interlinear, above line 2: Maria] Kruse'),
    ('label differs, content same', 'Anna [interlinear, above line 2: Maria] Kruse', 'Anna [interlinear: Maria] Kruse'),
    ('[interlinear] label', 'regenerata / [interlinear, above \'Maria\', underlined] Anna / Maria Elisab.',
     'regenerata [interlinear, above \'Maria\', underlined] Anna Maria Elisab[etha]'),
    ('[later_note (...)] label', 'Illegit. | [later_note (under baptizati)] Legit. 9a aug. / 1805.',
     'Illegit[ima] | [later_note (under baptizati)] Legit[imata] 9a aug[usti] 1805.'),
    ('[later addition] label', 'ex Horn. / [later addition] Frans Buschman', 'ex Horn. [later addition] Frans Buschman'),
    ('column labels in diplomatic_text', '[margin_date]\n22 diē\n[place]\nex Schall.\n[main_text]\nobtentā',
     '22 diē | ex Schall[ern] | obtentā'.replace(' | ', ' ')),
    ('[?|alt] carried', 'in Lanck ven Kothen[?|Kotten]', 'in Lanck ven Kothen[?|Kotten]'),
    ('[*] carried', 'in Strümp ven Bantagns[*]', 'in Strümp ven Bantagns[*]'),
    ('Stage A supplied digit [1]803', 'Anno [1]803', 'Anno [1]803'),
    # --- abbreviation signs the expanded side may drop ---
    ('q; -> q[ue]', 'Rdō. doctissimoq; Dnō parocho', 'R[everen]do doctissimoq[ue] D[omi]no parocho'),
    ('q; kept unexpanded', 'doctissimoq; Dnō', 'doctissimoq; D[omi]no'),
    ('ꝫ -> q[ue]', 'doctissimoqꝫ Dnō', 'doctissimoq[ue] D[omi]no'),
    ('dtʸ -> d[ic]t[us]', 'Koch dtʸ Schulte', 'Koch d[ic]t[us] Schulte'),
    ('Mʸ stripped', 'Mʸ Sybilla', 'M[aria] Sybilla'),
    ('superscript kept', 'Koch dtʸ Schulte', 'Koch dtʸ Schulte'),
    ('superscript as plain letters', 'Sᵗⁱ Stephani', 'S[anc]ti Stephani'),
    ('gebʳ.', 'Anna gebʳ. Kruse', 'Anna geb[orene] Kruse'),
    ('macron below No̱ / dta̱', 'No̱ 16. dta̱ Rikart', 'N[umer]o 16. d[ic]ta Rikart'),
]
FAIL = [
    ('added word', 'Petrus Heijes in Lank', 'Petrus Heijes natus in Lank'),
    ('dropped struck content', 'ex Schall. [struck: obt] | obtentā', 'ex Schall[ern] | obtentā'),
    ('changed interlinear content', 'Sybilla = [interlinear: Brinkhoff dtā] Herweg', 'Sybilla = [interlinear: Brinkhof dtā] Herweg'),
    ('dropped reading [?]', 'Schüer[?] ex Schall.', 'Schüer ex Schall[ern]'),
    ('changed [?|alt]', 'Kothen[?|Kotten]', 'Kothen[?|Kothen]'),
    ('letter dropped outside brackets', 'Dnō parocho', 'D[omi]no paroch'),
    ('semicolon not after q is punctuation', 'Anna; Maria', 'Anna Maria'),
    ('umlaut removed', 'Büsch', 'Busch'),
]

bad = 0
for name, t, e in PASS:
    r = check(t, e)
    if r: bad += 1; print('UNEXPECTED FAIL:', name, '|', r)
for name, t, e in FAIL:
    if check(t, e) is None: bad += 1; print('UNEXPECTED PASS:', name)
print(f'{len(PASS)} pass-cases, {len(FAIL)} fail-cases, {bad} problems')
sys.exit(bool(bad))
