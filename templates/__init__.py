"""
⚡ Void Bot Builder — Templates Registry
────────────────────────────────────────
Drop any bot_name.py into this folder.
As long as it defines TEMPLATE_INFO and a class that inherits BaseTemplate,
it will be auto-discovered and appear in the builder menu — no other file
needs to be touched.
"""

import importlib
import pkgutil
import logging
from pathlib import Path

logger = logging.getLogger("Templates")

# ── Populated automatically at import time ─────────────────────────────────
BOT_TEMPLATES: dict = {}   # { template_id: TEMPLATE_INFO dict }
_CLASS_MAP:    dict = {}   # { template_id: TemplateClass }


def _discover():
    """Walk every .py file in this package and register templates."""
    pkg_dir = Path(__file__).parent
    for finder, mod_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if mod_name.startswith("_"):          # skip __init__, __pycache__ etc.
            continue
        try:
            mod = importlib.import_module(f"templates.{mod_name}")
            info  = getattr(mod, "TEMPLATE_INFO", None)
            klass = getattr(mod, "Template",      None)
            if info and klass:
                tid = info["id"]
                BOT_TEMPLATES[tid] = info
                _CLASS_MAP[tid]    = klass
                logger.info(f"  ✅ Template registered: [{tid}] {info['name']}")
            else:
                logger.warning(f"  ⚠️  {mod_name}.py skipped — missing TEMPLATE_INFO or Template class")
        except Exception as e:
            logger.error(f"  ❌ Failed to load template '{mod_name}': {e}")


_discover()


# ── Public helpers used by main.py & bot_manager.py ───────────────────────

def get_template_info(tid: str) -> dict | None:
    """Return the TEMPLATE_INFO dict for a given template id."""
    return BOT_TEMPLATES.get(tid)


def get_template_class(tid: str):
    """Return the Template class for a given template id, or None."""
    return _CLASS_MAP.get(tid)
