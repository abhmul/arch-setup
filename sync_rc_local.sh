#!/bin/sh

sudo cp /etc/rc.local /etc/rc.local.bak
sudo cp rc.local /etc/rc.local
sudo chmod +x /etc/rc.local

sudo cp /etc/systemd/system/rc-local.service /etc/systemd/system/rc-local.service.bak
sudo cp rc-local.service /etc/systemd/system/rc-local.service
sudo systemctl enable rc-local.service