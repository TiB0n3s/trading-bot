#!/usr/bin/env python3
"""Ensure the fill stream is active during regular market hours.

The preferred runtime is the systemd ``fill-stream`` unit. If that unit is
inactive and the operator account cannot start system services without sudo,
this guard starts ``scripts/fill_stream.py`` directly under the tradingbot user.
It keeps a PID file so weekend/after-hours cron can stop only the fallback
process it created.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from market_time import is_market_hours, now_et

ENV_FILE = Path("/etc/trading-bot.env")
PID_FILE = ROOT / "runtime_state" / "fill_stream_runtime.pid"
RUNTIME_LOG = ROOT / "fill_stream_runtime.log"
FILL_STREAM_SCRIPT = ROOT / "scripts" / "fill_stream.py"
VENV_PYTHON = ROOT / "venv" / "bin" / "python"


def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    if not ENV_FILE.exists():
        return env

    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def _systemd_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "fill-stream"],
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0


def _pid_from_file() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _pid_is_fill_stream(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        cmdline = proc_cmdline.read_text(errors="replace").replace("\x00", " ")
    except Exception:
        return False
    return "scripts/fill_stream.py" in cmdline or "fill_stream.py" in cmdline


def _fallback_active() -> bool:
    return _pid_is_fill_stream(_pid_from_file())


def _start_fallback() -> int:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    python = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    env = _load_env()
    python_path = os.pathsep.join([str(ROOT), str(ROOT / "scripts"), str(ROOT / "src")])
    env["PYTHONPATH"] = (
        python_path if not env.get("PYTHONPATH") else f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    with RUNTIME_LOG.open("a") as log:
        proc = subprocess.Popen(
            [str(python), str(FILL_STREAM_SCRIPT)],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(f"{proc.pid}\n")
    return proc.pid


def _stop_fallback() -> bool:
    pid = _pid_from_file()
    if not _pid_is_fill_stream(pid):
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
        return False

    assert pid is not None
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    for _ in range(20):
        if not _pid_is_fill_stream(pid):
            break
        time.sleep(0.25)

    if _pid_is_fill_stream(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass
    return True


def ensure() -> int:
    if not is_market_hours(now_et()):
        stopped = _stop_fallback()
        suffix = " stopped_fallback=true" if stopped else ""
        print(f"fill-stream skipped: outside_regular_market_hours{suffix}")
        return 0

    if _systemd_active():
        print("fill-stream active: systemd")
        return 0

    if _fallback_active():
        print(f"fill-stream active: fallback pid={_pid_from_file()}")
        return 0

    pid = _start_fallback()
    print(f"WARNING: fill-stream systemd inactive; started fallback pid={pid}")
    return 0


def stop() -> int:
    stopped = _stop_fallback()
    print(f"fill-stream fallback stopped={str(stopped).lower()}")
    return 0


def status() -> int:
    if _systemd_active():
        print("fill-stream active: systemd")
        return 0
    if _fallback_active():
        print(f"fill-stream active: fallback pid={_pid_from_file()}")
        return 0
    print("WARNING: fill-stream is not active")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ensure", action="store_true", help="Start fallback during market hours.")
    mode.add_argument("--stop", action="store_true", help="Stop only the fallback process.")
    mode.add_argument("--status", action="store_true", help="Report active status.")
    args = parser.parse_args(argv)

    if args.stop:
        return stop()
    if args.status:
        return status()
    return ensure()


if __name__ == "__main__":
    raise SystemExit(main())
