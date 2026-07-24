#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import traceback

from hash import HashMismatchError, SHA256Verifier


COPY_CHUNK_SIZE = 8 * 1024 * 1024
FAT32_FILE_LIMIT = 4 * 1024 * 1024 * 1024 - 1
MINIMUM_ISO_STORAGE = 4 * 1024 * 1024 * 1024
cancel_event = False


class OperationCancelled(Exception):
    pass


def receive_signal(number, frame):
    global cancel_event
    cancel_event = True


def raise_if_cancelled():
    if cancel_event:
        raise OperationCancelled("ISO writing was cancelled")


def report_status(status):
    print("STATUS|{}".format(status), flush=True)


def report_log(message):
    print("LOG|{}".format(str(message).replace("\n", "\\n")), flush=True)


def run_command(command):
    raise_if_cancelled()
    report_log("Running command: {}".format(" ".join(command)))
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as error:
        output = (error.output or "").strip()
        stderr = (error.stderr or "").strip()
        if output:
            report_log("Command stdout: {}".format(output))
        if stderr:
            report_log("Command stderr: {}".format(stderr))
        details = stderr or output or "no output"
        raise RuntimeError(
            "Command failed ({}): {}".format(" ".join(command), details)
        )
    if result.stdout.strip():
        report_log("Command stdout: {}".format(result.stdout.strip()))
    if result.stderr.strip():
        report_log("Command stderr: {}".format(result.stderr.strip()))
    raise_if_cancelled()
    return result


def find_mounts(device):
    result = run_command(["lsblk", "-J", "/dev/{}".format(device)])
    output = result.stdout
    if isinstance(output, bytes):
        output = output.decode("utf-8")
    mounts = []
    names = []

    def collect(block):
        mounts.extend(mount for mount in (block.get("mountpoints") or []) if mount)
        if block.get("name"):
            names.append(block["name"])
        for child in block.get("children", []):
            collect(child)

    for block in json.loads(output).get("blockdevices", []):
        collect(block)
    return mounts, names


def validate_usb_device(device):
    if not re.match(r"^(sd[a-z]+|mmcblk[0-9]+|nvme[0-9]+n[0-9]+)$", device):
        raise ValueError("Invalid USB device name")
    sysfs_path = os.path.realpath("/sys/block/{}".format(device))
    if not os.path.isdir(sysfs_path) or not any(
        part.startswith("usb") for part in sysfs_path.split("/")
    ):
        raise ValueError("Selected device is not a USB disk")
    device_path = "/dev/{}".format(device)
    if not os.path.exists(device_path) or not stat.S_ISBLK(os.stat(device_path).st_mode):
        raise ValueError("Selected USB device is no longer available")
    return device_path


def ensure_minimum_device_capacity(device):
    with open("/sys/block/{}/size".format(device)) as size_file:
        sectors = int(size_file.read().strip())
    with open("/sys/block/{}/queue/logical_block_size".format(device)) as block_file:
        block_size = int(block_file.read().strip())
    if sectors * block_size < MINIMUM_ISO_STORAGE:
        raise ValueError("Target USB device must have at least 4 GiB of capacity")


def validate_iso_path(iso_path):
    iso_path = os.path.abspath(iso_path)
    if not os.path.isfile(iso_path) or not stat.S_ISREG(os.stat(iso_path).st_mode):
        raise ValueError("ISO source is not a regular file")
    return iso_path


def unmount_device(device):
    mounts, mapper_names = find_mounts(device)
    for mount in mounts:
        run_command(["umount", "-f", mount])
    for name in mapper_names:
        mapper_path = "/dev/mapper/{}".format(name)
        if os.path.exists(mapper_path):
            run_command(["dmsetup", "remove", name])
    remaining_mounts, _ = find_mounts(device)
    if remaining_mounts:
        raise RuntimeError(
            "Target device is still mounted: {}".format(", ".join(remaining_mounts))
        )


def partition_path(device):
    suffix = "p" if device.startswith(("mmcblk", "nvme")) else ""
    return "/dev/{}{}1".format(device, suffix)


def verify_iso(iso_path, expected_sha256):
    if not expected_sha256:
        return None
    verifier = SHA256Verifier(expected_sha256)
    with open(iso_path, "rb") as iso_file:
        while True:
            raise_if_cancelled()
            chunk = iso_file.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            verifier.update(chunk)
    raise_if_cancelled()
    try:
        return verifier.verify()
    except HashMismatchError as error:
        report_log(
            "SHA-256 mismatch: expected {}, got {}".format(
                error.expected, error.actual
            )
        )
        raise


