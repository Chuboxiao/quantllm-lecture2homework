"""Check curated local links and pinned source references without importing trading code."""

import ast
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    errors = []
    pages = list((ROOT / "wiki").rglob("*.md"))
    docs = pages + [ROOT / n for n in ("README.md", "Agent.md", "AGENTS.md")]
    for folder in ("projects", "configs", "reports"):
        docs.extend((ROOT / folder).rglob("*.md"))
    docs.append(ROOT / "raw/README.md")
    links = 0
    for doc in docs:
        text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            links += 1
            if not (doc.parent / unquote(parsed.path)).exists():
                errors.append(f"Missing link: {doc.relative_to(ROOT)} -> {target}")

    index = (ROOT / "wiki/index.md").read_text()
    for page in pages:
        if page.name != "index.md" and str(page.relative_to(ROOT / "wiki")) not in index:
            errors.append(f"Not indexed: {page.relative_to(ROOT)}")

    manifest_path = ROOT / "raw/source-manifest.json"
    if not manifest_path.exists():
        errors.append("Missing source-manifest.json")
        manifest = {"repositories": [], "references": []}
    else:
        manifest = json.loads(manifest_path.read_text())

    for repo in manifest["repositories"]:
        for item in repo["read_files"]:
            path = ROOT / repo["local_path"] / item["path"]
            if not path.exists():
                errors.append(f"Missing source: {path}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                errors.append(f"Source changed: {path}")

    for item in manifest["references"]:
        path = ROOT / "raw/repos" / item["repo"] / item["path"]
        if not path.exists():
            continue
        symbol = item["symbol"]
        if not symbol:
            continue
        try:
            nodes = ast.parse(path.read_text()).body
            for part in symbol.split("."):
                node = next(
                    n for n in nodes
                    if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == part
                )
                nodes = node.body
            if node.lineno != item["line"]:
                errors.append(f"Source line changed: {item['repo']} {symbol}")
        except (StopIteration, SyntaxError) as exc:
            errors.append(f"Invalid source reference: {symbol}: {exc}")

    for item in json.loads((ROOT / "raw/materials-manifest.json").read_text()):
        path = ROOT / item["file"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            errors.append(f"Source material changed: {item['file']}")

    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {len(pages)} wiki pages, {links} local links, "
          f"{len(manifest['references'])} source references; source/material hashes match.")
    print("Scope: link paths, index coverage, source symbols/lines, and hashes. "
          "Not a trading runtime test or semantic proof of all notes.")


if __name__ == "__main__":
    main()
