#!/usr/bin/env python3
"""System Backup Manager: explicitly guarded local USB HDD disaster recovery."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "backup.json"
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
EXCLUDE_SYSTEM = [
    "/dev/***", "/proc/***", "/sys/***", "/run/***", "/tmp/***",
    "/mnt/***", "/media/***", "/lost+found", "/srv/jail/***",
    "/srv/software_development/***", "/srv/smb/***", "/srv/ftp/***",
    "/root/.vscode-server/cli/servers/***", "/var/cache/apt/archives/***",
    "/var/cache/apt/pkgcache.bin", "/var/cache/apt/srcpkgcache.bin",
]
EXCLUDE_DEV = [
    "/lost+found", "/forprint-project/calculator_engine/app/tmp/tmp/***",
]


def call(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def info(message: str) -> None:
    print(f"[SBM] {message}", flush=True)


def fail(message: str) -> None:
    raise RuntimeError(message)


def settings() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def require_root() -> None:
    if os.geteuid() != 0:
        fail("Run as root. This is a local-only server administration tool.")


def disk_candidates(conf: dict) -> list[str]:
    devices = json.loads(call("lsblk", "-J", "-b", "-d", "-o", "NAME,TYPE,TRAN,SIZE,MODEL", capture=True))["blockdevices"]
    return ["/dev/" + d["name"] for d in devices
            if d.get("type") == "disk" and d.get("tran") == "usb"
            and conf["disk_model_token"] in (d.get("model") or "")
            and conf["min_disk_bytes"] <= int(d.get("size") or 0) <= conf["max_disk_bytes"]]


def real_mount_source(path: str) -> str:
    return call("findmnt", "-n", "-o", "SOURCE", "--target", path, capture=True)


def check_host(conf: dict) -> None:
    if Path("/sys/firmware/efi").exists():
        fail("Host is UEFI; this release supports Legacy BIOS only.")
    if real_mount_source("/") != "/dev/md0":
        fail("System root is not /dev/md0.")
    if real_mount_source(conf["development_source"]) != conf["development_block"]:
        fail("Unexpected Development source device.")
    md = Path("/proc/mdstat").read_text()
    for name in ("md0", "md1"):
        if not re.search(rf"(?m)^{name} :.*?(?:\n[^\n]*)?\s\[UU\]", md):
            fail(f"RAID {name} is not confirmed healthy [UU].")


def check_disk(conf: dict, selected: str | None) -> str:
    candidates = disk_candidates(conf)
    if selected:
        device = os.path.realpath(selected)
        if device not in candidates:
            fail(f"Selected disk {selected} did not match USB model and size safety rules; matches: {candidates}")
    elif len(candidates) != 1:
        fail(f"Expected exactly one matching USB disk, found: {candidates}")
    else:
        device = candidates[0]
    if not re.fullmatch(r"/dev/[a-zA-Z0-9_-]+", device):
        fail("Unsafe disk device path.")
    udev = call("udevadm", "info", "--query=property", f"--name={device}", capture=True)
    if "ID_BUS=usb" not in udev.splitlines():
        fail("udev did not confirm ID_BUS=usb.")
    # No target descendant may be mounted, in RAID/LVM, or used as swap.
    tree = json.loads(call("lsblk", "-J", "-o", "NAME,TYPE,MOUNTPOINTS", device, capture=True))["blockdevices"][0]
    def validate(node: dict) -> None:
        if node.get("mountpoints") and any(node["mountpoints"]):
            fail(f"Target contains active mount or swap: {node['name']}")
        if node.get("type") in ("raid1", "raid0", "lvm", "crypt", "md"):
            fail("Target is part of an active storage stack.")
        for child in node.get("children", []) or []:
            validate(child)
    validate(tree)
    block = Path("/sys/class/block")
    for n in [tree] + (tree.get("children") or []):
        holders = block / n["name"] / "holders"
        if holders.is_dir() and any(holders.iterdir()):
            fail(f"Target {n['name']} has kernel holders.")
    for protected in ("/dev/md0", conf["development_block"]):
        if os.path.realpath(device) == os.path.realpath(protected):
            fail("Target overlaps production source.")
    return device


def part(device: str, n: int) -> str:
    return f"{device}{'p' if device[-1].isdigit() else ''}{n}"


def partition_uuid(device: str, n: int, label: str) -> str:
    path = part(device, n)
    if call("blkid", "-s", "TYPE", "-o", "value", path, capture=True) != "ext4":
        fail(f"Not ext4: {path}")
    if call("blkid", "-s", "LABEL", "-o", "value", path, capture=True) != label:
        fail(f"Unexpected label: {path}")
    return call("blkid", "-s", "UUID", "-o", "value", path, capture=True)


def inspect(conf: dict, device: str) -> None:
    info(f"Target USB HDD: {device}")
    call("lsblk", "-o", "NAME,SIZE,MODEL,TRAN,FSTYPE,LABEL,UUID,MOUNTPOINTS", device)
    info("RAID status:")
    print(Path("/proc/mdstat").read_text())
    info(f"Development source: {real_mount_source(conf['development_source'])}")
    info("Inspect is read-only. Preparation is a separate destructive operation.")


def prepare(conf: dict, device: str) -> None:
    info("DESTRUCTIVE: all partitions and Windows data on this USB HDD will be erased.")
    info(f"Target: {device}; model token {conf['disk_model_token']}")
    confirmation = input(f"Type {conf['erase_phrase']} to erase this device: ").strip()
    if confirmation != conf["erase_phrase"]:
        fail("Erase not confirmed.")
    check_host(conf)
    check_disk(conf, device)
    call("parted", "-s", device, "mklabel", "msdos")
    call("parted", "-s", device, "mkpart", "primary", "ext4", "1MiB", conf["clone_end"])
    call("parted", "-s", device, "set", "1", "boot", "on")
    call("parted", "-s", device, "mkpart", "primary", "ext4", conf["clone_end"], "100%")
    call("partprobe", device)
    call("udevadm", "settle")
    call("mkfs.ext4", "-F", "-L", "MFS_CLONE", part(device, 1))
    call("mkfs.ext4", "-F", "-L", "MFS_BACKUP", part(device, 2))
    info("Prepared disk; live /etc/fstab, RAID, Hestia, and Development unchanged.")


def assert_mount(path: Path, uuid: str) -> None:
    found = call("findmnt", "-n", "-o", "UUID", "--mountpoint", str(path), capture=True)
    if found != uuid:
        fail(f"Unsafe mount: {path} UUID={found!r}, expected {uuid!r}")


@contextmanager
def mounted(device: str):
    root_uuid = partition_uuid(device, 1, "MFS_CLONE")
    backup_uuid = partition_uuid(device, 2, "MFS_BACKUP")
    mount1, mount2 = Path("/mnt/sbm_clone"), Path("/mnt/sbm_backup")
    mount1.mkdir(parents=True, exist_ok=True)
    mount2.mkdir(parents=True, exist_ok=True)
    for p in (mount1, mount2):
        if subprocess.run(["mountpoint", "-q", str(p)]).returncode == 0:
            fail(f"Existing mount at {p}; refusing.")
    mounted_paths = []
    try:
        call("mount", "-t", "ext4", part(device, 1), str(mount1))
        mounted_paths.append(mount1)
        call("mount", "-t", "ext4", part(device, 2), str(mount2))
        mounted_paths.append(mount2)
        assert_mount(mount1, root_uuid)
        assert_mount(mount2, backup_uuid)
        yield mount1, mount2, root_uuid, backup_uuid
    finally:
        call("sync")
        for p in reversed(mounted_paths):
            call("umount", str(p))


def rsync(source: str, dest: str, excludes: list[str], *, delete: bool = False, link_dest: str | None = None) -> None:
    cmd = ["rsync", "-aAXH", "--numeric-ids", "--one-file-system", "--info=stats2"]
    if delete:
        cmd.append("--delete")
    cmd += [f"--exclude={x}" for x in excludes]
    if link_dest:
        cmd.append(f"--link-dest={link_dest}")
    call(*(cmd + [source.rstrip("/") + "/", dest.rstrip("/") + "/"]))


@contextmanager
def chroot_mounts(root: Path):
    mounted_paths = []
    try:
        for name, args in (
            ("dev", ("mount", "--rbind", "/dev")),
            ("proc", ("mount", "-t", "proc", "proc")),
            ("sys", ("mount", "--rbind", "/sys")),
            ("run", ("mount", "--bind", "/run")),
        ):
            target = root / name
            target.mkdir(exist_ok=True, parents=True)
            call(*args, str(target))
            mounted_paths.append(target)
            if name in ("dev", "sys"):
                call("mount", "--make-rslave", str(target))
        yield
    finally:
        for path in reversed(mounted_paths):
            call("umount", "-R", str(path))


def make_bootable(clone: Path, device: str, uuid: str) -> None:
    fstab = clone / "etc/fstab"
    fstab.write_text(f"# Standalone emergency system; data disks intentionally not mounted\nUUID={uuid} / ext4 defaults,errors=remount-ro 0 1\n")
    grub_default = clone / "etc/default/grub"
    with grub_default.open("a") as f:
        f.write("\nGRUB_DISABLE_OS_PROBER=true\n")
    with chroot_mounts(clone):
        call("chroot", str(clone), "grub-install", "--target=i386-pc", device)
        call("chroot", str(clone), "update-initramfs", "-u", "-k", "all")
        call("chroot", str(clone), "update-grub")
    grub_cfg = clone / "boot/grub/grub.cfg"
    if not grub_cfg.is_file() or uuid not in grub_cfg.read_text(errors="replace"):
        fail("GRUB root UUID not found in clone grub.cfg; manual investigation required.")


def snapshots(root: Path) -> list[Path]:
    return sorted((p for p in root.iterdir() if p.is_dir() and STAMP_RE.fullmatch(p.name)
                   and (p / ".sbm-complete.json").is_file()), key=lambda p: p.name) if root.exists() else []


def snapshot(source: str, kind: str, root: Path, stamp: str, excludes: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    dest, stage = root / stamp, root / (".incomplete-" + stamp)
    if dest.exists() or stage.exists():
        fail("Snapshot destination already exists.")
    previous = snapshots(root)
    stage.mkdir()
    rsync(source, str(stage), excludes, link_dest=str(previous[-1]) if previous else None)
    (stage / ".sbm-complete.json").write_text(json.dumps({
        "kind": kind, "source": source, "created": stamp,
        "file_level_complete": True, "live_database_consistency": "NOT_VERIFIED",
    }, indent=2) + "\n")
    stage.rename(dest)
    info(f"Snapshot completed: {dest}")
    return dest


def prune(root: Path, keep: int) -> None:
    for old in snapshots(root)[:-keep]:
        if not STAMP_RE.fullmatch(old.name) or old.parent != root:
            fail("Unsafe snapshot deletion path.")
        info(f"Pruning old completed snapshot: {old.name}")
        shutil.rmtree(old)


def backup(conf: dict, device: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    with mounted(device) as (clone, store, root_uuid, backup_uuid):
        info("Updating standalone system clone; data mounts excluded.")
        rsync("/", str(clone), EXCLUDE_SYSTEM, delete=True)
        assert_mount(clone, root_uuid)
        assert_mount(store, backup_uuid)
        make_bootable(clone, device, root_uuid)
        dest = store / "MAIL_FTP_SERVER_BACKUP"
        sysroot = dest / "system_snapshots"
        devroot = dest / "development_snapshots"
        info("Creating file-level system snapshot.")
        snapshot("/", "system", sysroot, stamp, EXCLUDE_SYSTEM)
        free = shutil.disk_usage(store).free
        if free < conf["min_free_before_development_bytes"]:
            fail(f"Insufficient free space ({free} bytes) before Development copy; no pruning performed.")
        info("Creating Development snapshot.")
        snapshot(conf["development_source"], "development", devroot, stamp, EXCLUDE_DEV)
        assert_mount(store, backup_uuid)
        inventory = dest / "inventory"
        inventory.mkdir(parents=True, exist_ok=True)
        (inventory / ("raid-" + stamp + ".txt")).write_text(Path("/proc/mdstat").read_text())
        call("sync")
        prune(sysroot, conf["keep_last_backups"])
        prune(devroot, conf["keep_last_backups"])
        info("BACKUP=PASS_FILE_LEVEL; BOOT_TEST=PENDING; LIVE_DB_CONSISTENCY=NOT_VERIFIED")


def verify(device: str) -> None:
    with mounted(device) as (clone, store, root_uuid, backup_uuid):
        assert_mount(clone, root_uuid)
        assert_mount(store, backup_uuid)
        fstab = (clone / "etc/fstab").read_text()
        if f"UUID={root_uuid} / ext4" not in fstab:
            fail("Clone root fstab UUID mismatch.")
        cfg = clone / "boot/grub/grub.cfg"
        if not cfg.is_file() or root_uuid not in cfg.read_text(errors="replace"):
            fail("GRUB clone UUID missing.")
        data = store / "MAIL_FTP_SERVER_BACKUP"
        for kind in ("system_snapshots", "development_snapshots"):
            items = snapshots(data / kind)
            if not items:
                fail(f"No completed {kind}")
            info(f"{kind}: {len(items)} completed; latest: {items[-1].name}")
        info("VERIFY=PASS_STRUCTURE; PHYSICAL_BOOT=UNTESTED; DATABASE_RECOVERY=UNTESTED")


def main() -> int:
    parser = argparse.ArgumentParser(description="ForPrint guarded system backup manager")
    parser.add_argument("command", choices=("inspect", "prepare", "backup", "verify"))
    parser.add_argument("--device", help="Explicit USB HDD path, still subject to all safety checks")
    args = parser.parse_args()
    conf = settings()
    require_root()
    lock = Path("/run/lock/forprint-system-backup-manager.lock")
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_host(conf)
        device = check_disk(conf, args.device)
        if args.command == "inspect":
            inspect(conf, device)
        elif args.command == "prepare":
            prepare(conf, device)
        elif args.command == "backup":
            backup(conf, device)
        else:
            verify(device)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, BlockingIOError) as exc:
        print(f"[SBM] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
