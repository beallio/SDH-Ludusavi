from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def environment(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "mkdir").symlink_to("/usr/bin/mkdir")
    cargo = tmp_path / "cargo"
    cargo.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$CC_x86_64_unknown_linux_musl" '
        '"$CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER"\n'
    )
    cargo.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    env.pop("CC_x86_64_unknown_linux_musl", None)
    env.pop("CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER", None)
    return env


def test_musl_build_reports_missing_compiler(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "run.sh"),
            "cargo",
            "build",
            "--target",
            "x86_64-unknown-linux-musl",
        ],
        env=environment(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "musl-gcc" in result.stderr and "musl-tools" in result.stderr


def test_musl_build_uses_standard_compiler_for_cc_and_linker(tmp_path: Path) -> None:
    env = environment(tmp_path)
    compiler = tmp_path / "musl-gcc"
    compiler.write_text("#!/bin/sh\nexit 0\n")
    compiler.chmod(0o755)
    result = subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "run.sh"),
            "cargo",
            "build",
            "--target",
            "x86_64-unknown-linux-musl",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines()[-2:] == [str(compiler), str(compiler)]


def test_explicit_compiler_is_respected_and_other_cargo_commands_need_no_musl(
    tmp_path: Path,
) -> None:
    env = environment(tmp_path)
    compiler = tmp_path / "custom-compiler"
    compiler.write_text("#!/bin/sh\nexit 0\n")
    compiler.chmod(0o755)
    subprocess.run(["/bin/bash", str(ROOT / "run.sh"), "cargo", "fmt"], env=env, check=True)
    env["CC_x86_64_unknown_linux_musl"] = str(compiler)
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "run.sh"), "cargo", "build", "--target=x86_64-unknown-linux-musl"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines()[-2:] == [str(compiler), str(compiler)]
