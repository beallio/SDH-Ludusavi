import subprocess
import json
import logging
from typing import Any, Optional, Literal, Dict, TypeVar, Generic
from dataclasses import dataclass

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LudusaviError(Exception):
    """Base exception for pyludusavi."""

    pass


class LudusaviExecutionError(LudusaviError):
    """Raised when the Ludusavi process exits with a non-zero code."""

    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Ludusavi command {command} failed with exit code {returncode}: {stderr}")


class LudusaviContractError(LudusaviError):
    """Raised when the Ludusavi output does not match the expected contract (e.g. invalid JSON)."""

    pass


@dataclass
class LudusaviResponse(Generic[T]):
    """Container for Ludusavi command responses."""

    data: T
    raw: Any
    warnings: str
    command: list[str]


class LudusaviExecutor:
    """Engine for executing Ludusavi commands across different modes."""

    def __init__(self, command_prefix: list[str]):
        self.command_prefix = command_prefix

    def execute(
        self,
        args: list[str],
        mode: Literal["JSON", "TEXT", "SPAWN", "STDIN_JSON"] = "JSON",
        input_data: Optional[Any] = None,
        timeout: Optional[float] = 30.0,
        env: Optional[Dict[str, str]] = None,
        auto_api: bool = True,
    ) -> Optional[LudusaviResponse]:
        """
        Execute a Ludusavi command.

        Args:
            args: Subcommand and flags.
            mode: Execution mode (JSON, TEXT, SPAWN, STDIN_JSON).
            input_data: Dictionary to be sent via stdin (only for STDIN_JSON).
            timeout: Maximum time to wait for the process.
            env: Environment variables for the subprocess.
            auto_api: If True, automatically appends --api to JSON/STDIN_JSON modes.

        Returns:
            LudusaviResponse or None (for SPAWN mode).
        """
        full_cmd = self.command_prefix + args

        # Append --api if mode involves JSON parsing
        if auto_api and mode in ["JSON", "STDIN_JSON"] and "--api" not in full_cmd:
            full_cmd.append("--api")

        logger.debug(f"Executing Ludusavi command: {full_cmd}")

        if mode == "SPAWN":
            subprocess.Popen(full_cmd, env=env)
            return None

        stdin_content = None
        if mode == "STDIN_JSON" and input_data is not None:
            stdin_content = json.dumps(input_data)

        try:
            result = subprocess.run(
                full_cmd,
                input=stdin_content,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise LudusaviError(f"Ludusavi command timed out after {timeout}s: {full_cmd}") from e

        if result.returncode != 0:
            raise LudusaviExecutionError(full_cmd, result.returncode, result.stdout, result.stderr)

        if mode in ["JSON", "STDIN_JSON"]:
            try:
                data = json.loads(result.stdout)
                return LudusaviResponse(
                    data=data, raw=data, warnings=result.stderr, command=full_cmd
                )
            except json.JSONDecodeError as e:
                raise LudusaviContractError(
                    f"Failed to parse Ludusavi JSON output: {result.stdout}"
                ) from e

        # mode == "TEXT"
        return LudusaviResponse(
            data=result.stdout, raw=result.stdout, warnings=result.stderr, command=full_cmd
        )
