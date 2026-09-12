"""Tests for the mobilerun bootstrap (detection + public-environment install)."""

import subprocess
import sys

import pytest

from mobilerun_autotest import bootstrap
from mobilerun_autotest.bootstrap import (
    MobilerunNotInstalled,
    MobilerunStatus,
    detect_mobilerun,
    ensure_mobilerun,
    python_version_supported,
    requirement_spec,
)


class TestPythonVersionSupported:
    def test_supported_range(self):
        assert python_version_supported((3, 11))
        assert python_version_supported((3, 12))
        assert python_version_supported((3, 13))

    def test_unsupported_range(self):
        assert not python_version_supported((3, 10))
        assert not python_version_supported((3, 14))

    def test_defaults_to_current_interpreter(self):
        expected = (3, 11) <= sys.version_info[:2] < (3, 14)
        assert python_version_supported() is expected


class TestRequirementSpec:
    def test_plain(self):
        assert requirement_spec() == "mobilerun"

    def test_with_extras(self):
        assert requirement_spec(extras="anthropic") == "mobilerun[anthropic]"

    def test_bare_version_becomes_floor(self):
        assert requirement_spec(version="0.6.17") == "mobilerun>=0.6.17"

    def test_explicit_operator_preserved(self):
        assert requirement_spec(version="==0.6.17") == "mobilerun==0.6.17"

    def test_extras_and_version(self):
        assert requirement_spec("anthropic", "0.6.17") == "mobilerun[anthropic]>=0.6.17"


class TestMobilerunStatus:
    def test_ok_requires_both_halves(self):
        assert MobilerunStatus(cli_path="/bin/mobilerun", importable=True).ok
        assert not MobilerunStatus(cli_path="/bin/mobilerun", importable=False).ok
        assert not MobilerunStatus(cli_path=None, importable=True).ok

    def test_summary_reports_missing(self):
        summary = MobilerunStatus().summary()
        assert "missing" in summary
        assert "not importable" in summary


class TestDetect:
    def test_detects_cli_and_package(self, monkeypatch):
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/mobilerun")
        monkeypatch.setattr(bootstrap, "_probe_cli_version", lambda p: "mobilerun v0.6.17")
        monkeypatch.setattr(bootstrap.importlib.util, "find_spec", lambda name: object())
        monkeypatch.setattr(bootstrap.importlib.metadata, "version", lambda name: "0.6.17")

        status = detect_mobilerun()

        assert status.ok
        assert status.cli_path == "/usr/bin/mobilerun"
        assert status.cli_version == "mobilerun v0.6.17"
        assert status.package_version == "0.6.17"

    def test_detects_nothing_installed(self, monkeypatch):
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)
        monkeypatch.setattr(bootstrap.importlib.util, "find_spec", lambda name: None)

        status = detect_mobilerun()

        assert not status.ok
        assert not status.cli_ok
        assert not status.importable

    def test_cli_only_install_is_not_ok(self, monkeypatch):
        """`uv tool install` yields an isolated CLI that is not importable."""
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/mobilerun")
        monkeypatch.setattr(bootstrap, "_probe_cli_version", lambda p: "mobilerun v0.6.17")
        monkeypatch.setattr(bootstrap.importlib.util, "find_spec", lambda name: None)

        status = detect_mobilerun()

        assert status.cli_ok
        assert not status.importable
        assert not status.ok

    def test_source_checkout_without_metadata_is_noted(self, monkeypatch):
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)
        monkeypatch.setattr(bootstrap.importlib.util, "find_spec", lambda name: object())

        def _raise(name):
            raise bootstrap.importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(bootstrap.importlib.metadata, "version", _raise)

        status = detect_mobilerun()

        assert status.importable
        assert status.package_version is None
        assert any("metadata" in n for n in status.notes)


def _fake_detect(cli: bool, lib: bool):
    return lambda: MobilerunStatus(
        cli_path="/usr/bin/mobilerun" if cli else None,
        cli_version="mobilerun v0.6.17" if cli else None,
        importable=lib,
        package_version="0.6.17" if lib else None,
    )


