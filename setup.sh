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
sudo pacman -S --needed neovim ranger scrot xclip firefox sysstat htop cameractrls otf-font-awesome

# Setup software
sudo pacman -S --needed obsidian
yay -Sa --needed zoom visual-studio-code-bin howdoi

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
# TODO: Why is this error occuring? Do I need to change my dockerfile or add some more installation scripts?
# DEPRECATED: The legacy builder is deprecated and will be removed in a future release.
#             Install the buildx component to build images with BuildKit:
#             https://docs.docker.com/go/buildx/
# 
# Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?


# Setup workstation 
sudo pacman -S --needed rclone
echo -e "\nSetup the rclone config, then run \`sd\` and \`library\` to get Google Drive files"
cd $HOME && mkdir -p dev
cd $HOME && mkdir -p .local/bin

# Install miniconda
cd $HOME
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh
rm Miniforge3-$(uname)-$(uname -m).sh

# Setup mamba
echo -e "\nTo finish setting up mamba, run \`mamba env create -f environment.yml\` to create the arch python environment"

# Run alias commands that do some setup


