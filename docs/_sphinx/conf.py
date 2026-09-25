"""Sphinx config for the docs site (dev-only; never in the image, R5). Build: `make docs`.

Source dir is `docs/`, this folder is only the config dir (`sphinx-build -c docs/_sphinx`), so
`docs/INDEX.md` (the agents' router) and the site root `docs/SITE.md` never clash.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

project = "Radiology Workbench"
author = "Radiology Workbench contributors"
extensions = ["myst_parser", "reqs"]
myst_enable_extensions = ["colon_fence", "deflist"]  # no `linkify`: `.md` is a TLD (AUD-A7-05)
myst_heading_anchors = 3
root_doc = "SITE"
source_suffix = {".md": "markdown"}
exclude_patterns = [
    "archive/**",
    "audit/**",
    "_sphinx/**",
    "INDEX.md",
    "ops/AGENT_RUNBOOK.md",
    "**/.DS_Store",
]
templates_path = ["_templates"]
html_additional_pages = {"index": "redirect.html"}
html_theme = "furo"
html_title = "Radiology Workbench"
html_logo = "../brand/logo-master.png"
html_show_sphinx = False
html_copy_source = False
html_show_sourcelink = False


def setup(app):
    from pygments.lexers import JsonLexer

    app.add_lexer("jsonc", JsonLexer)  # JSON with comments in the domain docs
