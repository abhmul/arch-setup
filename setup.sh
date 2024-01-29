#!/bin/bash

SETUP_PATH=$(pwd)
echo "Path to current directory $SETUP_PATH"
if [[ $SETUP_PATH != *arch-setup ]]; then
	echo "Must run from root of arch-setup!"
	exit 1
fi

# Setup and upgrade
sudo pacman -SyU
# TODO Add 
# - yay
# - i3
# - network-manager
# - blueman
#
# TODO - should I replace pacman calls with yay?

# Install python setup-tools
sudo pacman -S python-setuptools

# Install screen layout manager
sudo pacman -S arandr

# Install applets
sudo pacman -S indicator-sound-switcher

# Install tools
sudo pacman -S --needed nvim
sudo pacman -S --needed ranger
sudo pacman -S --needed scrot
sudo pacman -S --needed xclip

# Setup software
# TODO - continue updating from here
snap install vscode --classic
snap install emacs --classic
snap install obsidian
snap install zoom-client

# Setup background
sudo apt -y install feh


# Set up symbolic link
echo "Setting up symbolic links"

mkdir $HOME/.config
cd $HOME/.config && {
	rm -rf i3
	ln -s $SETUP_PATH/.config/i3 i3
	rm -rf i3status
	ln -s $SETUP_PATH/.config/i3status i3status
}
cd $HOME && {
	rm -rf .scripts
	ln -s $SETUP_PATH/.scripts .scripts
}
cd $HOME && {
	rm -rf indicators
	ln -s $SETUP_PATH/indicators indicators
}
mkdir $HOME/Pictures
cd $HOME/Pictures && {
	rm normandy-destruction.jpg
	ln -s $SETUP_PATH/Pictures/normandy-destruction.jpg normandy-destruction.jpg
}
cd $HOME && {
	rm .bashrc.extra
	ln -s $SETUP_PATH/.bashrc.extra .bashrc.extra
	echo "\n. $HOME/.bashrc.extra" >> .bashrc 
	rm .bash_aliases
	ln -s $SETUP_PATH/.bash_aliases .bash_aliases
	rm .bash_profile
	ln -s $SETUP_PATH/.bash_profile .bash_profile
	echo "\n\nCurrent state of bash settings"
	l -alh | grep .bash
	echo "\nUsing new bashrc"
	source ~/.bashrc
}


# Install Docker
echo "\n\nInstall docker at https://docs.docker.com/engine/install/ubuntu/#installation-methods"
echo "Test installation with dktest"

# Setup workstation
cd $HOME && {
	mkdir dev
	mkdir sync-documents
}

# Run alias commands that do some setup
up
p
o

