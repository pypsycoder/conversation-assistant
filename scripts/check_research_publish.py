"""Scan only explicitly staged text. Never read secrets or patient directories."""
import re
import subprocess
from pathlib import Path

git = r"C:\Program Files\Git\cmd\git.exe"
names = subprocess.check_output([git, "diff", "--cached", "--name-only", "--diff-filter=ACM"], text=True).splitlines()
for name in names:
    if name.startswith(("data/", "models/", "sessions/", "recordings/", ".env")):
        raise SystemExit("Forbidden staged path")
    text = subprocess.check_output([git, "show", ":" + name]).decode("utf-8")
    if re.search(r'(?i)(?:api[_-]?key|access_token|authorization)\s*[=:]\s*["\x27]([A-Za-z0-9_+/=-]{32,})', text):
        raise SystemExit("Potential literal credential in " + name)
print("Staged allowlist scan passed:", len(names), "text files; no data/models/env")
