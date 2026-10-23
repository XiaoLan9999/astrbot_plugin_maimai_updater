from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maimai_official_interface.local_runtime import is_arm64_linux, prepared_runtime, runtime_home
from maimai_official_interface.wine_bridge import WineBridgeError, WineChimeBridge


HANGOVER_VERSION = "11.16"
RUNTIME_URL = (
    "https://github.com/AndreRH/hangover/releases/download/hangover-11.16/"
    "hangover_11.16_ubuntu2404_noble_arm64.tar"
)
RUNTIME_SHA256 = "94611dad2b23978d35825a018c81b3947caaec174aa04c052849d37bc6a39e72"
VC_URL = (
    "https://download.visualstudio.microsoft.com/download/pr/7ebf5fdb-36dc-4145-b0a0-90d3d5990a61/"
    "CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B/VC_redist.x64.exe"
)
VC_SHA256 = "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b"
PACKAGES = (
    "hangover-wine_11.16~noble_arm64.deb",
    "hangover-libwow64fex_11.16_arm64.deb",
    "hangover-libarm64ecfex_11.16_arm64.deb",
    "hangover-wowbox64_11.16_arm64.deb",
)


class SetupError(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def download(url: str, path: Path, expected: str) -> None:
    if path.is_file() and digest(path) == expected:
        return
    temporary = path.with_suffix(path.suffix + ".part")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target, length=1024 * 1024)
            if digest(temporary) != expected:
                raise SetupError("download_checksum_mismatch")
            temporary.replace(path)
            return
        except OSError:
            if attempt == 2:
                raise SetupError("download_failed") from None
            time.sleep(1)


def extract_packages(archive: Path, directory: Path) -> list[Path]:
    if digest(archive) != RUNTIME_SHA256:
        raise SetupError("runtime_checksum_mismatch")
    found = {}
    with tarfile.open(archive) as source:
        for member in source:
            if member.name not in PACKAGES:
                continue
            if not member.isfile() or member.name in found:
                raise SetupError("invalid_runtime_archive")
            target = directory / member.name
            with source.extractfile(member) as data, target.open("wb") as output:
                shutil.copyfileobj(data, output)
            found[member.name] = target
    if set(found) != set(PACKAGES):
        raise SetupError("incomplete_runtime_archive")
    return [found[name] for name in PACKAGES]


def run(command: list[str], *, environment: dict[str, str], timeout: int = 900, accepted=(0,)) -> None:
    result = subprocess.run(
        command, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False,
    )
    with (runtime_home() / "setup.log").open("ab") as log:
        log.write(result.stdout)
    if result.returncode not in accepted:
        raise SetupError("setup_command_failed")


def probe() -> bool:
    resources = ROOT / "maimai_official_interface/resources"
    if sys.platform == "win32":
        result = subprocess.run(
            [str(resources / "chime_bridge.exe"), "--probe"], cwd=resources,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=45, check=False,
        )
        data = json.loads(result.stdout)
        return result.returncode == 0 and data.get("protocol") == 1 and data.get("ok") is True and data.get("stage") == "dll_exports"
    if is_arm64_linux() and not prepared_runtime():
        return False
    return WineChimeBridge(dll_path=resources / "core.dat", timeout=60).probe() == "dll_exports"


def install(archive: Path | None = None) -> None:
    if not is_arm64_linux():
        raise SetupError("requires_arm64_ubuntu")
    if os.sysconf("SC_PAGE_SIZE") != 4096:
        raise SetupError("requires_4k_pages")
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise SetupError("requires_ubuntu_24_04")
    if prepared_runtime() and probe():
        return
    if os.geteuid() != 0 or not shutil.which("apt-get"):
        raise SetupError("container_admin_required")
    home = runtime_home()
    home.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(home).free < 3 * 1024**3:
        raise SetupError("requires_3gb_free_space")
    cache = home / "cache"
    cache.mkdir(exist_ok=True)
    supplied_archive = archive is not None
    archive = archive or cache / "hangover-arm64.tar"
    print("Preparing download", flush=True)
    if not supplied_archive:
        download(RUNTIME_URL, archive, RUNTIME_SHA256)
    packages = extract_packages(archive, cache)
    environment = dict(os.environ)
    environment.update(DEBIAN_FRONTEND="noninteractive", NEEDRESTART_MODE="l")
    print("Preparing container packages", flush=True)
    run(["apt-get", "update"], environment=environment)
    run([
        "apt-get", "--no-remove", "install", "-y", "--no-install-recommends",
        *map(str, packages), "xvfb", "xauth", "libgnutls30t64", "ca-certificates",
    ], environment=environment)
    wine = shutil.which("wine")
    if not wine:
        raise SetupError("runtime_executable_missing")
    prefix = home / "prefix"
    environment.update(
        WINEARCH="win64", WINEPREFIX=str(prefix), WINEDEBUG="-all",
        WINEDLLOVERRIDES="mscoree,mshtml=", HODLL64="libarm64ecfex.dll",
    )
    print("Initializing local environment", flush=True)
    run(["xvfb-run", "-a", wine, "wineboot.exe", "--init"], environment=environment, timeout=180)
    redist = cache / "VC_redist.x64.exe"
    download(VC_URL, redist, VC_SHA256)
    run([
        "xvfb-run", "-a", wine, str(redist), "/install", "/quiet", "/norestart",
    ], environment=environment, timeout=300, accepted=(0, 194))
    resources = ROOT / "maimai_official_interface/resources"
    print("Checking local environment", flush=True)
    result = subprocess.run(
        ["xvfb-run", "-a", wine, str(resources / "chime_bridge.exe"), "--probe"],
        cwd=resources, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=90, check=False,
    )
    payload = WineChimeBridge._parse_payload(result.stdout)
    if result.returncode != 0 or payload.get("protocol") != 1 or payload.get("ok") is not True or payload.get("stage") != "dll_exports":
        with (home / "setup.log").open("a", encoding="utf-8") as log:
            log.write(result.stdout + "\n" + result.stderr)
        raise SetupError("runtime_probe_failed")
    manifest = {
        "schema": 1, "probe": "dll_exports", "wine_binary": wine,
        "prefix": str(prefix), "version": HANGOVER_VERSION,
    }
    temporary = home / "runtime.json.tmp"
    temporary.write_text(json.dumps(manifest), encoding="utf-8")
    temporary.replace(home / "runtime.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or check the local score runtime")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    detail = ""
    try:
        if args.install:
            install(args.archive)
        ready = probe()
        code = "ready" if ready else "not_prepared"
    except SetupError as exc:
        ready, code = False, str(exc)
    except WineBridgeError as exc:
        ready, code, detail = False, "runtime_probe_failed", str(exc)
    except Exception as exc:
        ready, code = False, type(exc).__name__
    print(json.dumps({"ready": ready, "code": code, "detail": detail}), flush=True)
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
