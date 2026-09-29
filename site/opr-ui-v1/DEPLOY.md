# Deploy — UI v1 drop-in (Site Host)

## Package (shared box)
`/workspace/opr-ui-v1/static/`
- `index.html`
- `styles.css`
- `app.js`

Fallback single file: `/workspace/opr-ui-v1/index.single.html` (all-in-one).

## Install on VM `oldparishrecords` (VMID 100)
Target: `/opt/lank-search/static/`

```bash
sudo mkdir -p /opt/lank-search/static
sudo cp index.html styles.css app.js /opt/lank-search/static/
# if app.py still inlines HTML, finish the StaticFiles switch first, then:
sudo systemctl restart lank-search
```

Serve GET `/` from `static/index.html` (or FileResponse). `index.html` links to `/static/styles.css` and `/static/app.js` (assumes StaticFiles mount at `/static` and HTML served at `/`).

## Do not change
- JSON `GET /health`, `GET /search`
- Query params: `q`, `name`, `place`, `date`, `kind`

## Smoke
1. `curl -sS http://127.0.0.1:8000/health`
2. Open `/` — title **Old Parish Records** (not Lank)
3. Search name=`Mueller` — card results, not raw JSON dump
4. `curl -sS 'http://127.0.0.1:8000/search?name=Mueller'` still JSON
