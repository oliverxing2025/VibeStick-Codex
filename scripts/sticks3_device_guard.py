#!/usr/bin/env python3
"""Identify registered StickS3 devices by hardware MAC before flashing."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = (
    Path.home()
    / "Library"
    / "Application Support"
    / "VibeStick"
    / "sticks3-devices.json"
)
MAC_RE = re.compile(r"\bMAC:\s*((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})\b")
CHIP_RE = re.compile(r"Chip is\s+([^\r\n]+)")
VALID_PROFILES = {
    "codex-hourglass-dual",
    "fruit-machine-standalone",
    "hourglass-standalone",
    "stock-monitor-standalone",
    "unassigned",
}


class GuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    port: str
    mac: str
    chip: str


@dataclass(frozen=True)
class Device:
    name: str
    mac: str
    profile: str


def normalize_mac(value: str) -> str:
    value = value.strip().lower().replace("-", ":")
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value):
        raise GuardError(f"Invalid six-byte MAC address: {value!r}")
    return value


def parse_identity(port: str, output: str) -> Identity:
    mac_match = MAC_RE.search(output)
    chip_match = CHIP_RE.search(output)
    if not mac_match:
        raise GuardError(f"Could not read a hardware MAC from {port}.")
    chip = chip_match.group(1).strip() if chip_match else "unknown"
    if "ESP32-S3" not in chip:
        raise GuardError(f"{port} is not an ESP32-S3 device (reported {chip}).")
    return Identity(port=port, mac=normalize_mac(mac_match.group(1)), chip=chip)


def masked_mac(mac: str) -> str:
    parts = normalize_mac(mac).split(":")
    return f"…:{parts[-2]}:{parts[-1]}"


def find_esptool() -> list[str]:
    configured = os.environ.get("VIBESTICK_ESPTOOL", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return [str(path)] if os.access(path, os.X_OK) else [sys.executable, str(path)]
        raise GuardError(f"VIBESTICK_ESPTOOL does not exist: {path}")

    discovered = shutil.which("esptool.py")
    if discovered:
        return [discovered]

    candidates = sorted(
        Path.home().glob(".espressif/python_env/*/bin/esptool.py"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return [str(candidates[0])]

    raise GuardError(
        "esptool.py was not found. Export ESP-IDF or set VIBESTICK_ESPTOOL."
    )


def query_identity(port: str) -> Identity:
    command = [
        *find_esptool(),
        "--chip",
        "esp32s3",
        "--port",
        port,
        "chip_id",
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        detail = next(
            (line.strip() for line in reversed(output.splitlines()) if line.strip()),
            "unknown esptool error",
        )
        raise GuardError(f"Could not identify {port}: {detail}")
    return parse_identity(port, output)


def discover_ports(explicit_port: str | None) -> list[str]:
    if explicit_port:
        return [explicit_port]
    return sorted(glob.glob("/dev/cu.usbmodem*"))


def load_registry(path: Path) -> list[Device]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"Could not read registry {path}: {exc}") from exc
    if payload.get("version") != 1 or not isinstance(payload.get("devices"), list):
        raise GuardError(f"Unsupported device registry format: {path}")

    devices: list[Device] = []
    seen_names: set[str] = set()
    seen_macs: set[str] = set()
    for item in payload["devices"]:
        try:
            device = Device(
                name=str(item["name"]).strip(),
                mac=normalize_mac(str(item["mac"])),
                profile=str(item["profile"]).strip(),
            )
        except (KeyError, TypeError, GuardError) as exc:
            raise GuardError(f"Invalid device registry entry: {item!r}") from exc
        if not device.name:
            raise GuardError("A registered device name cannot be empty.")
        if device.profile not in VALID_PROFILES:
            raise GuardError(
                f"Unknown profile {device.profile!r} for {device.name!r}."
            )
        if device.name in seen_names or device.mac in seen_macs:
            raise GuardError("Device registry contains a duplicate name or MAC.")
        seen_names.add(device.name)
        seen_macs.add(device.mac)
        devices.append(device)
    return devices


def save_registry(path: Path, devices: Iterable[Device]) -> None:
    payload = {
        "version": 1,
        "devices": [
            {"name": item.name, "mac": item.mac, "profile": item.profile}
            for item in sorted(devices, key=lambda item: item.name)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def by_mac(devices: Iterable[Device]) -> dict[str, Device]:
    return {device.mac: device for device in devices}


def by_name(devices: Iterable[Device]) -> dict[str, Device]:
    return {device.name: device for device in devices}


def identify_connected(
    registry: list[Device], explicit_port: str | None
) -> list[tuple[Identity, Device | None]]:
    ports = discover_ports(explicit_port)
    if not ports:
        raise GuardError("No /dev/cu.usbmodem* StickS3 serial port is connected.")
    lookup = by_mac(registry)
    results: list[tuple[Identity, Device | None]] = []
    for port in ports:
        identity = query_identity(port)
        results.append((identity, lookup.get(identity.mac)))
    return results


def command_scan(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    results = identify_connected(registry, args.port)
    for identity, device in results:
        if device:
            print(
                f"REGISTERED name={device.name} profile={device.profile} "
                f"port={identity.port} hardware={masked_mac(identity.mac)}"
            )
        else:
            print(
                f"UNKNOWN port={identity.port} hardware={masked_mac(identity.mac)} "
                "flash=REFUSED"
            )
    return 0


def command_list(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    if not registry:
        print("No StickS3 devices are registered.")
        return 0
    for device in sorted(registry, key=lambda item: item.name):
        print(
            f"name={device.name} profile={device.profile} "
            f"hardware={masked_mac(device.mac)}"
        )
    return 0


def select_single_identity(port: str | None) -> Identity:
    ports = discover_ports(port)
    if not ports:
        raise GuardError("No /dev/cu.usbmodem* StickS3 serial port is connected.")
    if len(ports) != 1:
        raise GuardError(
            "More than one StickS3 port is connected; pass --port explicitly."
        )
    return query_identity(ports[0])


def command_register(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    identity = select_single_identity(args.port)
    names = by_name(registry)
    macs = by_mac(registry)

    if args.name in names:
        existing = names[args.name]
        if existing.mac != identity.mac:
            raise GuardError(
                f"Name {args.name!r} already belongs to different hardware "
                f"{masked_mac(existing.mac)}."
            )
        if existing.profile != args.profile:
            raise GuardError(
                f"{args.name!r} is already registered with profile "
                f"{existing.profile!r}."
            )
        print(f"UNCHANGED name={existing.name} hardware={masked_mac(existing.mac)}")
        return 0

    if identity.mac in macs:
        existing = macs[identity.mac]
        raise GuardError(
            f"Hardware {masked_mac(identity.mac)} is already named "
            f"{existing.name!r}."
        )

    registered = Device(args.name, identity.mac, args.profile)
    save_registry(args.registry, [*registry, registered])
    print(
        f"REGISTERED name={registered.name} profile={registered.profile} "
        f"hardware={masked_mac(registered.mac)}"
    )
    return 0


def command_require(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    expected = by_name(registry).get(args.name)
    if expected is None:
        raise GuardError(f"Device {args.name!r} is not registered.")
    if args.profile and expected.profile != args.profile:
        raise GuardError(
            f"Device {args.name!r} has profile {expected.profile!r}, "
            f"not {args.profile!r}."
        )

    results = identify_connected(registry, args.port)
    matching = [
        (identity, device)
        for identity, device in results
        if identity.mac == expected.mac
    ]
    if not matching:
        connected = ", ".join(
            device.name if device else f"UNKNOWN({masked_mac(identity.mac)})"
            for identity, device in results
        )
        raise GuardError(
            f"Expected {expected.name!r}, but connected hardware is: {connected}. "
            "Flash refused."
        )
    if len(matching) != 1:
        raise GuardError(f"Device {expected.name!r} appeared on multiple ports.")

    identity, _ = matching[0]
    print(
        f"AUTHORIZED name={expected.name} profile={expected.profile} "
        f"port={identity.port} hardware={masked_mac(identity.mac)}",
        file=sys.stderr,
    )
    print(identity.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recognize physical StickS3 units by hardware MAC. "
            "Unknown or mismatched devices are never authorized for flashing."
        )
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="local device registry (default: macOS Application Support)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="identify all connected StickS3 units")
    scan.add_argument("--port")
    scan.set_defaults(handler=command_scan)

    list_command = subparsers.add_parser("list", help="list registered devices")
    list_command.set_defaults(handler=command_list)

    register = subparsers.add_parser(
        "register", help="register the one connected StickS3"
    )
    register.add_argument("--name", required=True)
    register.add_argument("--profile", choices=sorted(VALID_PROFILES), required=True)
    register.add_argument("--port")
    register.set_defaults(handler=command_register)

    require = subparsers.add_parser(
        "require", help="authorize only the named connected StickS3"
    )
    require.add_argument("--name", required=True)
    require.add_argument("--profile", choices=sorted(VALID_PROFILES))
    require.add_argument("--port")
    require.set_defaults(handler=command_require)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (GuardError, subprocess.TimeoutExpired) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
