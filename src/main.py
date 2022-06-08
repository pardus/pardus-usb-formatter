#!/usr/bin/python3

import sys, os
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gio, Gtk

from MainWindow import MainWindow

class Application(Gtk.Application):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id="tr.org.pardus.usb-formatter", flags=Gio.ApplicationFlags.HANDLES_OPEN, **kwargs)
        self.window = None
    
    def do_activate(self):
        self.window = MainWindow(self)
    
    def do_open(self, files, filecount, hint):
        if filecount == 1:
            file = files[0]
            if "/dev" in file.get_path():
                self.window = MainWindow(self, file.get_path())
            else:
                print("Only /dev/ files")
        else:
            print("Only one file.")



if __name__ == "__main__":
    app = Application()
    app.run(sys.argv)
