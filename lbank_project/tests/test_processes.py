"""Real subprocess smoke test; no exchange or external network access."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("filename", ["baseline_config.json", "../config.json"])
def test_bot_and_dashboard_processes(tmp_path, filename):
    config = json.loads((ROOT / "tests" / filename).read_text())
    config["bot_control"]["check_interval_seconds"] = 1
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    env = {**os.environ, "BOT_CONFIG": str(config_path),
        "BOT_DB": str(tmp_path / "lbank_ichimoku_bot.db"),
        "BOT_PIN": "process-test-pin", "PAPER_DATA_MODE": "demo", "PYTHONPATH": os.pathsep.join(str(Path(x).resolve()) for x in os.environ.get("PYTHONPATH", "").split(os.pathsep) if x)}
    auth = {"X-Bot-Pin": "process-test-pin"}
    with (tmp_path / "bot.log").open("w+") as bot_log, (tmp_path / "dashboard.log").open("w+") as dashboard_log:
        bot = subprocess.Popen([sys.executable, "-u", "lbank_bot.py"], cwd=ROOT,
                               env=env, stdout=bot_log, stderr=subprocess.STDOUT)
        dashboard = subprocess.Popen([sys.executable, "-m", "uvicorn", "dashboard_server:app",
            "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
            stdout=dashboard_log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + 15
                status = None
                while time.monotonic() < deadline:
                    assert bot.poll() is None and dashboard.poll() is None
                    try:
                        response = client.get("/api/status", headers=auth)
                        if response.status_code == 200:
                            status = response.json()
                            if status["runtime"].get("watchdog_at") and status["runtime"].get("scanner_at"):
                                break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                assert status and "scanner_at" in status["runtime"]
                assert status["data_mode"] == "demo"
                assert time.time() - status["runtime"]["watchdog_at"] < 5
                assert client.get("/").status_code == 200
                assert client.get("/api/status").status_code == 401
                current = client.get("/api/config", headers=auth)
                changed = current.json()
                changed["bot_control"]["auto_trade_enabled"] = False
                assert client.put("/api/config", headers={**auth, "If-Match": current.headers["etag"]}, json=changed).status_code == 200
                assert json.loads(config_path.read_text())["bot_control"]["auto_trade_enabled"] is False
                panic = client.post("/api/positions/close-all", headers=auth, json={"disable_auto_trade": True})
                assert panic.status_code == 200
                assert panic.json()["remaining_positions"] == 0
                assert not panic.json()["errors"]
        finally:
            for process in (bot, dashboard):
                process.terminate()
            for process in (bot, dashboard):
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
