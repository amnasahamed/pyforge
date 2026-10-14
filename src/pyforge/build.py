"""Trusted, isolated PyInstaller builds with cancellation and verified native output.

Builds are not a sandbox: PyInstaller hooks, imports, and project code can execute.
Process groups/Windows jobs clean up ordinary descendants, not deliberate escape:
POSIX children can detach and Windows job assignment follows unsuspended launch.
Inspection is separate and inert. Nothing here installs packages or edits a project.
"""

from __future__ import annotations

import json
import os
import plistlib
import queue
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import ExitStack, suppress
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, cast

from pyforge.config import BuildConfig
from pyforge.diagnostics import run_doctor
from pyforge.platform import expected_artifact

MAX_LOG_LINES = 1000
MAX_LOG_LINE_CHARS = 1024
MAX_PENDING_LOG_LINES = 128
REPORT_SCHEMA = 1


@dataclass(frozen=True)
class BuildEvent:
    """A worker-thread event; progress describes stages, not estimated elapsed time."""

    kind: str
    message: str
    progress: int | None = None


@dataclass(frozen=True)
class BuildResult:
    success: bool
    status: str
    artifact: Path | None = None
    run_dir: Path | None = None
    report_path: Path | None = None
    returncode: int | None = None
    elapsed_seconds: float = 0.0
    command: tuple[str, ...] = ()
    logs: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("artifact", "run_dir", "report_path"):
            data[key] = str(data[key]) if data[key] is not None else None
        data.update(schema_version=REPORT_SCHEMA, python=sys.executable)
        return data


class ArtifactError(ValueError):
    """A successful process did not produce the promised native artifact."""


def _is_macho_executable(handle: BinaryIO, offset: int = 0) -> bool:
    handle.seek(offset)
    header = handle.read(32)
    if len(header) < 28:
        return False
    endian = {
        b"\xfe\xed\xfa\xce": ">",
        b"\xce\xfa\xed\xfe": "<",
        b"\xfe\xed\xfa\xcf": ">",
        b"\xcf\xfa\xed\xfe": "<",
    }.get(header[:4])
    return bool(endian and struct.unpack_from(endian + "I", header, 12)[0] == 2)


def _verify_binary(path: Path, target: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ArtifactError(f"Expected a regular executable, not a missing file or symlink: {path}")
    with path.open("rb") as handle:
        header = handle.read(64)
        valid = False
        if target == "linux" and len(header) >= 52 and header[:4] == b"\x7fELF":
            elf_class, encoding = header[4:6]
            endian = {1: "<", 2: ">"}.get(encoding)
            valid = bool(
                elf_class in (1, 2)
                and endian
                and len(header) >= (64 if elf_class == 2 else 52)
                and struct.unpack_from(endian + "H", header, 16)[0] in (2, 3)
            )
        elif target == "windows" and len(header) == 64 and header[:2] == b"MZ":
            pe_offset = struct.unpack_from("<I", header, 60)[0]
            if 64 <= pe_offset <= path.stat().st_size - 26:
                handle.seek(pe_offset)
                pe = handle.read(26)
                flags = struct.unpack_from("<H", pe, 22)[0]
                valid = (
                    pe[:4] == b"PE\x00\x00"
                    and bool(flags & 0x0002)
                    and not bool(flags & 0x2000)
                    and struct.unpack_from("<H", pe, 24)[0] in (0x10B, 0x20B)
                )
        elif target == "macos":
            valid = _is_macho_executable(handle)
            fat = {
                b"\xca\xfe\xba\xbe": (">", False),
                b"\xbe\xba\xfe\xca": ("<", False),
                b"\xca\xfe\xba\xbf": (">", True),
                b"\xbf\xba\xfe\xca": ("<", True),
            }.get(header[:4])
            if fat and len(header) >= 8:
                endian, wide = fat
                count = struct.unpack_from(endian + "I", header, 4)[0]
                valid = 1 <= count <= 64
                stride = 32 if wide else 20
                for index in range(count if valid else 0):
                    handle.seek(8 + index * stride)
                    entry = handle.read(stride)
                    if len(entry) != stride:
                        valid = False
                        break
                    offset, size = struct.unpack_from(endian + ("QQ" if wide else "II"), entry, 8)
                    if (
                        offset < 8 + count * stride
                        or size < 28
                        or offset + size > path.stat().st_size
                        or not _is_macho_executable(handle, offset)
                    ):
                        valid = False
                        break
        if not valid:
            raise ArtifactError(f"Output is not a valid {target} executable header: {path}")
    if target != "windows" and not os.access(path, os.X_OK):
        raise ArtifactError(f"Output lacks executable permission: {path}")


def _windows_version_strings(path: Path) -> dict[str, str]:
    """Read resources via Win32 version APIs, never execute or import the artifact."""
    import ctypes
    from ctypes import wintypes

    api = cast(Any, ctypes).WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [
        wintypes.LPCVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    api.VerQueryValueW.restype = wintypes.BOOL
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size or size > 1024 * 1024:
        raise ArtifactError("Windows output has no readable native version resource.")
    data = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, data):
        raise ArtifactError("Cannot read Windows version resource.")
    result: dict[str, str] = {}
    for name in ("FileVersion", "ProductVersion", "FileDescription", "ProductName"):
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        key = "\\StringFileInfo\\040904b0\\" + name
        if (
            api.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length))
            and pointer.value
        ):
            result[name] = ctypes.wstring_at(pointer.value, max(0, length.value - 1))
    return result


