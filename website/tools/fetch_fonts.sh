#!/usr/bin/env bash
# Refresh the self-hosted webfonts in website/assets/fonts and rebuild fonts.css.
# Google Fonts serves different files depending on the User-Agent; the Chrome UA
# below is what gets us woff2 rather than ttf.
set -euo pipefail
cd "$(dirname "$0")/.."
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
URL="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&family=Inter:wght@300;400;500;600&display=swap"
curl -sS -A "$UA" "$URL" -o /tmp/aurelia-gf.css
python3 - <<'PY'
import re, pathlib, subprocess
src = pathlib.Path('/tmp/aurelia-gf.css').read_text()
blocks = re.findall(r'/\* ([\w-]+) \*/\n@font-face \{(.*?)\}\n', src, re.S)
fonts = pathlib.Path('assets/fonts'); fonts.mkdir(parents=True, exist_ok=True)
out, seen = [], {}
for sub, body in blocks:
    if sub not in ('latin', 'latin-ext'):
        continue
    fam = re.search(r"font-family: '([^']+)'", body).group(1)
    style = re.search(r'font-style: (\w+)', body).group(1)
    url = re.search(r'url\((https://[^)]+)\)', body).group(1)
    slug = fam.lower().replace(' ', '-')
    # Google serves these as variable fonts: several weight blocks share one file
    name = f"{slug}-variable{'-italic' if style=='italic' else ''}-{sub}.woff2"
    if url not in seen:
        subprocess.run(['curl', '-sS', '-o', str(fonts / name), url], check=True)
        seen[url] = name
    out.append('@font-face {' + body.replace(url, f'../fonts/{seen[url]}') + '}')
# The @font-face rules live in style.css, between the markers below, so the
# site keeps to a single stylesheet and a single request. Writing them to a
# fonts.css nobody links would leave the live rules stale.
START = '/* --- generated font faces: fetch_fonts.sh --- */'
END = '/* --- end generated font faces --- */'
style = pathlib.Path('assets/css/style.css')
css = style.read_text()
block = START + '\n' + '\n'.join(out) + '\n' + END
if START in css and END in css:
    head, _, rest = css.partition(START)
    _, _, tail = rest.partition(END)
    style.write_text(head + block + tail)
    print(f'{len(out)} faces written into assets/css/style.css')
else:
    raise SystemExit(
        'assets/css/style.css has no generated-font-faces markers.\n'
        f'Add these around the @font-face rules and run this again:\n  {START}\n  {END}')
PY