def largest_regular_file(directory):
    largest = 0
    for root, directories, files in os.walk(directory):
        raise_if_cancelled()
        for filename in files:
            file_path = os.path.join(root, filename)
            file_stat = os.lstat(file_path)
            if stat.S_ISREG(file_stat.st_mode):
                largest = max(largest, file_stat.st_size)
    return largest


def copy_file(source, destination):
    raise_if_cancelled()
    with open(source, "rb") as input_file, open(destination, "wb") as output_file:
        while True:
            raise_if_cancelled()
            chunk = input_file.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            output_file.write(chunk)
        output_file.flush()
        os.fsync(output_file.fileno())
    # FAT filesystems cannot preserve all POSIX metadata from the ISO.
    try:
        shutil.copystat(source, destination, follow_symlinks=False)
    except OSError:
        pass


def copy_symlink(source, destination):
    try:
        os.symlink(os.readlink(source), destination)
    except OSError as error:
        report_log(
            "Uyarı: Soft link atlandı (FAT32 desteklemiyor): {} -> {} (errno {})".format(
                source, destination, error.errno
            )
        )


def copy_directory(source_directory, target_directory):
    os.mkdir(target_directory)
    for entry in os.scandir(source_directory):
        raise_if_cancelled()
        if entry.is_symlink():
            copy_symlink(entry.path, os.path.join(target_directory, entry.name))
        elif entry.is_dir(follow_symlinks=False):
            copy_directory(entry.path, os.path.join(target_directory, entry.name))
        elif entry.is_file(follow_symlinks=False):
            copy_file(entry.path, os.path.join(target_directory, entry.name))
        else:
            raise RuntimeError("ISO contains an unsupported file type: {}".format(entry.path))


def copy_iso_contents(source_directory, target_directory):
    for entry in os.scandir(source_directory):
        raise_if_cancelled()
        target_path = os.path.join(target_directory, entry.name)
        if entry.is_symlink():
            copy_symlink(entry.path, target_path)
        elif entry.is_dir(follow_symlinks=False):
            copy_directory(entry.path, target_path)
        elif entry.is_file(follow_symlinks=False):
            copy_file(entry.path, target_path)
        else:
            raise RuntimeError("ISO contains an unsupported file type: {}".format(entry.path))
    raise_if_cancelled()


def create_partition(device_path, device, partition_table, filesystem):
    run_command(["parted", "--script", device_path, "mklabel", partition_table])
    run_command(
        [
            "parted",
            "--script",
            device_path,
            "mkpart",
            "primary",
            "fat32" if filesystem == "fat32" else "exfat",
            "1MiB",
            "100%",
        ]
    )
    if partition_table == "gpt":
        run_command(["parted", "--script", device_path, "set", "1", "esp", "on"])
        run_command(["parted", "--script", device_path, "set", "1", "boot", "on"])
    else:
        run_command(["parted", "--script", device_path, "set", "1", "boot", "on"])
    run_command(["partprobe", device_path])
    run_command(["udevadm", "settle"])

    partition = partition_path(device)
    if not os.path.exists(partition):
        raise RuntimeError("New USB partition was not created")
    run_command(["wipefs", "-a", partition, "--force"])
    if filesystem == "fat32":
        run_command(["mkfs.fat", "-F", "32", "-n", "PARDUS", "-I", partition])
    else:
        run_command(["mkfs.exfat", "-n", "PARDUS", partition])
    return partition


def install_bootloader(partition_table, device_path, target_directory):
    report_status("installing_bootloader")
    if partition_table == "msdos":
        grub_config = os.path.join(target_directory, "boot", "grub", "grub.cfg")
        if not os.path.isfile(grub_config):
            raise RuntimeError("ISO does not contain boot/grub/grub.cfg for Legacy booting")
        run_command(
            [
                "grub-install",
                "--target=i386-pc",
                "--boot-directory={}".format(os.path.join(target_directory, "boot")),
                device_path,
            ]
        )
        return

    efi_bootloader = os.path.join(target_directory, "EFI", "BOOT", "BOOTX64.EFI")
    if not os.path.isfile(efi_bootloader):
        raise RuntimeError("ISO does not contain EFI/BOOT/BOOTX64.EFI for UEFI booting")


