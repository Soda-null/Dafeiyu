"""Windows: run `fish wechat` or `fish nightly` with no console window (install.ps1 starts it
through the venv's pythonw.exe). Output goes to data/logs/<command>.log; WeChat comes back by
itself after a crash, like KeepAlive on the Mac and Restart= on Linux."""

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_LIMIT = 5_000_000  # bytes; the old log is kept once as .old

command = sys.argv[1] if len(sys.argv) > 1 else "wechat"
logs = ROOT / "data" / "logs"
logs.mkdir(parents=True, exist_ok=True)
path = logs / f"{command}.log"
if path.exists() and path.stat().st_size > LOG_LIMIT:
    path.replace(path.with_suffix(".log.old"))
sys.stdout = sys.stderr = open(path, "a", encoding="utf-8", buffering=1)

from fish.__main__ import main  # noqa: E402  (after the log is in place, so import errors land in it)

while True:
    print(f"== {time.strftime('%Y-%m-%d %H:%M:%S')} fish {command} ==")
    try:
        main([command])
    except SystemExit as e:  # not bound to WeChat yet, or a clean stop: do not loop
        print(f"stopped: {e}")
        raise
    except Exception:
        traceback.print_exc()
        if command != "wechat":
            raise
        time.sleep(30)
        continue
    if command != "wechat":
        break
