#!/bin/bash

SETUP_PATH=$(pwd)
echo "Path to current directory $SETUP_PATH"
if [[ $SETUP_PATH != *arch-setup ]]; then
	echo "Must run from root of arch-setup!"
	exit 1
fi

# Setup and upgrade
sudo pacman -Syu
sudo pacman -S --needed git lsb-release
# TODO Add 
# - yay
# - i3, i3blocks
# - network-manager
# - blueman

# Install python setup-tools
sudo pacman -S --needed python-setuptools

# Install screen layout manager
sudo pacman -S --needed arandr

# Install applets
yay -Sa --needed indicator-sound-switcher

# Install tools
sudo pacman -S --needed neovim ranger scrot xclip firefox

# Setup software
sudo pacman -S --needed code obsidian
yay -Sa --needed zoom
yay -Sa --needed howdoi

# Setup background
sudo pacman -S --needed feh


# Set up symbolic link
echo -e "Setting up symbolic links"

cd $HOME && {
	rm -fv .gitconfig
	ln -s $SETUP_PATH/.gitconfig .gitconfig
}
mkdir -p $HOME/.config
cd $HOME/.config && {
	rm -rfv i3
	ln -s $SETUP_PATH/.config/i3 i3
}
# TODO - i3blocks setup
cd $HOME && {
	rm -rfv .scripts
	ln -s $SETUP_PATH/.scripts .scripts
}
cd $HOME && {
	rm -rfv indicators
	ln -s $SETUP_PATH/indicators indicators
}
mkdir -p $HOME/Pictures
cd $HOME/Pictures && {
	rm -fv normandy-sr2.jpg
	ln -s $SETUP_PATH/Pictures/normandy-sr2.jpg normandy-sr2.jpg
}
cd $HOME && {
	rm -fv .bashrc.extra
	ln -s $SETUP_PATH/.bashrc.extra .bashrc.extra
	
	if grep -R -q "source \$HOME/.bashrc.extra" .bashrc
	then
		:
	else
		echo -e "\nsource \$HOME/.bashrc.extra" >> .bashrc
	fi

	rm -fv .bash_aliases
	ln -s $SETUP_PATH/.bash_aliases .bash_aliases
	rm -fv .bash_profile
	ln -s $SETUP_PATH/.bash_profile .bash_profile
	echo -e "\nCurrent state of bash settings"
	ls -alh | grep .bash
	echo -e "\nUsing new bashrc"
	source ~/.bashrc
}


# Install Docker
echo -e "\nInstalling docker"
sudo pacman -S --needed docker
echo -e "Test installation with dktest when the script is complete."

# Setup workstation TODO install drive
# cd $HOME && {
# 	mkdir -p dev
# 	mkdir -p gdrive && \
# 	cd gdrive && \
# 	drive init && \
# 	drive pull sync-documents && \
# 	drive pull sync-data/library
# }
cd $HOME && mkdir -p .local/bin

# Install miniconda
# TODO wget to /tmp https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
# Run the miniconda installation

# Run alias commands that do some setup