class TestEnsure:
    def test_noop_when_already_installed(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(True, True))
        monkeypatch.setattr(
            bootstrap,
            "install_mobilerun",
            lambda **kw: pytest.fail("must not install when already present"),
        )

        assert ensure_mobilerun().ok

    def test_installs_when_missing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(False, False))

        def _install(**kwargs):
            calls.append(kwargs)
            return _fake_detect(True, True)()

        monkeypatch.setattr(bootstrap, "install_mobilerun", _install)

        status = ensure_mobilerun(print_fn=lambda m: None)

        assert status.ok
        assert calls == [{
            "extras": None,
            "version": None,
            "need_cli": True,
            "need_library": True,
        }]

    def test_installs_only_the_missing_half(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(True, False))
        monkeypatch.setattr(
            bootstrap,
            "install_mobilerun",
            lambda **kw: (calls.append(kw), _fake_detect(True, True)())[1],
        )

        ensure_mobilerun(print_fn=lambda m: None)

        assert calls[0]["need_cli"] is False
        assert calls[0]["need_library"] is True

    def test_raises_with_instructions_when_auto_install_disabled(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(False, False))

        with pytest.raises(MobilerunNotInstalled) as exc:
            ensure_mobilerun(auto_install=False)

        msg = str(exc.value)
        assert "uv tool install mobilerun" in msg
        assert bootstrap.REPO_URL in msg

    def test_only_cli_required(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(True, False))
        monkeypatch.setattr(
            bootstrap,
            "install_mobilerun",
            lambda **kw: pytest.fail("CLI already present"),
        )

        ensure_mobilerun(need_library=False)


class TestInstallCommands:
    def test_prefers_uv_tool_install_for_cli(self, monkeypatch):
        monkeypatch.setattr(
            bootstrap.shutil, "which", lambda n: "/usr/bin/uv" if n == "uv" else None
        )
        cmds = bootstrap._cli_install_commands("mobilerun", upgrade=False)
        assert cmds == [["/usr/bin/uv", "tool", "install", "mobilerun"]]

    def test_falls_back_to_pipx(self, monkeypatch):
        monkeypatch.setattr(
            bootstrap.shutil, "which", lambda n: "/usr/bin/pipx" if n == "pipx" else None
        )
        cmds = bootstrap._cli_install_commands("mobilerun", upgrade=False)
        assert cmds == [["/usr/bin/pipx", "install", "mobilerun"]]

    def test_upgrade_forces(self, monkeypatch):
        monkeypatch.setattr(
            bootstrap.shutil, "which", lambda n: f"/usr/bin/{n}" if n in ("uv", "pipx") else None
        )
        cmds = bootstrap._cli_install_commands("mobilerun", upgrade=True)
        assert cmds[0][-1] == "--force"
        assert cmds[1][-1] == "--force"

    def test_no_installer_available(self, monkeypatch):
        monkeypatch.setattr(bootstrap.shutil, "which", lambda n: None)
        assert bootstrap._cli_install_commands("mobilerun", upgrade=False) == []

    def test_library_install_targets_user_site_outside_venv(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "_in_virtualenv", lambda: False)
        monkeypatch.setattr(bootstrap, "_pip_available", lambda: True)
        monkeypatch.setattr(bootstrap.shutil, "which", lambda n: None)
        cmds = bootstrap._library_install_commands("mobilerun", upgrade=False)
        assert cmds == [[sys.executable, "-m", "pip", "install", "--user", "mobilerun"]]

    def test_library_install_respects_active_venv(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "_in_virtualenv", lambda: True)
        monkeypatch.setattr(bootstrap, "_pip_available", lambda: True)
        monkeypatch.setattr(bootstrap.shutil, "which", lambda n: None)
        cmds = bootstrap._library_install_commands("mobilerun", upgrade=False)
        assert "--user" not in cmds[0]
        assert cmds[0][-1] == "mobilerun"

    def test_library_install_falls_back_to_uv_pip_without_pip(self, monkeypatch):
        """uv-created venvs commonly ship without pip."""
        monkeypatch.setattr(bootstrap, "_in_virtualenv", lambda: True)
        monkeypatch.setattr(bootstrap, "_pip_available", lambda: False)
        monkeypatch.setattr(
            bootstrap.shutil, "which", lambda n: "/usr/bin/uv" if n == "uv" else None
        )
        cmds = bootstrap._library_install_commands("mobilerun", upgrade=False)
        assert cmds == [["/usr/bin/uv", "pip", "install", "--python", sys.executable, "mobilerun"]]

    def test_library_install_has_no_candidates_without_pip_or_uv(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "_pip_available", lambda: False)
        monkeypatch.setattr(bootstrap.shutil, "which", lambda n: None)
        assert bootstrap._library_install_commands("mobilerun", upgrade=False) == []


