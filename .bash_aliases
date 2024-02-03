alias sudo='sudo '

# package management
alias up='sudo pacman -Syu && yay -Syu'
alias search='sudo pacman --search'
alias clean='sudo pacman --clean'
alias remove='sudo pacman -R'
alias install='sudo pacman -S'
alias i='install'

# bash management
alias refresh='exec bash'
alias r='refresh'
alias aliases='$EDITOR $HOME/.bash_aliases'
alias a='aliases'
alias bashrc='$EDITOR $HOME/.bashrc'
alias rc='bashrc'
alias bash_profile='$EDITOR $HOME/.bash_profile'
alias prof='bash_profile'

# i3 management
alias config='$EDITOR $HOME/.config/i3/config'
alias startup='$EDITOR $HOME/.scripts/startup.sh'

# computer management
alias keys='xev | grep -A2 --line-buffered "^KeyRelease" | sed -n "/keycode /s/^.*keycode \([0-9]*\).* (.*, \(.*\)).*$/\1 \2/p"'
alias logs='$EDITOR /var/log/syslog'
alias klogs="dmesg | grep -i"
alias v='uname -a && lsb_release -a'

# setup
alias as='cd $HOME/arch-setup'
alias das='cd $HOME/dev/arch-setup'
alias setup='nvim $HOME/arch-setup/setup.sh'

# help
alias h='function hdi(){ howdoi $* -c -n 5; }; hdi'

# list
alias l='ls -alh'

# git
alias g='git'
alias gitconfig='$EDITOR ~/.gitconfig'
alias gitaliases='gitconfig'
alias ga='gitaliases'

# sync-documents
export DRIVE_PATH=$HOME/gdrive
export SYNC_DOCUMENTS=$DRIVE_PATH/sync-documents
export SYNC_DATA=$DRIVE_PATH/sync-data
export TEXTBOOK_LIBRARY=$SYNC_DATA/library
init_drive() {
	if [[ ! -d $DRIVE_PATH ]]
	then
		mkdir -p $DRIVE_PATH && \
		cd $DRIVE_PATH && \
		drive init
	fi
	cd $DRIVE_PATH
}
sync-documents() {
	init_drive
	if [[ ! -d $SYNC_DOCUMENTS ]]
	then
		drive pull sync-documents
	fi
	cd $SYNC_DOCUMENTS
}
sync-data() {
	init_drive
        if [[ ! -d $SYNC_DATA ]]
        then
                drive pull sync-data
        fi
        cd $SYNC_DATA
}
library() {
	init_drive
        if [[ ! -d $TEXTBOOK_LIBRARY ]]
        then
                drive pull sync-data/library
        fi
        cd $TEXTBOOK_LIBRARY
}

alias sync='drive pull -no-clobber && drive push'
alias sd='sync-documents'
alias sdata='sync-data'

# obsidian
export OBSIDIAN_HOME=$HOME/Documents
export MATH_WIKI_NAME='math-wiki'
export MATH_WIKI_PATH=$OBSIDIAN_HOME/$MATH_WIKI_NAME
math_wiki() {
        if [[ ! -d $MATH_WIKI_PATH  ]]
        then
                mkdir -p $OBSIDIAN_HOME && \
                cd $OBSIDIAN_HOME && \
                git clone git@github.com:abhmul/$MATH_WIKI_NAME.git
        fi
        cd $MATH_WIKI_PATH
}
alias math='math_wiki'

export TRIVIA_VAULT_NAME='trivia-vault'
export TRIVIA_VAULT_PATH=$OBSIDIAN_HOME/$TRIVIA_VAULT_NAME
trivia_vault() {
        if [[ ! -d $TRIVIA_VAULT_PATH  ]]
        then
                mkdir -p $OBSIDIAN_HOME && \
                cd $OBSIDIAN_HOME && \
                git clone git@github.com:abhmul/$TRIVIA_VAULT_NAME.git
        fi
        cd $TRIVIA_VAULT_PATH
}
alias trivia='trivia_vault'

export THERAPY_VAULT_NAME='therapy-vault'
export THERAPY_VAULT_PATH=$OBSIDIAN_HOME/$THERAPY_VAULT_NAME
therapy_vault() {
        if [[ ! -d $THERAPY_VAULT_PATH  ]]
        then
                mkdir -p $OBSIDIAN_HOME && \
                cd $OBSIDIAN_HOME && \
                git clone git@github.com:abhmul/$THERAPY_VAULT_NAME.git
        fi
        cd $THERAPY_VAULT_PATH
}
alias therapy='therapy_vault'

export MANAGEMENT_VAULT_NAME='management-vault'
export MANAGEMENT_VAULT_PATH=$OBSIDIAN_HOME/$MANAGEMENT_VAULT_NAME
management_vault() {
        if [[ ! -d $MANAGEMENT_VAULT_PATH  ]]
        then
                mkdir -p $OBSIDIAN_HOME && \
                cd $OBSIDIAN_HOME && \
                git clone git@github.com:abhmul/$MANAGEMENT_VAULT_NAME.git
        fi
        cd $MANAGEMENT_VAULT_PATH
}
alias manage='management_vault'



# docker
alias dkps='docker ps --format "ID: {{.ID}} ~ Nm: {{.Names}} ~ Sts: {{.Status}} ~ Img: {{.Image}}"'
alias docker-smi='sudo docker run --gpus all --rm nvidia/cuda nvidia-smi'
alias tensorflow='sudo docker run --gpus all -v $HOME:$HOME -u $(id -u):$(id -g) -it tensorflow/tensorflow:latest-gpu-jupyter bash'

# projects
export PROJECTS_NAME='projects-repo'
export DEV=$HOME/dev
export PROJECTS=$DEV/$PROJECTS_NAME
projects() {
        if [[ ! -d $PROJECTS ]]
        then
                mkdir -p $DEV && \
                cd $DEV && \
                git clone https://github.com/abhmul/$PROJECTS_NAME.git
                conda env create -f pyprojects/environment.yml
        fi
        cd $PROJECTS
        prepare
}
alias p='projects'
prepare() {
        git pull
        conda activate pyprojects
}

# scratch
alias test='mkdir -p $HOME/test && cd $HOME/test'
alias t='test'
dkinit() {
	test
	if [[ ! -f ./Dockerfile ]]
	then
                echo "FROM alpine:latest" > Dockerfile
	fi
}
dktest-edit() {
	dkinit && \
	vim Dockerfile
}
dkbuild() {
	dkinit && \
	sudo docker build . -t test:latest
}
dktest() {
	dkbuild && \
	sudo docker run -it test:latest /bin/sh
}

