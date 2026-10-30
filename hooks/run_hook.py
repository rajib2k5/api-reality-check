"""Hook entry point: python3 -I -S -B "${CLAUDE_PLUGIN_ROOT}/hooks/run_hook.py".

Works without the package being installed: puts <plugin root>/src first on sys.path. Kept free
of newer syntax so that an old python3 can still report that it is too old.
"""
import json
import os
import sys

sys.dont_write_bytecode = True

if sys.version_info < (3, 10):
    sys.stdout.write(json.dumps({"systemMessage": "api-reality-check: the hook needs Python >= 3.10 "
                                 "(python3 is %d.%d)" % sys.version_info[:2]}))
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from api_reality_check.hook import main  # noqa: E402

sys.exit(main())
