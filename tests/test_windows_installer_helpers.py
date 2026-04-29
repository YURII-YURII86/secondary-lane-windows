from __future__ import annotations

import queue
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import second_lane_installer as installer


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_set_env_value_preserves_windows_backslashes() -> None:
    text = "WORKSPACE_ROOTS=old\nNGROK_PATH=old\n"

    text = installer.set_env_value(text, "WORKSPACE_ROOTS", r"C:\SecondLane")
    text = installer.set_env_value(text, "NGROK_PATH", r"C:\tools\ngrok.exe")

    assert r"WORKSPACE_ROOTS=C:\SecondLane" in text
    assert r"NGROK_PATH=C:\tools\ngrok.exe" in text


def test_ngrok_domain_validation_accepts_current_free_domains() -> None:
    assert installer.ngrok_domain_is_valid("team-name.ngrok-free.app")
    assert installer.ngrok_domain_is_valid("team-name.ngrok-free.dev")
    assert installer.ngrok_domain_is_valid("team-name.ngrok.app")
    assert installer.ngrok_domain_is_valid("agent.example.com")


def test_ngrok_domain_validation_rejects_placeholders_and_bad_text() -> None:
    assert not installer.ngrok_domain_is_valid("your-domain.ngrok-free.app")
    assert not installer.ngrok_domain_is_valid("your-domain.ngrok-free.dev")
    assert not installer.ngrok_domain_is_valid("not a domain")
    assert not installer.ngrok_domain_is_valid("https://")


def test_control_panel_normalizes_ngrok_domain_before_tunnel_start() -> None:
    import gpts_agent_control as control

    assert control.normalize_ngrok_domain("https://Team-Name.ngrok-free.app/") == "team-name.ngrok-free.app"
    panel = control.ControlPanel.__new__(control.ControlPanel)
    assert panel.ngrok_domain_is_placeholder("https://your-domain.ngrok-free.app/")


def test_step_env_creates_env_with_windows_ngrok_path() -> None:
    original_env_file = installer.ENV_FILE
    original_env_example_file = installer.ENV_EXAMPLE_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            tmp_path = Path(tmp)
            installer.ENV_FILE = tmp_path / ".env"
            installer.ENV_EXAMPLE_FILE = tmp_path / ".env.example"
            installer.ENV_EXAMPLE_FILE.write_text(
                "AGENT_TOKEN=replace-this-with-a-long-random-secret-token\n"
                "AGENT_HOST=0.0.0.0\n"
                "AGENT_PORT=8787\n"
                r"WORKSPACE_ROOTS=C:\SecondLane"
                "\n"
                "NGROK_DOMAIN=your-domain.ngrok-free.app\n"
                r"NGROK_PATH=C:\old\ngrok.exe"
                "\n",
                "utf-8",
            )

            app = installer.InstallerApp.__new__(installer.InstallerApp)
            app.workspace_root_var = _Var(str(tmp_path))
            app.worker_queue = queue.Queue()

            token = installer.InstallerApp._step_env(app, "demo.ngrok-free.app", r"C:\tools\ngrok.exe")
            env_text = installer.ENV_FILE.read_text("utf-8")

            assert installer.token_is_safe(token or "")
            assert f"AGENT_TOKEN={token}" in env_text
            assert f"WORKSPACE_ROOTS={tmp_path}" in env_text
            assert r"NGROK_PATH=C:\tools\ngrok.exe" in env_text
            assert ("step_state:env", "done") in list(app.worker_queue.queue)
        finally:
            installer.ENV_FILE = original_env_file
            installer.ENV_EXAMPLE_FILE = original_env_example_file
