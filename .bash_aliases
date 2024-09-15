alias sudo='sudo '

# package management
alias up='sudo pacman -Syu && mamba activate arch && yay -Syu && mamba deactivate'
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
alias clear-data='history -wc && cat /dev/null > ~/.bash_history && ~/arch-setup/.scripts/clear-clipboard.sh'
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

# Util tools
alias djvu2pdf="~/arch-setup/.scripts/djvu2pdf.sh"
encrypt-drive() {
	mamba activate arch
	python ~/arch-setup/.scripts/encrypt-drive.py "$@"
	mamba deactivate
}

# sync-documents
export DRIVE_PATH=$HOME/gdrive
export SYNC_DOCUMENTS=sync-documents
export SYNC_DOCUMENTS_PATH=$DRIVE_PATH/$SYNC_DOCUMENTS
export SYNC_DATA=sync-data
export SYNC_DATA_PATH=$DRIVE_PATH/$SYNC_DATA
export TEXTBOOK_LIBRARY=$SYNC_DATA/library
export TEXTBOOK_LIBRARY_PATH=$DRIVE_PATH/$TEXTBOOK_LIBRARY
alias rsync="rclone sync -i --create-empty-src-dirs"
sync-documents() {
	if [[ ! -d $SYNC_DOCUMENTS_PATH ]]
	then
		rsync drive:$SYNC_DOCUMENTS $SYNC_DOCUMENTS_PATH
	fi
	cd $SYNC_DOCUMENTS_PATH
}
sync-data() {
        if [[ ! -d $SYNC_DATA_PATH ]]
        then
                mkdir -p $SYNC_DATA_PATH
		echo -e "To pull different sync-data modules, run \`dpull sync-data/\[MODULE\]\'"
        fi
        cd $SYNC_DATA_PATH
}
library() {
        if [[ ! -d $TEXTBOOK_LIBRARY_PATH ]]
        then
                rsync drive:$TEXTBOOK_LIBRARY $TEXTBOOK_LIBRARY_PATH
        fi
        cd $TEXTBOOK_LIBRARY_PATH
}

trim_trailing_helper() { 
	echo -e $(echo -e "$@" | sed "s:/*$::") 
}

drive_command_helper() {
	if [[ $# -eq 0 ]]; then
		path=$(pwd)
		tail_path="$(trim_trailing_helper ${path#$DRIVE_PATH/})"
		head_path="$(trim_trailing_helper ${path%$tail_path})"
		if [[ $head_path != $DRIVE_PATH ]]; then
			echo -e "Must run from inside $DRIVE_PATH! Currently at $path."
			return 1
		fi

		if [[ $path = $DRIVE_PATH ]]; then
			echo -e "Must run from a subfolder of $DRIVE_PATH, not from $DRIVE_PATH."
			return 1
		fi

	else
		tail_path=$1
		head_path=$DRIVE_PATH
	fi

	echo -e $head_path
	echo -e $tail_path
	return 0
}
dpull() { 
	PATH_PARSE=$(drive_command_helper $@) RCODE=$?
	if [[ $RCODE -ne 0 ]]; then
		echo $PATH_PARSE
		return $RCODE
	fi
	{ read head_path; read tail_path;} <<<"$PATH_PARSE"
	rsync --exclude-from={'.driveignore'} drive:$tail_path $head_path/$tail_path
}
dpush() { 
	PATH_PARSE=$(drive_command_helper $@) RCODE=$?
	if [[ $RCODE -ne 0 ]]; then
		echo $PATH_PARSE
		return $RCODE
	fi
	{ read head_path; read tail_path;} <<<"$PATH_PARSE"
	rsync --exclude-from={'.driveignore'} $head_path/$tail_path drive:$tail_path
}
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

