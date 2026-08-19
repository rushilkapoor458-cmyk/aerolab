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
pathlib.Path('assets/css/fonts.css').write_text(
    "/* Self-hosted webfonts — latin and latin-ext subsets only.\n"
    "   Served from our own origin so there is no third-party request on first paint.\n"
    "   Regenerate with website/tools/fetch_fonts.sh. */\n\n" + '\n'.join(out) + '\n')
print(f'{len(out)} faces written')
PY
