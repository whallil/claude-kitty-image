"""Make the skill's scripts importable by name in tests.

The skill dir contains plain scripts (show.py, mermaid.py, _chrome.py, html.py),
not an installable package, and its path has a hyphen — so tests put the skill
dir on sys.path and import the modules directly.

IMPORTANT: the skill dir contains a sibling `html.py`, which would shadow the
stdlib `html` module once the dir is on sys.path. We import stdlib `html` FIRST
so it is cached in sys.modules; any later bare `import html` (by a test, a pytest
plugin, or a transitively imported library, e.g. for html.escape) then keeps
resolving to the stdlib, not the skill script. The skill's own html.py is loaded
explicitly by file path under the alias `htmlpy` (see test_html.py).
"""
import sys
from pathlib import Path

import html  # noqa: F401  # cache stdlib html BEFORE the skill dir goes on sys.path

SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
