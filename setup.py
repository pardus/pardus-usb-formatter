#!/usr/bin/env python3
import os
import subprocess

from setuptools import setup, find_packages


def create_mo_files():
    podir = "po"
    mo = []
    for po in os.listdir(podir):
        if po.endswith(".po"):
            os.makedirs("{}/{}/LC_MESSAGES".format(podir, po.split(".po")[0]), exist_ok=True)
            mo_file = "{}/{}/LC_MESSAGES/{}".format(podir, po.split(".po")[0], "pardus-usb-formatter.mo")
            msgfmt_cmd = 'msgfmt {} -o {}'.format(podir + "/" + po, mo_file)
            subprocess.call(msgfmt_cmd, shell=True)
            mo.append(("/usr/share/locale/" + po.split(".po")[0] + "/LC_MESSAGES",
                       ["po/" + po.split(".po")[0] + "/LC_MESSAGES/pardus-usb-formatter.mo"]))
    return mo


changelog = 'debian/changelog'
version = "0.1.0"
if os.path.exists(changelog):
    head = open(changelog).readline()
    try:
        version = head.split("(")[1].split(")")[0]
    except:
        print("debian/changelog format is wrong for get version")
    f = open('src/__version__', 'w')
    f.write(version)
    f.close()

data_files = [
                 ("/usr/share/applications/",
                  ["tr.org.pardus.usb-formatter.desktop"]),
                 ("/usr/share/pardus/pardus-usb-formatter/",
                  ["pardus-usb-formatter.svg", "main.svg"]),
                 ("/usr/share/pardus/pardus-usb-formatter/src",
                  ["src/Main.py",
                   "src/MainWindow.py",
                   "src/USBFormatter.py",
                   "src/USBDeviceManager.py",
                   "src/__version__"]),
                 ("/usr/share/pardus/pardus-usb-formatter/ui",
                  ["ui/MainWindow.glade"]),
                 ("/usr/share/polkit-1/actions",
                  ["tr.org.pardus.pkexec.pardus-usb-formatter.policy"]),
                 ("/usr/bin/",
                  ["pardus-usb-formatter"]),
                 ("/usr/share/icons/hicolor/scalable/apps/",
                  ["pardus-usb-formatter.svg"])
             ] + create_mo_files()

setup(
    name="Pardus USB Formatter",
    version=version,
    packages=find_packages(),
    scripts=["pardus-usb-formatter"],
    install_requires=["PyGObject"],
    data_files=data_files,
    author="Emin Fedar",
    author_email="emin.fedar@pardus.org.tr",
    description="Pardus USB Formatter.",
    license="GPLv3",
    keywords="usb format pardus",
    url="https://github.com/pardus/pardus-usb-formatter",
)
