#!/usr/bin/python3

import locale
from locale import gettext as _
import shutil
import tempfile
from USBDeviceManager import USBDeviceManager
from downloader import DownloadCancelled, PardusMirrorClient
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gio, Gtk  # noqa


# Translation Constants:
APPNAME = "pardus-usb-formatter"
TRANSLATIONS_PATH = "/usr/share/locale"
MINIMUM_ISO_STORAGE = 4 * 1024 * 1024 * 1024

# Translation functions:
locale.bindtextdomain(APPNAME, TRANSLATIONS_PATH)
locale.textdomain(APPNAME)


class MainWindow:
    def __init__(self, application, dev_file=None):
        self.dev_file = dev_file
        self.iso_cancel_event = None
        self.iso_operation_active = False
        self.iso_writer_pid = None
        self.iso_writer_verified = False
        self.iso_writer_errors = []
        self.iso_device_name = None
        self.iso_temp_dir = None

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
        self.cryptOk = True
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
        self.cb_encrypt.connect("toggled", self.onEncryptChanged)

        # Show Screen:
        self.window.show_all()
        # show_all() updates child visibility after the ISO tab re-parents main.
        # Set both stacks afterwards so startup can never show the result page.
        self.mode_stack.set_visible_child_name("format")
        self.stack_windows.set_visible_child(self.main_page)

    def onEncryptChanged(self, *args):
        self.ui_revealer_encrypt.set_reveal_child(
            self.cb_encrypt.get_active()
        )

    # Window methods:
    def onDestroy(self, action):
        self._cancel_iso_operation()
        # A downloader has no privileged helper to clean up after the GTK loop exits.
        if self.iso_writer_pid is None:
            self._cleanup_iso_temp_dir()
        self.window.get_application().quit()

    def defineComponents(self):
        self.stack_windows = self.builder.get_object("stack_windows")
        self.page_format = self.builder.get_object("page_format")
        self.page_finished = self.builder.get_object("page_finished")

        # Main
        self.txt_deviceName = self.builder.get_object("txt_deviceName")
        self.txt_password = self.builder.get_object("txt_password")
        self.list_devices = self.builder.get_object("list_devices")
        self.cmb_devices = self.builder.get_object("cmb_devices")
        self.list_formats = self.builder.get_object("list_formats")
        self.cmb_formats = self.builder.get_object("cmb_formats")
        self.btn_start = self.builder.get_object("btn_start")
        self.pb_writingProgress = self.builder.get_object("pb_writingProgress")
        self.btn_cancelWriting = self.builder.get_object("btn_cancelWriting")
        self.lbl_waiting_title = self.builder.get_object("lbl_waiting_title")
        self.lbl_waiting_description = self.builder.get_object("lbl_waiting_description")
        self.ui_revealer_encrypt = self.builder.get_object("ui_revealer_encrypt")
        self._build_mode_selector()

        # Integrity
        self.cb_slowFormat = self.builder.get_object("cb_slowFormat")
        self.cb_encrypt = self.builder.get_object("cb_encrypt")

        # Dialog:
        self.dialog_write = self.builder.get_object("dialog_write")
        self.dialog_write.set_position(Gtk.WindowPosition.CENTER)
        self.dlg_lbl_format = self.builder.get_object("dlg_lbl_format")
        self.dlg_lbl_disk = self.builder.get_object("dlg_lbl_disk")
        self.dialog_about = self.builder.get_object("dialog_about")

    def _build_mode_selector(self):
        self.stack_windows.remove(self.page_format)

        mode_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mode_page.set_margin_start(13)
        mode_page.set_margin_end(13)
        mode_page.set_margin_top(10)
        mode_page.set_margin_bottom(13)
        self.mode_stack = Gtk.Stack()
        self.mode_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.mode_stack.set_transition_duration(200)
        self.mode_stack.add_titled(self.page_format, "format", _("Format USB"))
        self.mode_stack.add_titled(self._build_iso_page(), "iso", _("Write ISO"))

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.mode_stack)
        switcher.set_halign(Gtk.Align.CENTER)
        mode_page.pack_start(switcher, False, False, 0)
        mode_page.pack_start(self.mode_stack, True, True, 0)
        self.stack_windows.add_named(mode_page, "main")
        self.main_page = mode_page
        self.mode_stack.set_visible_child_name("format")
        self.stack_windows.set_visible_child(self.main_page)

    def _build_iso_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_top(8)

        title = Gtk.Label()
        title.set_markup("<b><big>{}</big></b>".format(_("Write a Pardus ISO")))
        page.pack_start(title, False, False, 0)

        source_row = Gtk.Box(spacing=8)
        source_icon = Gtk.Image.new_from_icon_name(
            "folder-download-symbolic", Gtk.IconSize.BUTTON
        )
        source_row.pack_start(source_icon, False, False, 0)
        self.cmb_iso_source = Gtk.ComboBoxText()
        self.cmb_iso_source.append("gnome", _("Pardus GNOME (Current)"))
        self.cmb_iso_source.append("xfce", _("Pardus XFCE (Current)"))
        self.cmb_iso_source.append("local", _("Choose local ISO file"))
        self.cmb_iso_source.set_active_id("gnome")
        source_row.pack_start(self.cmb_iso_source, True, True, 0)
        page.pack_start(source_row, False, False, 0)

        device_row = Gtk.Box(spacing=8)
        device_icon = Gtk.Image.new_from_icon_name(
            "drive-removable-media-symbolic", Gtk.IconSize.BUTTON
        )
        device_row.pack_start(device_icon, False, False, 0)
        self.cmb_iso_devices = Gtk.ComboBox.new_with_model(self.list_devices)
        self.cmb_iso_devices.set_id_column(0)
        for column in (1, 2):
            renderer = Gtk.CellRendererText()
            self.cmb_iso_devices.pack_start(renderer, column == 1)
            self.cmb_iso_devices.add_attribute(renderer, "text", column)
        device_row.pack_start(self.cmb_iso_devices, True, True, 0)
        page.pack_start(device_row, False, False, 0)

        scheme_row = Gtk.Box(spacing=8)
        scheme_icon = Gtk.Image.new_from_icon_name(
            "drive-harddisk-symbolic", Gtk.IconSize.BUTTON
        )
        scheme_row.pack_start(scheme_icon, False, False, 0)
        scheme_label = Gtk.Label(label=_("Partition Scheme"))
        scheme_label.set_xalign(0)
        scheme_row.pack_start(scheme_label, False, False, 0)
        self.cmb_iso_partition_table = Gtk.ComboBoxText()
        self.cmb_iso_partition_table.append("msdos", _("MBR (Legacy/CSM)"))
        self.cmb_iso_partition_table.append("gpt", _("GPT (UEFI)"))
        self.cmb_iso_partition_table.set_active_id("gpt")
        scheme_row.pack_start(self.cmb_iso_partition_table, True, True, 0)
        page.pack_start(scheme_row, False, False, 0)

        warning = Gtk.Label(label=_("All data on the selected USB device will be erased."))
        warning.set_xalign(0)
        warning.get_style_context().add_class("error")
        page.pack_start(warning, False, False, 0)

        self.pb_iso_progress = Gtk.ProgressBar()
        self.pb_iso_progress.set_show_text(True)
        self.pb_iso_progress.set_text(_("Ready to write"))
        page.pack_start(self.pb_iso_progress, False, False, 0)

        self.lbl_iso_status = Gtk.Label(label=_("Select a source and target USB device."))
        self.lbl_iso_status.set_xalign(0)
        self.lbl_iso_status.set_line_wrap(True)
        page.pack_start(self.lbl_iso_status, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.btn_start_iso = Gtk.Button.new_with_label(_("Write ISO"))
        self.btn_start_iso.set_image(
            Gtk.Image.new_from_icon_name("media-optical-symbolic", Gtk.IconSize.BUTTON)
        )
        self.btn_start_iso.set_always_show_image(True)
        self.btn_start_iso.get_style_context().add_class("suggested-action")
        self.btn_start_iso.connect("clicked", self.btn_start_iso_clicked)
        buttons.pack_start(self.btn_start_iso, True, True, 0)
        self.btn_cancel_iso = Gtk.Button.new_with_label(_("Cancel"))
        self.btn_cancel_iso.set_sensitive(False)
        self.btn_cancel_iso.get_style_context().add_class("destructive-action")
        self.btn_cancel_iso.connect("clicked", self.btn_cancel_iso_clicked)
        buttons.pack_start(self.btn_cancel_iso, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

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

        if hasattr(self, "cmb_iso_devices"):
            if active_id != "":
                self.cmb_iso_devices.set_active_id(active_id)
            else:
                self.cmb_iso_devices.set_active(0)

        if len(deviceList) == 0:
            self.btn_start.set_sensitive(False)
            self.btn_start_iso.set_sensitive(False)
        else:
            self.btn_start.set_sensitive(True)
            if not self.iso_operation_active:
                self.btn_start_iso.set_sensitive(True)

        if self.iso_operation_active and self.iso_device_name not in [device[0] for device in deviceList]:
            GLib.idle_add(self._iso_device_removed)

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
    def on_txt_password_icon_press(self, entry, icon_pos, event):
        entry.set_visibility(True)
        entry.set_icon_from_icon_name(icon_pos, "view-conceal-symbolic")

    def on_txt_password_icon_release(self, entry, icon_pos, event):
        entry.set_visibility(False)
        entry.set_icon_from_icon_name(icon_pos, "view-reveal-symbolic")

    def btn_start_clicked(self, button):
        if self.formatting_rule_checks():
            self.pb_writingProgress.set_visible(self.cb_slowFormat.get_active())
            self.btn_cancelWriting.set_visible(self.cb_slowFormat.get_active())

            GLib.idle_add(self.prepare_writing)

    def btn_exit_clicked(self, button):
        self.window.get_application().quit()

    def btn_write_new_file_clicked(self, button):
        self.stack_windows.set_visible_child(self.main_page)

    def btn_information_clicked(self, button):
        self.dialog_about.run()
        self.dialog_about.hide()

    def btn_cancelWriting_clicked(self, button):
        if hasattr(self, "writerProcessPID"):
            subprocess.call(["pkexec", "kill", "-SIGTERM", str(self.writerProcessPID)])

    # ISO file-copy writer methods
    def btn_start_iso_clicked(self, button):
        if self.iso_operation_active:
            return
        device = self._selected_device(self.cmb_iso_devices)
        if device is None:
            self.show_error_dialog(_("USB device required."), _("Select a target USB device."))
            return
        if not self._has_iso_storage(device[0]):
            return
        if not self._confirm_iso_write(device):
            return

        self.iso_device_name = device[0]
        self.iso_cancel_event = threading.Event()
        self.iso_operation_active = True
        self.iso_writer_verified = False
        self.btn_start_iso.set_sensitive(False)
        self.cmb_iso_source.set_sensitive(False)
        self.cmb_iso_devices.set_sensitive(False)
        self.cmb_iso_partition_table.set_sensitive(False)
        self.btn_cancel_iso.set_sensitive(True)
        self.pb_iso_progress.set_fraction(0)

        source = self.cmb_iso_source.get_active_id()
        local_file = None
        if source == "local":
            local_file = self._choose_local_iso()
            if local_file is None:
                self._finish_iso_operation()
                return

        try:
            self._create_iso_temp_dir()
        except OSError as error:
            self._show_iso_error(str(error))
            return

        if source == "local":
            self.lbl_iso_status.set_text(_("Preparing local ISO..."))
            self.pb_iso_progress.pulse()
            threading.Thread(
                target=self._stage_local_iso,
                args=(device[0], local_file),
                daemon=True,
            ).start()
            return

        self.lbl_iso_status.set_text(_("Looking up the current Pardus ISO..."))
        self.pb_iso_progress.pulse()
        threading.Thread(
            target=self._discover_iso_image,
            args=(source.upper(), device[0]),
            daemon=True,
        ).start()

    def btn_cancel_iso_clicked(self, button):
        self._cancel_iso_operation()

    def _discover_iso_image(self, desktop, device_name):
        cancel_event = self.iso_cancel_event
        try:
            images = PardusMirrorClient().discover_latest(cancel_event)
            if cancel_event.is_set():
                GLib.idle_add(self._finish_iso_operation)
            else:
                image = next(image for image in images if image.desktop == desktop)
                target_path = os.path.join(self.iso_temp_dir, image.filename)
                GLib.idle_add(
                    self.lbl_iso_status.set_text, _("Downloading {}...").format(image.filename)
                )
                PardusMirrorClient().download(
                    image,
                    target_path,
                    self._iso_download_progress,
                    cancel_event,
                )
                if cancel_event.is_set():
                    GLib.idle_add(self._finish_iso_operation)
                else:
                    GLib.idle_add(
                        self._start_iso_writer,
                        device_name,
                        target_path,
                        image.sha256,
                        True,
                    )
        except DownloadCancelled:
            GLib.idle_add(self._finish_iso_operation)
        except Exception as error:
            if cancel_event.is_set():
                GLib.idle_add(self._finish_iso_operation)
            else:
                GLib.idle_add(self._show_iso_error, str(error))

    def _stage_local_iso(self, device_name, source_path):
        cancel_event = self.iso_cancel_event
        try:
            target_path = os.path.join(self.iso_temp_dir, os.path.basename(source_path))
            checksum = PardusMirrorClient().stage_local_file(
                source_path,
                target_path,
                self._iso_staging_progress,
                cancel_event,
            )
            if cancel_event.is_set():
                GLib.idle_add(self._finish_iso_operation)
            else:
                GLib.idle_add(
                    self._start_iso_writer,
                    device_name,
                    target_path,
                    checksum,
                    False,
                )
        except DownloadCancelled:
            GLib.idle_add(self._finish_iso_operation)
        except Exception as error:
            if cancel_event.is_set():
                GLib.idle_add(self._finish_iso_operation)
            else:
                GLib.idle_add(self._show_iso_error, str(error))

    def _iso_download_progress(self, written, total):
        GLib.idle_add(self._update_iso_download_progress, written, total, False)

    def _iso_staging_progress(self, written, total):
        GLib.idle_add(self._update_iso_download_progress, written, total, True)

    def _update_iso_download_progress(self, written, total, local_source):
        action = _("Preparing local ISO") if local_source else _("Downloading")
        if total:
            percent = min(1, written / total)
            self.pb_iso_progress.set_fraction(percent)
            self.pb_iso_progress.set_text("{}%".format(int(percent * 100)))
            self.lbl_iso_status.set_text("{}: {}%".format(action, int(percent * 100)))
        else:
            self.pb_iso_progress.pulse()
            self.lbl_iso_status.set_text(
                "{}: {} MB".format(action, round(written / 1000 / 1000))
            )
        return False

    def _start_iso_writer(self, device_name, iso_path, checksum, official_checksum):
        if self.iso_cancel_event is None or self.iso_cancel_event.is_set():
            return self._finish_iso_operation()
        self.iso_writer_verified = official_checksum
        self.iso_writer_errors = []
        self.lbl_iso_status.set_text(_("Formatting USB device..."))
        self.pb_iso_progress.set_fraction(0)
        self.pb_iso_progress.pulse()
        command = [
            "pkexec",
            os.path.dirname(os.path.abspath(__file__)) + "/ISOWriter.py",
            "--device",
            device_name,
            "--iso-path",
            iso_path,
            "--sha256",
            checksum,
            "--partition-table",
            self.cmb_iso_partition_table.get_active_id(),
            "--cleanup-directory",
            self.iso_temp_dir,
            "--cleanup-root",
            self._iso_cache_directory(),
        ]
        self.iso_writer_pid, stdin_fd, stdout, stderr_fd = GLib.spawn_async(
            command,
            flags=GLib.SPAWN_SEARCH_PATH
            | GLib.SPAWN_LEAVE_DESCRIPTORS_OPEN
            | GLib.SPAWN_DO_NOT_REAP_CHILD,
            standard_input=False,
            standard_output=True,
            standard_error=True,
        )
        GLib.io_add_watch(
            GLib.IOChannel(stdout),
            GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self.onISOProcessStdout,
        )
        GLib.io_add_watch(
            GLib.IOChannel(stderr_fd),
            GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self.onISOProcessStderr,
        )
        GLib.child_watch_add(GLib.PRIORITY_LOW, self.iso_writer_pid, self.onISOProcessExit)
        return False

    def onISOProcessStdout(self, source, condition):
        if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR) and not condition & GLib.IOCondition.IN:
            return False
        io_status, line, line_length, terminator_pos = source.read_line()
        if io_status != GLib.IOStatus.NORMAL or line_length == 0:
            return True
        message = line.strip()
        fields = message.split("|", 1)
        if fields[0] == "STATUS" and len(fields) == 2:
            self._set_iso_writer_status(fields[1])
        elif fields[0] == "ERROR" and len(fields) == 2:
            self._record_iso_writer_error(fields[1])
        elif fields[0] == "LOG" and len(fields) == 2:
            print("ISOWriter: {}".format(fields[1]), file=sys.stderr, flush=True)
        elif message:
            print("ISOWriter: {}".format(message), file=sys.stderr, flush=True)
        return True

    def onISOProcessStderr(self, source, condition):
        if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR) and not condition & GLib.IOCondition.IN:
            return False
        io_status, line, line_length, terminator_pos = source.read_line()
        if io_status != GLib.IOStatus.NORMAL or line_length == 0:
            return True
        self._record_iso_writer_error(line.strip())
        return True

    def _record_iso_writer_error(self, message):
        if message:
            self.iso_writer_errors.append(message)
            print("ISOWriter error: {}".format(message), file=sys.stderr, flush=True)

    def _set_iso_writer_status(self, status):
        messages = {
            "verifying": _("Verifying ISO checksum..."),
            "formatting": _("Formatting USB device..."),
            "copying": _("Copying ISO files..."),
            "installing_bootloader": _("Installing bootloader..."),
        }
        self.pb_iso_progress.pulse()
        self.lbl_iso_status.set_text(messages.get(status, _("Preparing USB device...")))

    def onISOProcessExit(self, pid, status):
        cancelled = self.iso_cancel_event is not None and self.iso_cancel_event.is_set()
        verified = self.iso_writer_verified
        self._finish_iso_operation()
        if status == 0:
            message = (
                _("ISO files were copied and SHA-256 was verified.")
                if verified
                else _("Local ISO files were copied successfully. Its SHA-256 was calculated before writing.")
            )
            self.lbl_iso_status.set_text(message)
            self.pb_iso_progress.set_fraction(1)
            self.pb_iso_progress.set_text(_("Complete"))
            self.sendNotification(_("ISO writing is finished."), message)
        elif cancelled:
            self.lbl_iso_status.set_text(_("ISO operation cancelled. The USB device may contain incomplete files."))
        else:
            error = "\n".join(self.iso_writer_errors[-8:])
            self._show_iso_error(
                error or _("The ISO writer exited without an error message.")
            )

    def _choose_local_iso(self):
        chooser = Gtk.FileChooserDialog(
            title=_("Choose ISO file"), parent=self.window, action=Gtk.FileChooserAction.OPEN
        )
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Open"), Gtk.ResponseType.ACCEPT)
        iso_filter = Gtk.FileFilter()
        iso_filter.set_name(_("ISO images"))
        iso_filter.add_pattern("*.iso")
        chooser.add_filter(iso_filter)
        response = chooser.run()
        filename = chooser.get_filename()
        chooser.destroy()
        return filename if response == Gtk.ResponseType.ACCEPT else None

    def _confirm_iso_write(self, device):
        dialog = Gtk.MessageDialog(
            self.window,
            Gtk.DialogFlags.MODAL,
            Gtk.MessageType.WARNING,
            Gtk.ButtonsType.CANCEL,
            _("Write ISO to /dev/{}?").format(device[0]),
        )
        dialog.format_secondary_text(
            _("All data on {} ({}) will be permanently deleted.").format(device[1], device[2])
        )
        dialog.add_button(_("Write ISO"), Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.ACCEPT

    @staticmethod
    def _selected_device(combobox):
        tree_iter = combobox.get_active_iter()
        return combobox.get_model()[tree_iter][:3] if tree_iter else None

    def _cancel_iso_operation(self):
        if self.iso_cancel_event is None:
            return
        self.iso_cancel_event.set()
        self.btn_cancel_iso.set_sensitive(False)
        self.lbl_iso_status.set_text(_("Cancelling ISO operation..."))
        if self.iso_writer_pid is not None:
            subprocess.Popen(
                [
                    "pkexec",
                    os.path.dirname(os.path.abspath(__file__)) + "/ISOWriter.py",
                    "--cancel-pid",
                    str(self.iso_writer_pid),
                ]
            )

    def _iso_device_removed(self):
        if self.iso_operation_active:
            self._cancel_iso_operation()
            self.lbl_iso_status.set_text(_("USB device was removed. Stopping ISO writing..."))
        return False

    def _finish_iso_operation(self):
        self.iso_operation_active = False
        self.iso_writer_pid = None
        self.iso_cancel_event = None
        self.iso_device_name = None
        self._cleanup_iso_temp_dir()
        self.cmb_iso_source.set_sensitive(True)
        self.cmb_iso_devices.set_sensitive(True)
        self.cmb_iso_partition_table.set_sensitive(True)
        self.btn_start_iso.set_sensitive(bool(self.usbManager.getUSBDevices()))
        self.btn_cancel_iso.set_sensitive(False)
        return False

    def _show_iso_error(self, error):
        self._finish_iso_operation()
        self.lbl_iso_status.set_text(_("ISO writing failed."))
        self.show_error_dialog(_("Pardus ISO writing failed."), error)
        return False

    def _create_iso_temp_dir(self):
        self._cleanup_iso_temp_dir()
        cache_directory = self._iso_cache_directory()
        os.makedirs(cache_directory, mode=0o700, exist_ok=True)
        self.iso_temp_dir = tempfile.mkdtemp(
            prefix="pardus-usb-formatter-", dir=cache_directory
        )

    @staticmethod
    def _device_capacity(device_name):
        if device_name != os.path.basename(device_name):
            raise ValueError("Invalid USB device name")
        with open("/sys/block/{}/size".format(device_name)) as size_file:
            sectors = int(size_file.read().strip())
        with open("/sys/block/{}/queue/logical_block_size".format(device_name)) as block_file:
            block_size = int(block_file.read().strip())
        return sectors * block_size

    @staticmethod
    def _iso_cache_directory():
        return os.path.join(GLib.get_user_cache_dir(), "pardus-usb-formatter")

    def _has_iso_storage(self, device_name):
        try:
            cache_directory = self._iso_cache_directory()
            os.makedirs(cache_directory, mode=0o700, exist_ok=True)
            cache_free = shutil.disk_usage(cache_directory).free
            device_capacity = self._device_capacity(device_name)
        except (OSError, ValueError) as error:
            self.show_error_dialog(_("Insufficient disk space."), str(error))
            return False

        if cache_free < MINIMUM_ISO_STORAGE:
            self.show_error_dialog(
                _("Insufficient disk space."),
                _("At least 4 GiB of free space is required in {}.").format(
                    cache_directory
                ),
            )
            return False
        if device_capacity < MINIMUM_ISO_STORAGE:
            self.show_error_dialog(
                _("Insufficient disk space."),
                _("The target USB device must have at least 4 GiB of capacity."),
            )
            return False
        return True

    def _cleanup_iso_temp_dir(self):
        if self.iso_temp_dir:
            shutil.rmtree(self.iso_temp_dir, ignore_errors=True)
            self.iso_temp_dir = None

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
            process_command = [
                "pkexec",
                os.path.dirname(os.path.abspath(__file__)) + "/USBFormatter.py",
                "--device",
                self.usbDevice[0],
                "--type",
                selectedFormat,
                "--label",
                self.txt_deviceName.get_text(),
            ]
            if self.cb_slowFormat.get_active():
                process_command += ["--fill"]
            if self.cb_encrypt.get_active():
                process_command += ["--crypt", self.txt_password.get_text()]
            self.startProcess(process_command)
            self.stack_windows.set_visible_child_name("waiting")

    # Handling Image Writer process
    def startProcess(self, params):
        self.writerProcessPID, stdin_fd, stdout, stderr_fd = GLib.spawn_async(
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
            self.stack_windows.set_visible_child(self.main_page)
        else:
            self.stack_windows.set_visible_child(self.main_page)

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

        if self.cb_encrypt.get_active():
            if len(self.txt_password.get_text()) == 0:
                self.show_error_dialog(
                    _("Password required."),
                    _("Please provide a password for encrypt."),
                )
                return False


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
