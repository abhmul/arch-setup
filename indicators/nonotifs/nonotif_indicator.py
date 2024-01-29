#!/usr/bin/python3
import os
import signal
import gi
import subprocess
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3

currpath = os.path.dirname(os.path.realpath(__file__))
proc = "nonotifs.sh"
"""
def run(path):
    try: 
        pid = subprocess.check_output(["pgrep", "-f", proc]).decode("utf-8").strip()
    except subprocess.CalledProcessError:
        subprocess.Popen(path+"/"+proc)

def show():
    try:
        pid = subprocess.check_output(["pgrep", "-f", proc]).decode("utf-8").strip()
        subprocess.Popen(["pkill", "-P", pid])
    except subprocess.CalledProcessError:
        pass
"""

def silent():
    try:
        subprocess.check_call(["notify-send", "DUNST_COMMAND_PAUSE"])
        return True
    except subprocess.CalledProcessError:
        return False


def show():
    try:
        subprocess.check_call(["notify-send", "DUNST_COMMAND_RESUME"])
        return True
    except subprocess.CalledProcessError:
        return False


class Indicator():
    def __init__(self):
        self.app = 'nonotif'
        iconpath = currpath+"/grey.png"
        self.testindicator = AppIndicator3.Indicator.new(
            self.app, iconpath,
            AppIndicator3.IndicatorCategory.OTHER)
        self.testindicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)       
        self.testindicator.set_menu(self.create_menu())

        # Default to showing notifications
        self.show(None)

    def create_menu(self):
        menu = Gtk.Menu()
        item_quit = Gtk.MenuItem('Quit')
        item_quit.connect('activate', self.stop)
        item_silent = Gtk.MenuItem("Don't disturb")
        item_silent.connect('activate', self.silent)
        item_show = Gtk.MenuItem("Show notifications")
        item_show.connect('activate', self.show)
        menu.append(item_quit)
        menu.append(item_silent)
        menu.append(item_show)
        menu.show_all()
        return menu

    def stop(self, source):
        Gtk.main_quit()

    def silent(self, source):
        if silent():
            self.testindicator.set_icon(currpath+"/red.png")


    def show(self, source):
        if show():
            self.testindicator.set_icon(currpath+"/green.png")

Indicator()
signal.signal(signal.SIGINT, signal.SIG_DFL)
Gtk.main()
