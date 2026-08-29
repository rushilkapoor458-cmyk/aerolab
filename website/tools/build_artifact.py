"""
Single-file build of the Aurelia site.

Produces one self-contained .html with the stylesheet, the webfonts, the scripts
and every image inlined, so the page runs with zero network requests. That is
what makes it publishable as a Claude Artifact, whose CSP blocks every external
host, and it doubles as a portable copy you can email or open from a USB stick.

    python3 tools/build_artifact.py        # writes dist-single/aurelia.html

Differences from the deployed build, all forced by the single-file constraint:
  · webp only — the jpg fallbacks would double the payload for browsers that
    have supported webp for years;
  · the hero ships at one width instead of three, since srcset cannot pick a
    smaller file when all of them are already in the document;
  · the Google Maps embed becomes a link, because an iframe to another origin
    cannot load under the artifact CSP.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist-single"

import importlib.util
spec = importlib.util.spec_from_file_location("build", ROOT / "tools" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
minify_css = build.minify_css

# the hero is the only image that ships at several widths; one is enough here
SKIP = {"hero-900", "hero-2000", "og"}


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img_dir = ROOT / "assets" / "img"

    # ---- images ----------------------------------------------------------
    images = {p.stem: data_uri(p, "image/webp")
              for p in sorted(img_dir.glob("*.webp")) if p.stem not in SKIP}

    # ---- css, with the fonts folded in ----------------------------------
    css = (ROOT / "assets" / "css" / "style.css").read_text()
    for font in sorted((ROOT / "assets" / "fonts").glob("*.woff2")):
        css = css.replace(f"url(../fonts/{font.name})", f"url({data_uri(font, 'font/woff2')})")
    if "../fonts/" in css:
        raise SystemExit("a font url was left unresolved; the page would silently fall back")
    css = minify_css(css)

    # ---- page body -------------------------------------------------------
    html = (ROOT / "index.html").read_text()
    body = html.split("<body>", 1)[1].split("</body>", 1)[0]

    # the artifact host supplies the document skeleton, so the <head> content
    # goes with it — including the JSON-LD, which describes a domain this copy
    # does not live on.
    body = re.sub(r'<script src="assets/js/[^"]+"[^>]*></script>\s*', "", body)

    # one <img> per picture: the webp source and the jpg fallback would both be
    # inlined otherwise, doubling every image in the file
    body = re.sub(r'\s*<source[^>]*>', "", body)
    body = re.sub(r'</?picture>', "", body)
    body = re.sub(r'\s+(?:srcset|sizes)="[^"]*"', "", body)

    def swap(m: re.Match) -> str:
        name = m.group(1)
        if name in images:
            return images[name]
        if name.startswith("hero-"):
            return images["hero-1400"]
        raise SystemExit(f"no inlined image for {name}")

    body = re.sub(r'assets/img/([\w-]+)\.(?:jpg|webp)', swap, body)

    # ---- scripts ---------------------------------------------------------
    js_parts = []
    for name in ("data.js", "motion.js", "main.js"):
        js_parts.append((ROOT / "assets" / "js" / name).read_text())
    js = "\n".join(js_parts)

    # the img() helper builds paths at runtime; point it at the inlined map
    old_helper = """  const img = (name, alt, w, h, cls = '', eager = false) => `
    <picture>
      <source srcset="assets/img/${name}.webp" type="image/webp">
      <img src="assets/img/${name}.jpg" alt="${alt}" width="${w}" height="${h}" class="${cls}"
           ${eager ? '' : 'loading="lazy"'} decoding="async">
    </picture>`;"""
    new_helper = """  const img = (name, alt, w, h, cls = '', eager = false) =>
    `<img src="${window.__AURELIA_IMG[name] || ''}" alt="${alt}" width="${w}" height="${h}"
          class="${cls}" ${eager ? '' : 'loading="lazy"'} decoding="async">`;"""
    if old_helper not in js:
        raise SystemExit("the img() helper changed shape; update build_artifact.py")
    js = js.replace(old_helper, new_helper)

    js = js.replace("$('#lbImg').src = `assets/img/${g.img}.jpg`;",
                    "$('#lbImg').src = window.__AURELIA_IMG[g.img] || '';")

    # a cross-origin iframe cannot load here, so send people to the real map
    old_map = """  $('#loadMap') && $('#loadMap').addEventListener('click', () => {
    const wrap = $('.visit-map');
    const { lat, lng, name } = D.RESTAURANT;
    wrap.innerHTML =
      `<iframe title="Map showing Aurelia at 14 Ashford Lane, Bandra West, Mumbai" loading="lazy"
               referrerpolicy="no-referrer-when-downgrade"
               src="https://www.google.com/maps?q=${lat},${lng}&z=16&output=embed"></iframe>`;
  });"""
    new_map = """  // Single-file build: an embedded map is a cross-origin iframe, which cannot
  // load here, so the control opens the real map instead of failing silently.
  const mapBtn = $('#loadMap');
  if (mapBtn) {
    mapBtn.textContent = 'Open in Google Maps';
    mapBtn.addEventListener('click', () => {
      const { lat, lng } = D.RESTAURANT;
      window.open(`https://www.google.com/maps?q=${lat},${lng}&z=16`, '_blank', 'noopener');
    });
    const note = document.querySelector('.map-note');
    if (note) note.textContent = 'Opens in a new tab.';
  }"""
    if old_map not in js:
        raise SystemExit("the map loader changed shape; update build_artifact.py")
    js = js.replace(old_map, new_map)

    img_map = ",".join(f'"{k}":"{v}"' for k, v in images.items())

    # Standalone, nothing declares a document language, and inside the artifact
    # host we do not own the <html> tag either. Setting it from script covers
    # both, and the page is English in both.
    page = (
        "<title>Aurelia Fire Kitchen</title>\n"
        "<script>document.documentElement.lang='en';</script>\n"
        f"<style>{css}</style>\n"
        f"{body}\n"
        f"<script>window.__AURELIA_IMG={{{img_map}}};</script>\n"
        f"<script>{js}</script>\n"
    )

    target = OUT / "aurelia.html"
    target.write_text(page)
    mb = target.stat().st_size / 1e6
    print(f"{target}  ·  {len(images)} images inlined  ·  {mb:.2f} MB (artifact cap is 16 MB)")


if __name__ == "__main__":
    main()
