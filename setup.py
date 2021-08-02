#!/usr/bin/env python3
from setuptools import setup, find_packages, os

changelog = 'debian/changelog'
version = ""
if os.path.exists(changelog):
    head = open(changelog).readline()
    try:
        version = head.split("(")[1].split(")")[0]
    except:
        print("debian/changelog format is wrong for get version")
    f = open('src/__version__', 'w')
    f.write(version)
    f.close()

copyfile("icon.svg", "pardus-usb-formatter.svg")

data_files = [
    ("/usr/share/applications/", ["tr.org.pardus.usb-formatter.desktop"]),
    ("/usr/share/locale/tr/LC_MESSAGES/", ["translations/tr/LC_MESSAGES/pardus-usb-formatter.mo"]),
    ("/usr/share/pardus/pardus-usb-formatter/", ["icon.svg", "main.svg"]),
    ("/usr/share/pardus/pardus-usb-formatter/src", ["src/main.py", "src/MainWindow.py", "src/USBFormatter.py", "src/USBDeviceManager.py", "src/__version__"]),
    ("/usr/share/pardus/pardus-usb-formatter/ui", ["ui/MainWindow.glade"]),
    ("/usr/share/polkit-1/actions", ["tr.org.pardus.pkexec.pardus-usb-formatter.policy"]),
    ("/usr/bin/", ["pardus-usb-formatter"]),
    ("/usr/share/icons/hicolor/scalable/apps/", ["pardus-usb-formatter.svg"])
]

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
    url="https://www.pardus.org.tr",
)
