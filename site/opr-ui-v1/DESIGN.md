# Old Parish Records — UI v1 design direction

## Branding
- Public chrome: **Old Parish Records** (matches domain). No parish name, no family name, no “Lank” / “Veit” in title, header, or footer.
- Voice: archival reading room, not SaaS dashboard.

## Visual system
- **Paper**: warm parchment page (`#f4efe4` / `#ebe4d4` parchment) on a deeper oak/ink frame.
- **Ink**: near-black brown for body; muted slate for meta.
- **Accent**: oxblood / sealing-wax red for primary actions and kind accents (sparingly).
- **Type**: Georgia / `Iowan Old Style` / serif for titles; system UI sans for form controls and meta.
- **Texture**: subtle hairline rules and card borders — register-ledger feel, not skeuomorphic parchment noise.

## UX
- Search form first: anywhere (`q`), name, place, date/year, kind.
- Results as **cards** (kind · date · place · archival citation · names · snippet), not raw JSON.
- Staging counts from `/health` shown quietly in the footer/status strip.
- Progressive enhancement: `method="get" action="/search"` so no-JS still hits the JSON API; JS enhances into cards.
- Do not change `/health` or `/search` JSON contracts.

## Out of scope for v1
- Matricula deep links, auth, write paths, schema changes, networking.