def _windows_has_icon(path: Path) -> bool:
    """Check an RT_GROUP_ICON resource using data-only module loading."""
    import ctypes
    from ctypes import wintypes

    api = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    api.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    api.LoadLibraryExW.restype = wintypes.HMODULE
    api.FindResourceW.argtypes = [wintypes.HMODULE, wintypes.LPCWSTR, wintypes.LPCWSTR]
    api.FindResourceW.restype = wintypes.HANDLE
    api.FreeLibrary.argtypes = [wintypes.HMODULE]
    api.FreeLibrary.restype = wintypes.BOOL
    module = api.LoadLibraryExW(str(path), None, 0x00000002)  # LOAD_LIBRARY_AS_DATAFILE
    if not module:
        raise ArtifactError("Cannot inspect Windows icon resources as data.")
    try:
        # PyInstaller's icon copier assigns resource ID 1 to the first icon group.
        return bool(
            api.FindResourceW(
                module,
                ctypes.cast(ctypes.c_void_p(1), wintypes.LPCWSTR),
                ctypes.cast(ctypes.c_void_p(14), wintypes.LPCWSTR),
            )
        )
    finally:
        api.FreeLibrary(module)


def verify_artifact(config: BuildConfig, dist: Path, *, verify_metadata: bool = True) -> Path:
    """Verify expected layout and native headers, without launching the output."""
    artifact = expected_artifact(config, dist)
    if config.target == "macos" and not config.console:
        if artifact.is_symlink() or not artifact.is_dir():
            raise ArtifactError(f"Expected macOS .app directory: {artifact}")
        contents = artifact / "Contents"
        plist_path = contents / "Info.plist"
        if not plist_path.is_file() or plist_path.stat().st_size > 128 * 1024:
            raise ArtifactError("macOS bundle is missing a bounded Info.plist.")
        try:
            with plist_path.open("rb") as handle:
                info = plistlib.load(handle)
        except (ValueError, plistlib.InvalidFileException) as exc:
            raise ArtifactError(f"macOS Info.plist is invalid: {exc}") from exc
        if (
            not isinstance(info, dict)
            or info.get("CFBundleExecutable") != config.name
            or info.get("CFBundlePackageType") != "APPL"
        ):
            raise ArtifactError(
                "macOS bundle executable/package metadata does not match the configuration."
            )
        executable = contents / "MacOS" / config.name
        required_directories = [contents, contents / "MacOS", contents / "Resources"]
        if config.mode == "onedir":
            required_directories.append(contents / "Frameworks")
        if any(path.is_symlink() or not path.is_dir() for path in required_directories):
            raise ArtifactError("macOS bundle is missing Resources or Frameworks.")
        if verify_metadata:
            expected = {
                "CFBundleShortVersionString": config.version,
                "CFBundleVersion": config.version,
                "CFBundleGetInfoString": config.description,
            }
            if config.bundle_identifier:
                expected["CFBundleIdentifier"] = config.bundle_identifier
            if any(info.get(key) != value for key, value in expected.items()):
                raise ArtifactError(
                    "macOS bundle version/description/identifier metadata does not match the configuration."
                )
            if config.icon:
                icon_name = info.get("CFBundleIconFile")
                if not isinstance(icon_name, str) or Path(icon_name).name != icon_name:
                    raise ArtifactError("macOS icon resource name is invalid.")
                icon = contents / "Resources" / icon_name
                if icon.is_symlink() or not icon.is_file():
                    raise ArtifactError("macOS bundle is missing its native icon resource.")
                with icon.open("rb") as handle:
                    if handle.read(4) != b"icns":
                        raise ArtifactError("macOS icon resource is not ICNS data.")
    elif config.mode == "onedir":
        if (
            artifact.is_symlink()
            or not artifact.is_dir()
            or (artifact / "_internal").is_symlink()
            or not (artifact / "_internal").is_dir()
        ):
            raise ArtifactError(f"Expected onedir bundle with _internal dependencies: {artifact}")
        executable = artifact / (config.name + (".exe" if config.target == "windows" else ""))
    else:
        executable = artifact
    _verify_binary(executable, config.target)
    if verify_metadata and config.target == "windows" and os.name == "nt":
        info = _windows_version_strings(executable)
        expected = {
            "FileVersion": config.version,
            "ProductVersion": config.version,
            "FileDescription": config.description,
            "ProductName": config.name,
        }
        if any(info.get(key) != value for key, value in expected.items()):
            raise ArtifactError(
                "Windows native version/description metadata does not match the configuration."
            )
        if config.icon and not _windows_has_icon(executable):
            raise ArtifactError("Windows output is missing its native icon resource.")
    return artifact


