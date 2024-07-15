#!/usr/bin/python3

import locale
from locale import gettext as _
from USBDeviceManager import USBDeviceManager
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gio, Gtk  # noqa


# Translation Constants:
APPNAME = "pardus-usb-formatter"
TRANSLATIONS_PATH = "/usr/share/locale"

# Translation functions:
locale.bindtextdomain(APPNAME, TRANSLATIONS_PATH)
locale.textdomain(APPNAME)


class MainWindow:
    def __init__(self, application, dev_file=None):
        self.dev_file = dev_file

        # Gtk Builder
        self.builder = Gtk.Builder()

        # Translate things on glade:
        self.builder.set_translation_domain(APPNAME)

        # Import UI file:
        self.builder.add_from_file(
            os.path.dirname(os.path.abspath(__file__)) + "/../ui/MainWindow.glade"
        )
        self.builder.connect_signals(self)

        # Window
        self.window = self.builder.get_object("window")
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_application(application)
        self.window.connect("destroy", self.onDestroy)

        self.defineComponents()

        # Get inserted USB devices
        self.usbDevice = []
        self.usbManager = USBDeviceManager()
        self.usbManager.setUSBRefreshSignal(self.listUSBDevices)
        self.listUSBDevices()

        # Set version
        # If can't get from `./__version__` file then accept version in MainWindow.glade file
        with open(
            os.path.dirname(os.path.abspath(__file__)) + "/__version__"
        ) as version_file:
            version = version_file.readline()
            self.dialog_about.set_version(version)

        self.dialog_about.set_program_name(_("Pardus USB Formatter"))
        if self.dialog_about.get_titlebar() is None:
            about_headerbar = Gtk.HeaderBar.new()
            about_headerbar.set_show_close_button(True)
            about_headerbar.set_title(_("About Pardus USB Formatter"))
            about_headerbar.pack_start(Gtk.Image.new_from_icon_name("pardus-usb-formatter", Gtk.IconSize.LARGE_TOOLBAR))
            about_headerbar.show_all()
            self.dialog_about.set_titlebar(about_headerbar)

        # Set application:
        self.application = application

        # Show Screen:
        self.window.show_all()

    # Window methods:
    def onDestroy(self, action):
        self.window.get_application().quit()

    def defineComponents(self):
        self.stack_windows = self.builder.get_object("stack_windows")

        # Main
        self.txt_deviceName = self.builder.get_object("txt_deviceName")
        self.list_devices = self.builder.get_object("list_devices")
        self.cmb_devices = self.builder.get_object("cmb_devices")
        self.list_formats = self.builder.get_object("list_formats")
        self.cmb_formats = self.builder.get_object("cmb_formats")
        self.btn_start = self.builder.get_object("btn_start")
        self.pb_writingProgress = self.builder.get_object("pb_writingProgress")
        self.btn_cancelWriting = self.builder.get_object("btn_cancelWriting")

        # Integrity
        self.cb_slowFormat = self.builder.get_object("cb_slowFormat")

        # Dialog:
        self.dialog_write = self.builder.get_object("dialog_write")
        self.dialog_write.set_position(Gtk.WindowPosition.CENTER)
        self.dlg_lbl_format = self.builder.get_object("dlg_lbl_format")
        self.dlg_lbl_disk = self.builder.get_object("dlg_lbl_disk")
        self.dialog_about = self.builder.get_object("dialog_about")

    # USB Methods
    def listUSBDevices(self):
        deviceList = self.usbManager.getUSBDevices()
        self.list_devices.clear()

        active_id = ""
        for device in deviceList:
            self.list_devices.append(device)
            if self.dev_file is not None and device[0] in self.dev_file:
                self.cmb_devices.set_active_id(device[0])
                active_id = device[0]

        if active_id != "":
            self.cmb_devices.set_active_id(active_id)
        else:
            self.cmb_devices.set_active(0)

        if len(deviceList) == 0:
            self.btn_start.set_sensitive(False)
        else:
            self.btn_start.set_sensitive(True)

    # UI Signals:
    def cmb_devices_changed(self, combobox):
        tree_iter = combobox.get_active_iter()
        if tree_iter:
            model = combobox.get_model()
            deviceInfo = model[tree_iter][:3]
            self.usbDevice = deviceInfo
        else:
            self.btn_start.set_sensitive(False)

    # Buttons:
    def btn_start_clicked(self, button):
        if self.formatting_rule_checks():
            self.pb_writingProgress.set_visible(self.cb_slowFormat.get_active())
            self.btn_cancelWriting.set_visible(self.cb_slowFormat.get_active())

            GLib.idle_add(self.prepare_writing)

    def btn_exit_clicked(self, button):
        self.window.get_application().quit()

    def btn_write_new_file_clicked(self, button):
        self.stack_windows.set_visible_child_name("main")

    def btn_information_clicked(self, button):
        self.dialog_about.run()
        self.dialog_about.hide()

    def btn_cancelWriting_clicked(self, button):
        subprocess.call(["pkexec", "kill", "-SIGTERM", str(self.writerProcessPID)])

    def prepare_writing(self):
        # Ask if it is ok?
        selectedFormat = self.cmb_formats.get_model()[
            self.cmb_formats.get_active_iter()
        ][0]
        self.dlg_lbl_format.set_markup(f"- <b>{selectedFormat}</b>")
        self.dlg_lbl_disk.set_markup(
            f"- <b>{self.usbDevice[1]} [ {self.usbDevice[2]} ]</b> <i>( /dev/{self.usbDevice[0]} )</i>"
        )

        response = self.dialog_write.run()
        self.dialog_write.hide()
        if response == Gtk.ResponseType.YES:
            self.startProcess(
                [
                    "pkexec",
                    os.path.dirname(os.path.abspath(__file__)) + "/USBFormatter.py",
                    "/dev/" + self.usbDevice[0],
                    selectedFormat,
                    "1" if self.cb_slowFormat.get_active() else "0",
                    self.txt_deviceName.get_text(),
                ]
            )
            self.stack_windows.set_visible_child_name("waiting")

    # Handling Image Writer process
    def startProcess(self, params):
        self.writerProcessPID, _, stdout, _ = GLib.spawn_async(
            params,
            flags=GLib.SPAWN_SEARCH_PATH
            | GLib.SPAWN_LEAVE_DESCRIPTORS_OPEN
            | GLib.SPAWN_DO_NOT_REAP_CHILD,
            standard_input=False,
            standard_output=True,
            standard_error=True,
        )
        GLib.io_add_watch(
            GLib.IOChannel(stdout),
            GLib.PRIORITY_LOW,
            GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self.onProcessStdout,
        )
        GLib.child_watch_add(
            GLib.PRIORITY_DEFAULT, self.writerProcessPID, self.onProcessExit
        )

    def onProcessStdout(self, source, condition):
        if condition == GLib.IOCondition.HUP or condition == GLib.IOCondition.ERR:
            return False

        io_status, line, line_length, terminator_pos = source.read_line()
        if io_status != GLib.IOStatus.NORMAL or line_length == 0:
            return True

        line = line.strip()
        if len(line) != 0 and line[0:8] == "PROGRESS":
            writtenBytes = int(line.split("|")[1])
            totalBytes = int(line.split("|")[2])
            percent = writtenBytes / totalBytes

            self.pb_writingProgress.set_text(
                "{}MB / {}MB (%{})".format(
                    round(writtenBytes / 1000 / 1000),
                    round(totalBytes / 1000 / 1000),
                    int(percent * 100),
                )
            )
            self.pb_writingProgress.set_fraction(percent)

        return True

    def onProcessExit(self, pid, status):
        self.pb_writingProgress.set_fraction(0)
        self.pb_writingProgress.set_text(_("Formatting"))

        if status == 0:
            self.sendNotification(
                _("Formatting is finished."), _("You can eject the USB disk.")
            )
            self.stack_windows.set_visible_child_name("finished")
        elif status != 15 and status != 32256 and status != 32512:  # these are cancelling or auth error.
            dialog = Gtk.MessageDialog(
                self.window,
                0,
                Gtk.MessageType.ERROR,
                Gtk.ButtonsType.OK,
                _("An error occured while formatting the disk."),
            )
            dialog.format_secondary_text(
                _(
                    "Please make sure the USB device is connected properly, not used by any program and try again."
                )
            )
            dialog.run()
            dialog.destroy()
            self.stack_windows.set_visible_child_name("finished")
        else:
            self.stack_windows.set_visible_child_name("main")

    def sendNotification(self, title, body):
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon(name="pardus-usb-formatter"))
        notification.set_default_action("app.notification-response::focus")
        self.application.send_notification(
            self.application.get_application_id(), notification
        )

    def formatting_rule_checks(self):
        selectedFormat = self.cmb_formats.get_model()[
            self.cmb_formats.get_active_iter()
        ][0]
        newDeviceName = self.txt_deviceName.get_text()

        if selectedFormat == "FAT32":
            if len(newDeviceName) > 11:
                self.show_error_dialog(
                    _("Device name is too long."),
                    _(
                        "{} format supports maximum {} characters.".format(
                            "FAT32", "11"
                        )
                    ),
                )
                return False

            try:
                newDeviceName.encode("cp850", errors="strict")
            except ValueError:
                self.show_error_dialog(
                    _("Device name contains invalid characters."),
                    _("FAT32 format only supports ASCII characters."),
                )
                return False
        elif selectedFormat == "NTFS":
            if len(newDeviceName) > 32:
                self.show_error_dialog(
                    _("Device name is too long."),
                    _("{} format supports maximum {} characters.".format("NTFS", "32")),
                )
                return False

        elif selectedFormat == "EXFAT":
            if len(newDeviceName) > 11:
                self.show_error_dialog(
                    _("Device name is too long."),
                    _(
                        "{} format supports maximum {} characters.".format(
                            "EXFAT", "11"
                        )
                    ),
                )
                return False
        elif selectedFormat == "EXT4":
            if len(newDeviceName) > 16:
                self.show_error_dialog(
                    _("Device name is too long."),
                    _("{} format supports maximum {} characters.".format("EXT4", "16")),
                )
                return False

        # Everything is ok:
        return True

    def show_error_dialog(self, primary, secondary):
        dialog = Gtk.MessageDialog(
            self.window,
            0,
            Gtk.MessageType.ERROR,
            Gtk.ButtonsType.OK,
            primary,
        )
        dialog.format_secondary_text(secondary)
        dialog.run()
        dialog.destroy()
