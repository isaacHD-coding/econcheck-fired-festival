"""Subprocess-backed execution for worker-generated analysis code."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from typing import Any

from workers.artifacts import AnalysisArtifact, CodeArtifact


DEFAULT_TIMEOUT_SECONDS = 5


def run_analysis_code(
    code_artifact: CodeArtifact,
    data_artifact: Any,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    output_log_path: str | Path | None = None,
) -> AnalysisArtifact:
    with tempfile.TemporaryDirectory(prefix="econcheck-analysis-") as sandbox_dir:
        sandbox_path = Path(sandbox_dir)
        input_path = sandbox_path / "input.json"
        output_path = sandbox_path / "analysis_output.json"
        runner_path = sandbox_path / "runner.py"

        input_path.write_text(
            json.dumps(
                {
                    "code": code_artifact.code,
                    "input_data": _artifact_to_dict(data_artifact),
                    "output_path": str(output_path),
                },
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        runner_path.write_text(_child_runner_source(input_path), encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, str(runner_path)],
                cwd=sandbox_path,
                env=_sandbox_environment(sandbox_path),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _write_output_log(
                output_log_path,
                {
                    "returncode": None,
                    "stdout": _decode_timeout_output(exc.stdout),
                    "stderr": _decode_timeout_output(exc.stderr),
                    "timed_out": True,
                },
            )
            raise TimeoutError(
                f"analysis code timed out after {timeout_seconds} seconds"
            ) from exc

        _write_output_log(
            output_log_path,
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timed_out": False,
            },
        )

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                "analysis code failed with exit code "
                f"{completed.returncode}: {stderr}"
            )

        return AnalysisArtifact.from_dict(
            json.loads(output_path.read_text(encoding="utf-8"))
        )


def _artifact_to_dict(artifact: Any) -> dict[str, Any]:
    if hasattr(artifact, "to_dict"):
        data = artifact.to_dict()
    elif is_dataclass(artifact):
        data = asdict(artifact)
    elif isinstance(artifact, dict):
        data = artifact
    else:
        data = vars(artifact)

    if not isinstance(data, dict):
        raise TypeError("data_artifact must serialize to a dict")
    return data


def _write_output_log(output_log_path: str | Path | None, data: dict[str, Any]) -> None:
    if output_log_path is None:
        return
    path = Path(output_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _sandbox_environment(sandbox_path: Path) -> dict[str, str]:
    env = {
        "MPLCONFIGDIR": str(sandbox_path),
        "PYTHONNOUSERSITE": "1",
    }
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    return env


def _child_runner_source(input_path: Path) -> str:
    return textwrap.dedent(
        f"""
        from __future__ import annotations

        import builtins
        import json
        import os
        from pathlib import Path
        import socket
        import subprocess


        _SANDBOX_ROOT = Path.cwd().resolve()
        _ORIGINAL_OPEN = builtins.open


        def _is_inside_sandbox(path):
            try:
                path.resolve().relative_to(_SANDBOX_ROOT)
            except ValueError:
                return False
            return True


        def _safe_open(file, mode="r", *args, **kwargs):
            if isinstance(file, int):
                return _ORIGINAL_OPEN(file, mode, *args, **kwargs)

            path = Path(file)
            if not path.is_absolute():
                path = _SANDBOX_ROOT / path
            if not _is_inside_sandbox(path):
                raise PermissionError("analysis sandbox blocks file access outside cwd")
            return _ORIGINAL_OPEN(path, mode, *args, **kwargs)


        def _safe_path_open(
            self,
            mode="r",
            buffering=-1,
            encoding=None,
            errors=None,
            newline=None,
        ):
            return _safe_open(
                self,
                mode,
                buffering,
                encoding=encoding,
                errors=errors,
                newline=newline,
            )


        def _blocked(*args, **kwargs):
            raise PermissionError("analysis sandbox blocks this operation")


        builtins.open = _safe_open
        Path.open = _safe_path_open
        os.chdir = _blocked
        os.open = _blocked
        os.system = _blocked
        os.popen = _blocked
        socket.socket = _blocked
        socket.create_connection = _blocked
        subprocess.Popen = _blocked
        subprocess.run = _blocked
        subprocess.call = _blocked
        subprocess.check_call = _blocked
        subprocess.check_output = _blocked

        with _ORIGINAL_OPEN({str(input_path)!r}, "r", encoding="utf-8") as input_file:
            payload = json.load(input_file)

        globals_dict = {{"input_data": payload["input_data"]}}
        exec(compile(payload["code"], "<generated_analysis>", "exec"), globals_dict)

        analysis_output = globals_dict.get("analysis_output")
        if not isinstance(analysis_output, dict):
            raise RuntimeError("generated code must assign analysis_output as a dict")

        with _safe_open(payload["output_path"], "w", encoding="utf-8") as output_file:
            json.dump(analysis_output, output_file, allow_nan=False)
        """
    )