def cleanup_staging_directory(directory, cache_root):
    directory = os.path.realpath(directory)
    if not cache_root:
        raise ValueError("Missing staging cache root")
    cache_root = os.path.realpath(cache_root)
    if not os.path.exists(directory):
        return
    if (
        os.path.dirname(directory) != cache_root
        or not os.path.basename(directory).startswith("pardus-usb-formatter-")
    ):
        raise ValueError("Refusing to remove an unexpected staging directory")
    invoking_uid = os.environ.get("PKEXEC_UID")
    if (
        invoking_uid is None
        or os.stat(cache_root).st_uid != int(invoking_uid)
        or os.stat(directory).st_uid != int(invoking_uid)
    ):
        raise ValueError("Refusing to remove a staging directory owned by another user")
    shutil.rmtree(directory, ignore_errors=True)


def write_iso(args):
    try:
        if os.geteuid() != 0:
            raise PermissionError("ISO writer must be started with pkexec")
        device_path = validate_usb_device(args.device)
        ensure_minimum_device_capacity(args.device)
        iso_path = validate_iso_path(args.iso_path)
        if args.sha256:
            report_status("verifying")
            verify_iso(iso_path, args.sha256)

        with tempfile.TemporaryDirectory(prefix="pardus-iso-writer-") as temporary_directory:
            iso_mount = os.path.join(temporary_directory, "iso")
            target_mount = os.path.join(temporary_directory, "target")
            os.mkdir(iso_mount)
            os.mkdir(target_mount)
            target_mounted = False
            iso_mounted = False
            try:
                run_command(["mount", "-o", "loop,ro", iso_path, iso_mount])
                iso_mounted = True
                filesystem = "exfat" if largest_regular_file(iso_mount) > FAT32_FILE_LIMIT else "fat32"
                if args.partition_table == "gpt" and filesystem == "exfat":
                    raise RuntimeError(
                        "A GPT UEFI USB needs a FAT32 EFI System Partition; this ISO has a file larger than 4 GiB"
                    )

                report_status("formatting")
                unmount_device(args.device)
                partition = create_partition(
                    device_path, args.device, args.partition_table, filesystem
                )
                run_command(["mount", partition, target_mount])
                target_mounted = True

                report_status("copying")
                copy_iso_contents(iso_mount, target_mount)
                os.sync()
                install_bootloader(args.partition_table, device_path, target_mount)
                os.sync()
            finally:
                if target_mounted:
                    subprocess.run(["umount", target_mount], check=False)
                if iso_mounted:
                    subprocess.run(["umount", iso_mount], check=False)
    finally:
        if args.cleanup_directory:
            cleanup_staging_directory(args.cleanup_directory, args.cleanup_root)


def cancel_writer(pid):
    try:
        with open("/proc/{}/cmdline".format(pid), "rb") as command_line:
            if b"ISOWriter.py" not in command_line.read():
                raise ValueError("Requested process is not an ISO writer")
        os.kill(pid, signal.SIGTERM)
    except OSError as error:
        raise ValueError("Could not stop ISO writer: {}".format(error))


def parse_args():
    parser = argparse.ArgumentParser(description="Copy a bootable ISO to a USB device")
    parser.add_argument("--device")
    parser.add_argument("--iso-path")
    parser.add_argument("--sha256")
    parser.add_argument("--partition-table", choices=("msdos", "gpt"), default="gpt")
    parser.add_argument("--cleanup-directory")
    parser.add_argument("--cleanup-root")
    parser.add_argument("--cancel-pid", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.cancel_pid is not None:
            cancel_writer(args.cancel_pid)
            return 0
        if not args.device or not args.iso_path:
            raise ValueError("--device and --iso-path are required")
        write_iso(args)
        print("COMPLETE", flush=True)
        return 0
    except OperationCancelled:
        print("CANCELLED", flush=True)
        return 2
    except Exception as error:
        report_log("ISO writer failed: {}".format(error))
        for line in traceback.format_exc().rstrip().splitlines():
            report_log(line)
        print("ERROR|{}".format(error), flush=True)
        return 1


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, receive_signal)
    signal.signal(signal.SIGINT, receive_signal)
    sys.exit(main())
