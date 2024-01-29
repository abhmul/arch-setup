#!/bin/bash
dbus-monitor "interface='org.freedesktop.Notifications'" | xargs -I '{}' pkill notify-osd