class TestInstallMobilerun:
    def test_rejects_unsupported_python(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "python_version_supported", lambda: False)
        with pytest.raises(MobilerunNotInstalled, match="not supported"):
            bootstrap.install_mobilerun()

    def test_raises_when_install_leaves_target_missing(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "python_version_supported", lambda: True)
        monkeypatch.setattr(bootstrap, "_run_install", lambda argv, timeout=0: (1, "boom"))
        monkeypatch.setattr(
            bootstrap, "_cli_install_commands", lambda spec, upgrade: [["uv", "tool", "install", spec]]
        )
        monkeypatch.setattr(
            bootstrap, "_library_install_commands", lambda spec, upgrade: [["pip", "install", spec]]
        )
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(False, False))

        with pytest.raises(MobilerunNotInstalled) as exc:
            bootstrap.install_mobilerun()

        assert "boom" in str(exc.value)

    def test_succeeds_and_returns_status(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "python_version_supported", lambda: True)
        monkeypatch.setattr(bootstrap, "_run_install", lambda argv, timeout=0: (0, ""))
        monkeypatch.setattr(
            bootstrap, "_cli_install_commands", lambda spec, upgrade: [["uv", "tool", "install", spec]]
        )
        monkeypatch.setattr(
            bootstrap, "_library_install_commands", lambda spec, upgrade: [["pip", "install", spec]]
        )
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(True, True))

        assert bootstrap.install_mobilerun().ok

    def test_stops_after_first_successful_installer(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "python_version_supported", lambda: True)
        runs = []

        def _run(argv, timeout=0):
            runs.append(argv)
            return 0, ""

        monkeypatch.setattr(bootstrap, "_run_install", _run)
        monkeypatch.setattr(
            bootstrap,
            "_cli_install_commands",
            lambda spec, upgrade: [["uv", "x"], ["pipx", "y"]],
        )
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(True, True))

        bootstrap.install_mobilerun(need_library=False)

        assert runs == [["uv", "x"]]

    def test_missing_installer_reports_uv_instructions(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "python_version_supported", lambda: True)
        monkeypatch.setattr(bootstrap, "_cli_install_commands", lambda spec, upgrade: [])
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(False, True))

        with pytest.raises(MobilerunNotInstalled) as exc:
            bootstrap.install_mobilerun(need_library=False)

        assert "uv" in str(exc.value)


class TestSafeEmit:
    """Progress output must never be the reason bootstrapping fails."""

    def test_falls_back_to_ascii_on_gbk_console(self):
        seen = []

        def gbk_print(msg):
            msg.encode("gbk")  # raises on emoji, like a legacy Windows console
            seen.append(msg)

        bootstrap._safe_emit(gbk_print)("📥 installing mobilerun...")

        # retried with the emoji replaced, so the message still reaches the user
        assert seen == ["? installing mobilerun..."]

    def test_ascii_message_passes_through(self):
        seen = []
        bootstrap._safe_emit(seen.append)("installing")
        assert seen == ["installing"]

    def test_ensure_survives_unencodable_progress(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "detect_mobilerun", _fake_detect(False, False))
        monkeypatch.setattr(bootstrap, "install_mobilerun", lambda **kw: _fake_detect(True, True)())

        def gbk_print(msg):
            msg.encode("gbk")

        assert ensure_mobilerun(print_fn=gbk_print).ok


class TestRunInstall:
    def test_timeout_is_reported(self, monkeypatch):
        def _boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="uv", timeout=5)

        monkeypatch.setattr(bootstrap.subprocess, "run", _boom)
        code, out = bootstrap._run_install(["uv", "tool", "install", "mobilerun"], timeout=5)
        assert code == 124
        assert "timeout" in out

    def test_missing_binary_is_reported(self, monkeypatch):
        def _boom(*a, **kw):
            raise FileNotFoundError("no uv")

        monkeypatch.setattr(bootstrap.subprocess, "run", _boom)
        code, out = bootstrap._run_install(["uv"])
        assert code == 127
        assert "no uv" in out
