#!/usr/bin/env python3
from setuptools import setup, find_packages

data_files = [
    ("/usr/share/applications/", ["tr.org.pardus.usb-formatter.desktop"]),
    ("/usr/share/locale/tr/LC_MESSAGES/", ["translations/tr/LC_MESSAGES/pardus-usb-formatter.mo"]),
    ("/usr/share/pardus/pardus-usb-formatter/", ["icon.svg", "main.svg"]),
    ("/usr/share/pardus/pardus-usb-formatter/src", ["src/main.py", "src/MainWindow.py", "src/USBFormatter.py", "src/USBDeviceManager.py"]),
    ("/usr/share/pardus/pardus-usb-formatter/ui", ["ui/MainWindow.glade"]),
    ("/usr/share/polkit-1/actions", ["tr.org.pardus.pkexec.pardus-usb-formatter.policy"]),
    ("/usr/bin/", ["pardus-usb-formatter"])
]

setup(
    name="Pardus USB Formatter",
    version="0.2.0~Beta1",
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
