# package management
alias up='sudo apt update && sudo apt upgrade && sudo snap refresh'
alias search='sudo apt-cache search'
alias autoremove='sudo apt autoremove'
alias remove='sudo apt remove'
alias install='sudo apt install'
alias i='install'
alias snapstall='sudo snap install'
alias si='snapstall'

# bash management
alias refresh='exec bash'
alias r='refresh'
alias aliases='vim ~/.bash_aliases'
alias a='aliases'
alias bashrc='vim ~/.bashrc'
alias rc='bashrc'
alias bash_profile='vim ~/.bash_profile'
alias prof='bash_profile'

# i3 management
alias config='vim ~/.config/i3/config'
alias startup='vim ~/.scripts/startup.sh'

# computer management
alias keys='xev | grep -A2 --line-buffered "^KeyRelease" | sed -n "/keycode /s/^.*keycode \([0-9]*\).* (.*, \(.*\)).*$/\1 \2/p"'
alias logs='gedit /var/log/syslog'
alias v='uname -a && lsb_release -a'

# help
alias h='function hdi(){ howdoi $* -c -n 5; }; hdi'

# git
alias g='git'
alias gitconfig='vim ~/.gitconfig'
alias gitaliases='gitconfig'
alias ga='gitaliases'

# obsidian
alias o='cd ~/Documents/obsidian/vault'
alias osync='o && g up'


# docker
alias dkps='docker ps --format "ID: {{.ID}} ~ Nm: {{.Names}} ~ Sts: {{.Status}} ~ Img: {{.Image}}"'
alias docker-smi='docker run --gpus all --rm nvidia/cuda nvidia-smi'
alias tensorflow='docker run --gpus all -v $HOME:$HOME -u $(id -u):$(id -g) -it tensorflow/tensorflow:latest-gpu-py3-jupyter bash'

# projects
export PROJECTS_NAME='projects-repo'
export DEV=$HOME/dev
export PROJECTS=$DEV/$PROJECTS_NAME
projects() {
	if [[ ! -d $DEV/$PROJECTS_NAME ]]
	then
		mkdir -p $DEV && \
		cd $DEV && \
		git clone https://github.com/abhmul/$PROJECTS_NAME.git
	fi
	cd $PROJECTS
	prepare
}
alias p='projects'
prepare() {
	cp $HOME/.bash_aliases $PROJECTS && \
	cp $HOME/.gitconfig $PROJECTS
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
	docker build . -t test:latest
}
dktest() {
	dkbuild && \
	docker run -it test:latest /bin/bash
}
