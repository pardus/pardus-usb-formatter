#!/usr/bin/env python3

import subprocess, sys, os, time, signal
stopWriting = False

def receiveSignal(number, frame):
    global stopWriting
    stopWriting = True
    return

signal.signal(signal.SIGQUIT, receiveSignal)

device = sys.argv[1]
selectedFormat = sys.argv[2].lower()
isSlow = sys.argv[3] == "1"
deviceName = sys.argv[4] if sys.argv[4] else ""

partition = f"{device}1"
partitionType = selectedFormat if selectedFormat != "exfat" else "ntfs"

def execute(command):
    subprocess.call(command)
    subprocess.call(["sync"])

# Unmount the drive before writing on it
subprocess.call(["umount", f"{partition}"])

# Erase MBR
execute(["dd", "if=/dev/zero", f"of={device}", "bs=512", "count=1"])

# Fill with zeros:
if isSlow:
    execute(["dd", "if=/dev/zero", f"of={device}", "bs=2048"])

# Make the partition table:
execute(["parted", device, "mktable", "msdos"])

# Create a partition:
execute(["parted", device, "mkpart", "primary", partitionType, "1", "100%"])

# Remove old fs:
execute(["wipefs", "-a", partition, "--force"])

# Format:
if selectedFormat == "fat32":
    execute(["mkfs.fat", "-F", "32", "-n", deviceName, "-I", partition])
elif selectedFormat == "ext4":
    execute(["mkfs.ext4", "-L", deviceName, partition])
elif selectedFormat == "ntfs":
    execute(["mkfs.ntfs", "-f", "-L", deviceName, partition])
elif selectedFormat == "exfat":
    execute(["mkfs.exfat", "-n", deviceName, device])


exit(0)
