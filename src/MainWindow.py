import os, sys, subprocess, requests
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gio, Gtk

from USBDeviceManager import USBDeviceManager

import locale
from locale import gettext as tr

# Translation Constants:
APPNAME = "pardus-usb-formatter"
TRANSLATIONS_PATH = "/usr/share/locale"
SYSTEM_LANGUAGE = os.environ.get("LANG")

# Translation functions:
locale.bindtextdomain(APPNAME, TRANSLATIONS_PATH)
locale.textdomain(APPNAME)
locale.setlocale(locale.LC_ALL, SYSTEM_LANGUAGE)

class MainWindow:
    def __init__(self, application):
        # Gtk Builder
        self.builder = Gtk.Builder()

        # Translate things on glade:
        self.builder.set_translation_domain(APPNAME)

        # Import UI file:
        self.builder.add_from_file(os.path.dirname(os.path.abspath(__file__)) + "/../ui/MainWindow.glade")
        self.builder.connect_signals(self)

        # Window
        self.window = self.builder.get_object("window")
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_application(application)
        self.window.connect("destroy", self.onDestroy)

        self.defineComponents()
        self.isGUILocked = False

        # Get inserted USB devices            
        self.usbDevice = []
        self.usbManager = USBDeviceManager()
        self.usbManager.setUSBRefreshSignal(self.listUSBDevices)
        self.listUSBDevices()

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
        self.stack_buttons = self.builder.get_object("stack_buttons")
        self.btn_start = self.builder.get_object("btn_start")

        # Integrity
        self.cb_slowFormat = self.builder.get_object("cb_slowFormat")
        self.dialog_wait = self.builder.get_object("dialog_wait")
        self.dialog_wait.set_position(Gtk.WindowPosition.CENTER)

        # Dialog:
        self.dialog_write = self.builder.get_object("dialog_write")
        self.dialog_write.set_position(Gtk.WindowPosition.CENTER)
        self.dlg_lbl_format = self.builder.get_object("dlg_lbl_format")
        self.dlg_lbl_disk = self.builder.get_object("dlg_lbl_disk")
        self.dialog_about = self.builder.get_object("dialog_about")

    # USB Methods
    def listUSBDevices(self):
        if self.isGUILocked == True:
            return

        deviceList = self.usbManager.getUSBDevices()
        self.list_devices.clear()
        for device in deviceList:
            self.list_devices.append(device)

        self.cmb_devices.set_active(0)
        self.stack_buttons.set_visible_child_name("start")
        
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
        self.prepareWriting()
    
    def btn_cancel_clicked(self, button):
        self.cancelWriting()
    
    def btn_exit_clicked(self, button):
        self.window.get_application().quit()
    
    def btn_write_new_file_clicked(self, button):
        self.stack_windows.set_visible_child_name("main")
    
    def btn_information_clicked(self,button):
        self.dialog_about.run()
        self.dialog_about.hide()



    def prepareWriting(self):
        # Ask if it is ok?
        print(self.txt_deviceName.get_text())
        selectedFormat = self.cmb_formats.get_model()[self.cmb_formats.get_active_iter()][0]
        self.dlg_lbl_format.set_markup(f"- <b>{selectedFormat}</b>")
        self.dlg_lbl_disk.set_markup(f"- <b>{self.usbDevice[1]} [ {self.usbDevice[2]} ]</b> <i>( /dev/{self.usbDevice[0]} )</i>")

        response = self.dialog_write.run()
        self.dialog_write.hide()
        if response == Gtk.ResponseType.YES:
            self.lockGUI()
            self.startProcess([
                "pkexec",
                os.path.dirname(os.path.abspath(__file__))+"/USBFormatter.py", 
                '/dev/'+self.usbDevice[0],
                selectedFormat,
                "1" if self.cb_slowFormat.get_active() else "0",
                self.txt_deviceName.get_text()
            ])
            self.stack_windows.set_visible_child_name("waiting")
    
    def cancelWriting(self):
        subprocess.call(["pkexec", "kill", "-3", str(self.writerProcessPID)])

    # Handling Image Writer process
    def startProcess(self, params):
        self.writerProcessPID, _, stdout, _ = GLib.spawn_async(params,
                                    flags=GLib.SPAWN_SEARCH_PATH | GLib.SPAWN_LEAVE_DESCRIPTORS_OPEN | GLib.SPAWN_DO_NOT_REAP_CHILD,
                                    standard_input=False, standard_output=True, standard_error=True)
        GLib.io_add_watch(GLib.IOChannel(stdout), GLib.IO_IN | GLib.IO_HUP, self.onProcessStdout)
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self.writerProcessPID, self.onProcessExit)
    
    def onProcessStdout(self, source, condition):
        if condition == GLib.IO_HUP:
            return False
        
        line = source.readline().strip()
        print(line)
        return True
    
    def onProcessExit(self, pid, status):
        self.unlockGUI()

        self.listUSBDevices()

        self.dialog_wait.hide()

        if status == 0:
            self.sendNotification(tr("Formatting is finished."), tr("You can eject the USB disk."))
            self.stack_windows.set_visible_child_name("finished")
        elif status != 15 and status != 32256: # these are cancelling or auth error.
            dialog = Gtk.MessageDialog(
                self.window,
                0,
                Gtk.MessageType.ERROR,
                Gtk.ButtonsType.OK,
                tr("An error occured while formatting the disk."),
            )
            dialog.format_secondary_text(
                tr("Please make sure the USB device is connected properly, not used by any program and try again.")
            )
            dialog.run()
            dialog.destroy()
        
    def lockGUI(self, disableStart=False):
        self.cmb_formats.set_sensitive(False)
        self.cmb_devices.set_sensitive(False)
        self.cb_slowFormat.set_sensitive(False)

        self.stack_buttons.set_visible_child_name("cancel")
        self.isGUILocked = True
        
    def unlockGUI(self):
        self.cmb_formats.set_sensitive(True)
        self.cmb_devices.set_sensitive(True)
        self.cb_slowFormat.set_sensitive(True)

        self.stack_buttons.set_visible_child_name("start")
        self.isGUILocked = False
    
    def sendNotification(self, title, body):
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon(name="pardus-usb-formatter"))
        notification.set_default_action("app.notification-response::focus")
        self.application.send_notification(self.application.get_application_id(), notification)