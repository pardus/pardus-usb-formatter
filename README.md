# Pardus Usb Formatter

Pardus Usb Formatter is an application for format USB drives easily.

It can also create bootable USB media from the latest official Pardus GNOME or
XFCE ISO, or from a local ISO file. Current Pardus images are discovered from
the official mirror, downloaded into a per-user cache directory, and validated
against the mirror's `SHA256SUMS` before the USB device is changed. The ISO
writer copies ISO files to a new MBR (Legacy/CSM) or GPT (UEFI) USB partition;
it installs GRUB PC for MBR and verifies the ISO's UEFI fallback loader for
GPT. The writer requires at least 4 GiB of cache free space and USB capacity.
The cached ISO is removed after success, failure, or cancellation.

It is currently a work in progress. Maintenance is done by <a href="https://www.pardus.org.tr/">Pardus</a> team.

[![Packaging status](https://repology.org/badge/vertical-allrepos/pardus-usb-formatter.svg)](https://repology.org/project/pardus-usb-formatter/versions)

### **Dependencies**

This application is developed based on Python3 and GTK+ 3. Dependencies:
```bash
gir1.2-glib-2.0 gir1.2-gtk-3.0 python3-gi python3-pyudev
```

### **Run Application from Source**

Install dependencies
```bash
sudo apt install gir1.2-glib-2.0 gir1.2-gtk-3.0 python3-gi python3-pyudev
```
Clone the repository
```bash
git clone https://github.com/pardus/pardus-usb-formatter.git ~/pardus-usb-formatter
```
Run application
```bash
python3 ~/pardus-usb-formatter/src/Main.py
```

### **Build deb package**

```bash
sudo apt install devscripts git-buildpackage
sudo mk-build-deps -ir
gbp buildpackage --git-export-dir=/tmp/build/pardus-usb-formatter -us -uc
```

### **Screenshots**

![Pardus Usb Formatter 1](screenshots/pardus-usb-formatter-1.png)

![Pardus Usb Formatter 2](screenshots/pardus-usb-formatter-2.png)