def _write_spec(config: BuildConfig, temporary: Path) -> Path:
    """Generate our own spec from validated literals, never accept executable specs."""
    metadata = temporary / "pyforge-metadata.json"
    metadata.write_text(
        json.dumps(
            {"name": config.name, "version": config.version, "description": config.description},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    datas = [(str(metadata), "pyforge")]
    if config.icon and config.target == "linux":
        datas.append((str(config.icon), "pyforge"))
    lines = [
        "# Generated by PyForge; all user values are Python literals.",
        f"a = Analysis({[str(config.script)]!r}, pathex={[str(config.script.parent)]!r}, binaries=[], datas={datas!r}, hiddenimports={list(config.hidden_imports)!r}, hookspath=[], hooksconfig={{}}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)",
        "pyz = PYZ(a.pure)",
    ]
    arguments = (
        "pyz, a.scripts, a.binaries, a.datas, []"
        if config.mode == "onefile"
        else "pyz, a.scripts, []"
    )
    options: dict[str, Any] = {
        "name": config.name,
        "console": config.console,
        "debug": False,
        "strip": False,
        "upx": False,
        "bootloader_ignore_signals": False,
    }
    if config.mode == "onedir":
        options["exclude_binaries"] = True
        options["contents_directory"] = "_internal"
    if config.icon and config.target in ("windows", "macos"):
        options["icon"] = str(config.icon)
    if config.target == "windows":
        version_file = temporary / "windows-version.txt"
        parts = tuple(int(part) for part in config.version.split("."))
        parts += (0,) * (4 - len(parts))
        strings = {
            "FileDescription": config.description,
            "FileVersion": config.version,
            "InternalName": config.name,
            "OriginalFilename": config.name + ".exe",
            "ProductName": config.name,
            "ProductVersion": config.version,
        }
        table = ", ".join(f"StringStruct({key!r}, {value!r})" for key, value in strings.items())
        version_file.write_text(
            f"VSVersionInfo(ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), kids=[StringFileInfo([StringTable('040904b0', [{table}])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n",
            encoding="utf-8",
        )
        options["version"] = str(version_file)
    lines.append(
        f"exe = EXE({arguments}, "
        + ", ".join(f"{key}={value!r}" for key, value in options.items())
        + ")"
    )
    if config.mode == "onedir":
        lines.append(
            f"coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name={config.name!r})"
        )
    if config.target == "macos" and not config.console:
        info = {
            "CFBundleVersion": config.version,
            "CFBundleGetInfoString": config.description,
            "NSHighResolutionCapable": True,
        }
        lines.append(
            f"app = BUNDLE({'coll' if config.mode == 'onedir' else 'exe'}, name={config.name + '.app'!r}, icon={str(config.icon) if config.icon else None!r}, bundle_identifier={config.bundle_identifier or None!r}, version={config.version!r}, info_plist={info!r})"
        )
    path = temporary / "application.spec"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_linux_metadata(config: BuildConfig, artifact: Path) -> str | None:
    """Linux has no Windows-style embedded version/icon; ship actual desktop data."""
    destination = artifact if artifact.is_dir() else artifact.parent
    # App names cannot begin with a dot, so this directory cannot equal the ELF.
    # Reject an existing path instead of overwriting unexpected collected content.
    metadata_directory = destination / ".pyforge"
    metadata_directory.mkdir()
    metadata = {
        "name": config.name,
        "version": config.version,
        "description": config.description,
        "icon": None,
    }
    icon_path: Path | None = None
    if config.icon:
        icon_path = metadata_directory / "icon.png"
        shutil.copyfile(config.icon, icon_path)
        metadata["icon"] = ".pyforge/icon.png"
    (metadata_directory / "app-metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    executable = artifact / config.name if artifact.is_dir() else artifact
    if (
        any(
            ord(char) < 32 or ord(char) == 127
            for path in (executable, icon_path)
            if path
            for char in str(path)
        )
        or "=" in str(executable)
        or not str(executable).isascii()
    ):
        return "Desktop launcher omitted because the output path cannot be represented safely by the desktop Exec specification. The executable and JSON metadata are intact."
    # Desktop Exec has its own escaping rules; do not use shell quoting.
    escaped = (
        str(executable)
        .replace("\\", "\\\\\\\\")
        .replace('"', '\\\\"')
        .replace("`", "\\\\`")
        .replace("$", "\\\\$")
        .replace("%", "%%")
    )
    description = config.description.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
    entries = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={config.name}",
        f"Comment={description}",
        f'Exec="{escaped}"',
        f"Terminal={'true' if config.console else 'false'}",
        f"X-PyForge-Version={config.version}",
    ]
    if icon_path:
        escaped_icon = str(icon_path).replace("\\", "\\\\")
        entries.append(f"Icon={escaped_icon}")
    (destination / (config.name + ".desktop")).write_text(
        "\n".join(entries) + "\n", encoding="utf-8"
    )
    return None


def _failure_guidance(logs: deque[str]) -> tuple[str, ...]:
    text = "\n".join(logs).lower()
    guidance: list[str] = []
    for needles, recovery in (
        (
            ("no module named", "modulenotfounderror", "hidden import", "hiddenimport"),
            "The log may indicate a missing or dynamic import. Run Doctor, review the import, install only trusted requirements in this same virtual environment, or add an explicit hidden import. PyForge does not install anything.",
        ),
        (
            ("permission denied", "access is denied", "permissionerror"),
            "The log may indicate a permission or locked-file problem. Close running copies of the app and choose a writable output directory; do not disable system security.",
        ),
        (
            ("no space left", "disk full", "not enough space"),
            "The log may indicate exhausted storage. Free space in both the temporary and output filesystems or choose another output location.",
        ),
        (
            (
                "multiple qt",
                "attempting to collect multiple qt",
                "pyside6' while hook for",
                "pyqt6' while hook for",
            ),
            "The log may indicate conflicting Qt bindings. Keep one reviewed Qt binding in the project build environment and remove unintended optional imports.",
        ),
        (
            ("hookerror", "failed to execute script", "hook-"),
            "A hook or imported dependency may have failed. Inspect the traceback and the installed package/PyInstaller compatibility before changing the environment.",
        ),
        (
            ("upx",),
            "UPX compression is disabled by PyForge. If the log still references UPX, inspect dependency hooks and remove unsupported custom compression steps.",
        ),
    ):
        if any(needle in text for needle in needles):
            guidance.append(recovery)
    return tuple(guidance)


def _read_output(
    stream: BinaryIO, pending: queue.Queue[str], stop: threading.Event, dropped: list[int]
) -> None:
    partial = b""

    def offer(line: bytes) -> None:
        decoded = line.decode("utf-8", "replace").rstrip("\r")
        if len(decoded) > MAX_LOG_LINE_CHARS:
            dropped[0] += 1
        value = decoded[:MAX_LOG_LINE_CHARS]
        try:
            pending.put_nowait(value)
        except queue.Full:
            dropped[0] += 1
            with suppress(queue.Empty):
                pending.get_nowait()
            with suppress(queue.Full):
                pending.put_nowait(value)

    try:
        while not stop.is_set():
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            partial += chunk
            while b"\n" in partial:
                line, partial = partial.split(b"\n", 1)
                offer(line)
            if len(partial) > MAX_LOG_LINE_CHARS * 4:
                dropped[0] += 1
                offer(partial[:MAX_LOG_LINE_CHARS])
                partial = b""
        if partial:
            offer(partial)
    except (OSError, ValueError):
        pass
    finally:
        stream.close()


class _WindowsJob:
    """Own normal descendants even after the parent exits; this is not a sandbox.

    Assignment immediately follows Popen, before normal PyInstaller analysis, but
    is not atomic with launch: deliberately early/escaped children may evade it.
    """

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._api = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
        self._api.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._api.CreateJobObjectW.restype = wintypes.HANDLE
        self._api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._api.SetInformationJobObject.restype = wintypes.BOOL
        self._api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._api.AssignProcessToJobObject.restype = wintypes.BOOL
        self._api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._api.TerminateJobObject.restype = wintypes.BOOL
        self._api.CloseHandle.argtypes = [wintypes.HANDLE]
        self._api.CloseHandle.restype = wintypes.BOOL
        self._handle = self._api.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError(
                cast(Any, ctypes).get_last_error(), "Cannot create Windows build process Job Object"
            )
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = self._api.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        if not configured or not self._api.AssignProcessToJobObject(
            self._handle, cast(Any, process)._handle
        ):
            code = cast(Any, ctypes).get_last_error()
            self.close()
            raise OSError(code, "Cannot assign Windows build to a descendant-owning Job Object")

    def terminate(self) -> None:
        if self._handle:
            self._api.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        if self._handle:
            self._api.CloseHandle(self._handle)
            self._handle = None


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate the build's process group, including a parent's surviving children."""
    if os.name == "nt":
        # taskkill /T follows descendants, unlike Popen.terminate on Windows.
        taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=0.5)
        # Kill remaining descendants even if the immediate process already exited.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class BuildEngine:
    """One build at a time. Cancellation is sticky; use a fresh engine per GUI job.

    ``cancel`` is safe before or during ``build``. For explicit engine reuse after
    cancellation, call ``reset_cancellation`` after the previous build has finished.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._active = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()

    def reset_cancellation(self) -> None:
        if not self._active.acquire(blocking=False):
            raise RuntimeError("Cannot reset cancellation during a build.")
        try:
            self._cancelled.clear()
        finally:
            self._active.release()

    def build(
        self,
        config: BuildConfig,
        *,
        trusted: bool = False,
        on_event: Callable[[BuildEvent], None] | None = None,
    ) -> BuildResult:
        """Package explicitly trusted code with this interpreter and no shell/install."""
        if trusted is not True:
            return BuildResult(
                False,
                "untrusted",
                errors=(
                    "Building can execute project code and PyInstaller hooks. Review and trust the code explicitly before building.",
                ),
            )
        if not self._active.acquire(blocking=False):
            return BuildResult(
                False, "busy", errors=("This build engine already has an active build.",)
            )
        started = time.monotonic()
        run_dir: Path | None = None
        command: tuple[str, ...] = ()
        logs: deque[str] = deque(maxlen=MAX_LOG_LINES)
        warnings: list[str] = []
        process: subprocess.Popen[bytes] | None = None
        reader: threading.Thread | None = None
        windows_job: _WindowsJob | None = None
        stop_reader = threading.Event()
        dropped = [0]
        metadata: dict[str, Any] = {}
        tree_cleaned = False

        def emit(kind: str, message: str, progress: int | None = None) -> None:
            if on_event:
                # UI failures must not leave the owned subprocess running.
                with suppress(Exception):
                    on_event(BuildEvent(kind, message, progress))

        def terminate() -> None:
            if process:
                if windows_job:
                    windows_job.terminate()
                _terminate_process_tree(process)

        def cleanup_owned_tree() -> None:
            nonlocal tree_cleaned, windows_job
            if tree_cleaned:
                return
            stop_reader.set()
            try:
                if process and process.poll() is None:
                    terminate()
            finally:
                if windows_job:
                    windows_job.close()
                    windows_job = None
                elif process and os.name != "nt":
                    # Even an exited successful parent can leave descendants.
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                if reader:
                    reader.join(timeout=1)
            tree_cleaned = True

        def finish(
            status: str, *, artifact: Path | None = None, errors: tuple[str, ...] = ()
        ) -> BuildResult:
            # Stop owned descendants and close readers before announcing a result
            # or deleting their temporary spec/work/cache directories.
            cleanup_owned_tree()
            if dropped[0] or len(logs) == MAX_LOG_LINES:
                warnings.append(
                    "Build logs were truncated to bounded storage; the report contains the most recent retained lines."
                )
            report_path = run_dir / "build-report.json" if run_dir else None
            result = BuildResult(
                status == "success",
                status,
                artifact,
                run_dir,
                report_path,
                process.returncode if process else None,
                round(time.monotonic() - started, 3),
                command,
                tuple(logs),
                errors,
                tuple(dict.fromkeys(warnings)),
                metadata,
            )
            if report_path and run_dir:
                try:
                    payload = result.to_dict()
                    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
                    temporary_report = run_dir / ".build-report.json.tmp"
                    temporary_report.write_text(
                        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                    )
                    temporary_report.replace(report_path)
                except OSError as exc:
                    result = replace(
                        result,
                        success=False,
                        status="failed",
                        report_path=None,
                        errors=(*errors, f"Could not write build report: {exc}"),
                    )
            emit("finished", result.status, 100 if result.success else None)
            return result

        try:
            if self._cancelled.is_set():
                return finish("cancelled", errors=("Build cancelled before launch.",))
            emit("stage", "Validating configuration and current build environment", 5)
            errors = config.validate()
            if errors:
                return finish("invalid", errors=tuple(errors))
            config = config.normalized()
            doctor = run_doctor(config)
            warnings.extend(f.message for f in doctor.findings if f.severity == "warning")
            if not doctor.ok:
                return finish(
                    "preflight_failed",
                    errors=tuple(
                        f.message + " " + f.recovery
                        for f in doctor.findings
                        if f.severity == "error"
                    ),
                )
            if self._cancelled.is_set():
                return finish("cancelled", errors=("Build cancelled before launch.",))
            config.output_dir.mkdir(parents=True, exist_ok=True)
            run_dir = Path(tempfile.mkdtemp(prefix="pyforge-", dir=config.output_dir))
            dist = run_dir / "dist"
            metadata.update(
                name=config.name,
                version=config.version,
                description=config.description,
                target=config.target,
                mode=config.mode,
                console=config.console,
                script=str(config.script),
                bundle_identifier=config.bundle_identifier,
                icon=str(config.icon) if config.icon else None,
            )
            with ExitStack() as resources:
                directory = resources.enter_context(
                    tempfile.TemporaryDirectory(prefix="pyforge-build-")
                )
                # LIFO: terminate/close handles before TemporaryDirectory.__exit__,
                # including exceptions raised before a result can be constructed.
                resources.callback(cleanup_owned_tree)
                temporary = Path(directory)
                spec = _write_spec(config, temporary)
                command = (
                    sys.executable,
                    "-I",
                    "-m",
                    "PyInstaller",
                    "--noconfirm",
                    "--clean",
                    "--log-level",
                    "INFO",
                    "--distpath",
                    str(dist),
                    "--workpath",
                    str(temporary / "work"),
                    str(spec),
                )
                environment = os.environ.copy()
                for key in ("PYTHONPATH", "PYTHONHOME"):
                    environment.pop(key, None)
                environment["PYINSTALLER_CONFIG_DIR"] = str(temporary / "cache")
                environment["PYTHONUNBUFFERED"] = "1"
                emit("stage", "Building trusted code with PyInstaller", 15)
                if self._cancelled.is_set():
                    return finish("cancelled", errors=("Build cancelled before launch.",))
                process = subprocess.Popen(
                    command,
                    cwd=temporary,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    if os.name == "nt"
                    else 0,
                )
                if os.name == "nt":
                    windows_job = _WindowsJob(process)
                assert process.stdout is not None
                pending: queue.Queue[str] = queue.Queue(maxsize=MAX_PENDING_LOG_LINES)
                reader = threading.Thread(
                    target=_read_output,
                    args=(process.stdout, pending, stop_reader, dropped),
                    daemon=True,
                    name="pyforge-build-log",
                )
                reader.start()
                deadline = time.monotonic() + config.timeout
                exit_seen: float | None = None
                status: str | None = None
                while True:
                    if self._cancelled.is_set():
                        status = "cancelled"
                    elif time.monotonic() >= deadline:
                        status = "timeout"
                    if status:
                        emit("stage", "Stopping build and child processes")
                        terminate()
                    for _ in range(MAX_PENDING_LOG_LINES):
                        try:
                            line = pending.get_nowait()
                        except queue.Empty:
                            break
                        logs.append(line)
                        emit("log", line)
                    if status:
                        return finish(
                            status,
                            errors=(
                                "Build cancelled."
                                if status == "cancelled"
                                else f"Build exceeded the {config.timeout} second timeout.",
                            ),
                        )
                    if process.poll() is not None:
                        if not reader.is_alive() and pending.empty():
                            break
                        exit_seen = exit_seen or time.monotonic()
                        if time.monotonic() - exit_seen > 1:
                            terminate()
                            stop_reader.set()
                            break
                    time.sleep(0.05)
                if process.returncode != 0:
                    return finish(
                        "failed",
                        errors=(
                            f"PyInstaller exited with status {process.returncode}. Review retained logs and run Build Doctor.",
                            *_failure_guidance(logs),
                        ),
                    )
                emit("stage", "Verifying native artifact and metadata", 90)
                artifact = verify_artifact(config, dist)
                if config.target == "linux":
                    launcher_warning = _write_linux_metadata(config, artifact)
                    if launcher_warning:
                        warnings.append(launcher_warning)
                    # Verify again after writing sidecars: never report an ELF that
                    # was accidentally changed by metadata/launcher operations.
                    verify_artifact(config, dist)
                if self._cancelled.is_set():
                    return finish("cancelled", errors=("Build cancelled before completion.",))
                return finish("success", artifact=artifact)
        except KeyboardInterrupt:
            self.cancel()
            if process:
                terminate()
            return finish(
                "cancelled", errors=("Build interrupted; owned child processes were stopped.",)
            )
        except Exception as exc:
            if process and process.poll() is None:
                terminate()
            return finish("failed", errors=(str(exc),))
        finally:
            try:
                cleanup_owned_tree()
            finally:
                self._active.release()
