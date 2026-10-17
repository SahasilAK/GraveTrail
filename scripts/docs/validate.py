"""Check rendered links, anchors, project paths and the complete publication inventory."""
from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"])
        for key in ("href", "src"):
            if values.get(key):
                self.links.append(values[key])
        if values.get("srcset"):
            self.links.extend(item.strip().split()[0] for item in values["srcset"].split(","))


def inspect_site(site: Path, prefix: str) -> list[str]:
    pages = {path: Links(path.read_text(encoding="utf-8")) for path in site.rglob("*.html")}
    errors = []
    for page, parsed in pages.items():
        for link in parsed.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            path = unquote(url.path)
            if path.startswith("/"):
                if not path.startswith(prefix):
                    errors.append(f"{page.relative_to(site)}: missing project prefix: {link}")
                    continue
                target = site / path[len(prefix):]
            else:
                target = page.parent / path if path else page
            target = target.resolve()
            if not target.is_relative_to(site.resolve()):
                errors.append(f"{page.relative_to(site)}: outside site: {link}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{page.relative_to(site)}: missing target: {link}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                errors.append(f"{page.relative_to(site)}: missing anchor: {link}")
    # CSS resources are not HTML attributes, but must resolve too.
    for css in site.rglob("*.css"):
        for value in re.findall(r"url\([\"']?([^\)\"']+)", css.read_text(encoding="utf-8")):
            if not urlsplit(value).scheme and not value.startswith(("#", "//")):
                if not (css.parent / unquote(urlsplit(value).path)).is_file():
                    errors.append(f"{css.relative_to(site)}: missing CSS resource: {value}")
    return errors


def inspect_inventory(site: Path, expected: set[str], optional: set[str] | None = None) -> list[str]:
    actual = {path.relative_to(site).as_posix() for path in site.rglob("*") if path.is_file()}
    errors = [f"Unexpected publication file: {name}" for name in sorted(actual - expected - (optional or set()))]
    errors += [f"Missing publication file: {name}" for name in sorted(expected - actual)]
    errors += [f"Unsafe publication symlink: {path}" for path in site.rglob("*") if path.is_symlink()]
    return errors


def validate(config_path: Path, site: Path) -> None:
    import material
    from mkdocs.config import load_config

    from scripts.docs.hooks import nav_documents, page_output, public_files

    config = load_config(str(config_path))
    docs = set(nav_documents(config.nav))
    assets = set(config.extra["public_assets"])
    public_files(Path(config.docs_dir), docs | assets)
    expected = {page_output(name) for name in docs}
    expected |= assets | {"search/search_index.json", "sitemap.xml", "sitemap.xml.gz", "404.html"}
    theme = Path(material.__file__).parent / "templates"
    optional = {path.relative_to(theme).as_posix() for path in (theme / "assets").rglob("*") if path.is_file()}
    site = site.resolve()
    errors = inspect_inventory(site, expected, optional) + inspect_site(site, urlsplit(config.site_url).path)
    search = json.loads((site / "search/search_index.json").read_text(encoding="utf-8"))
    allowed_urls = {name.removesuffix("index.html") for name in expected if name.endswith(".html")}
    for item in search["docs"]:
        if urlsplit(item["location"]).path not in allowed_urls:
            errors.append(f"Unexpected search document: {item['location']}")
    if not search["docs"]:
        errors.append("Empty search index")
    # Check repository references without relying on the branch already being published.
    repo_prefix = config.repo_url + "/blob/main/"
    for source in [config_path.parent / "README.md", *(Path(config.docs_dir) / name for name in docs)]:
        import markdown
        rendered = markdown.markdown(source.read_text(encoding="utf-8"), extensions=["fenced_code", "tables"])
        for link in Links(rendered).links:
            if link.startswith(repo_prefix):
                target = config_path.parent / unquote(urlsplit(link[len(repo_prefix):]).path)
                if not target.exists():
                    errors.append(f"{source.name}: missing repository target: {link}")
            elif source.name == "README.md" and not urlsplit(link).scheme and not link.startswith("#"):
                target = source.parent / unquote(urlsplit(link).path)
                if not target.exists():
                    errors.append(f"README.md: missing target: {link}")
    if errors:
        raise SystemExit("Documentation validation failed:\n" + "\n".join(sorted(set(errors))))
    print(f"Validated {len(docs)} public pages, {len(assets)} assets, all rendered local links/anchors, "
          f"search and publication inventory ({len(search['docs'])} search entries).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    args = parser.parse_args()
    validate(Path(__file__).resolve().parents[2] / "mkdocs.yml", args.site_dir)
