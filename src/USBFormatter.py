#!/usr/bin/env python3

import os
import uuid
import signal
import subprocess
import json
import sys

from USBDeviceManager import USBDeviceManager

stopWriting = False

import argparse

def receiveSignal(number, frame):
    global stopWriting
    stopWriting = True
    return


signal.signal(signal.SIGTERM, receiveSignal)

parser = argparse.ArgumentParser(
        prog='Pardus USB Formatter',
        description='Format USB flash drives',
        epilog='USB Format tool for pardus'
)

parser.add_argument('-t', '--type', default="FAT32")
parser.add_argument('-d', '--device', required=True)
parser.add_argument('-l', '--label',default="")
parser.add_argument('-c', '--crypt')
parser.add_argument('-f', '--fill', default=False, action='store_true')
parser.add_argument('-g', '--gpt', default=False, action='store_true')

args = parser.parse_args()


# Only allow USB disks listed by the GUI (prevents non-removable disks and ../ traversal)
if args.device not in USBDeviceManager.find_usb_devices():
    print(f"Invalid device: {args.device}", file=sys.stderr)
    exit(1)


def execute(command):
    subprocess.call(command)
    subprocess.call(["sync"])


def create_luks(disk, name, password):
    cmds = [
        ["cryptsetup", "luksFormat", disk, "-"],
        ["cryptsetup", "luksOpen", disk, name, "-"]
    ]
    for cmd in cmds:
        p = subprocess.Popen(cmd,
            stdin=subprocess.PIPE,
        )
        p.communicate(input=password.encode())
        if p.returncode != 0:
            raise Exception("Failed to run command: {}".format(" ".join(cmd)))

def find_mounts(disk):
    sp = subprocess.run(
        ["lsblk", "-J", f"/dev/{disk}"],
        stdout=subprocess.PIPE
    )
    data = sp.stdout.decode("utf-8")
    data = json.loads(data)
    ret = []
    names = []
    for blocks in data.get("blockdevices", []):
        ret += blocks.get("mountpoints", [])
        names.append(blocks.get("name"))
        for child in blocks.get("children", []):
            ret += child.get("mountpoints", [])
            names.append(child.get("name"))
            for child in child.get("children", []):
                ret += child.get("mountpoints", [])
                names.append(child.get("name"))
    return {"mounts": ret, "names": names}


prefix=""
if "mmcblk" in args.device:
    prefix="p"
elif "nvme" in args.device:
    prefix="p"

# Unmount the drive before writing on it
mounts =  find_mounts(args.device)

for mp in mounts.get("mounts", []):
    if mp and os.path.exists(str(mp)):
        try:
            subprocess.run(["umount", "-f", str(mp)], check=False)
        except Exception:
            pass

for n in mounts.get("names", []):
    if n and os.path.exists(f"/dev/mapper/{n}"):
        try:
            subprocess.run(["dmsetup", "remove", str(n)], check=False)
        except Exception:
            pass

# Erase MBR
with open(f"/dev/{args.device}", "wb") as f:
    f.write(b"\0"*4096)
    f.flush()

subprocess.call(["partprobe", f"/dev/{args.device}"])


# Fill with zeros:
if args.fill:
    writtenBytes = 0
    # sysfs always reports size in 512 byte sectors, even on 4K devices
    with open(f"/sys/block/{args.device}/size", "r") as f:
        sectorCount = int(f.readline().strip())
    with open(f"/sys/block/{args.device}/queue/logical_block_size", "r") as f:
        blockSize = int(f.readline().strip())
    totalFileBytes = sectorCount * 512

    writeFile = open(f"/dev/{args.device}", "wb")

    oldMB = 0
    # write 4 MiB at a time, one block per loop was very slow on big drives
    chunkSize = max(blockSize, 4 * 1024 * 1024 // blockSize * blockSize)
    zeros = memoryview(bytes(chunkSize))
    try:
        print("PROGRESS|{}|{}".format(writtenBytes, totalFileBytes))
        sys.stdout.flush()
        while totalFileBytes != writtenBytes:
            if stopWriting:
                break

            size = min(chunkSize, totalFileBytes - writtenBytes)
            writeFile.write(zeros[:size])
            writtenBytes += size

            newMB = int(writtenBytes / 1000 / 1000 / 10)
            if oldMB != newMB:
                oldMB = newMB
                print("PROGRESS|{}|{}".format(writtenBytes, totalFileBytes))
                os.fsync(writeFile)
                sys.stdout.flush()

        writeFile.flush()
    except IOError:
        exit(1)
    else:
        os.fsync(writeFile)
        writeFile.close()

# Make the partition table:
execute(["parted", f"/dev/{args.device}", "mktable", "gpt" if args.gpt else "msdos"])

# Create a partition:
part_type = args.type
if part_type not in ["FAT32", "EXT4", "NTFS", "EXFAT", "BTRFS"]:
    part_type = "EXT4"
execute(["parted", f"/dev/{args.device}", "mkpart", "primary", part_type, "1", "100%"])

# Remove old fs:
execute(["wipefs", "-a", f"/dev/{args.device}{prefix}1", "--force"])

partition = f"/dev/{args.device}{prefix}1"

luks = None
# Crypt:
if args.crypt:
    luks = str(uuid.uuid4())
    create_luks(partition, luks, args.crypt)
    partition = f"/dev/mapper/{luks}"

# Format:
if args.type == "FAT32":
    execute(["mkfs.fat", "-F", "32", "-n", args.label, "-I", partition])
elif args.type == "EXT4":
    execute(["mkfs.ext4", "-L", args.label, partition])
elif args.type == "NTFS":
    execute(["mkfs.ntfs", "-f", "-L", args.label, partition])
elif args.type == "EXFAT":
    execute(["mkfs.exfat", "-L", args.label, partition])
elif args.type == "BTRFS":
    execute(["mkfs.btrfs", "-f", "-L", args.label, partition])


# Close luks
if luks:
    subprocess.call(["cryptsetup", "luksClose", f"/dev/mapper/{luks}"])

# Eject and uneject again to show new partition:
subprocess.call(["eject", f"/dev/{args.device}"])
subprocess.call(["eject", "-t", f"/dev/{args.device}"])

exit(0)
