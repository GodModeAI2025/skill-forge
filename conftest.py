"""pytest-Konfiguration.

Liegt im Repo-Root und trägt das Root aktiv auf ``sys.path``. Ohne die
Einfügung sammelt die Suite nur ein, wenn pytest zufällig als
``python3 -m pytest`` aus genau diesem Verzeichnis gestartet wird; mit einem
absoluten Pfad oder aus einem anderen cwd brach die Collection mit
``ModuleNotFoundError: No module named 'scripts'`` ab.

Es gibt aus demselben Grund kein ``tests/__init__.py``.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
