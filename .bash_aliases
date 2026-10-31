alias sudo='sudo '

# package management
alias up='sudo pacman -Syu && rustup update && yay -Syu'
alias search='sudo pacman -Q | grep'
alias clean='sudo pacman --clean'
alias remove='sudo pacman -R'
alias remove-orphans='mamba activate arch && yay -Qdtq | yay -Rns - && mamba deactivate'
alias clear-swap='sudo systemctl restart dev-zram0.swap'

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
# This fixes annotation issue in zoom
alias zfix="xcompmgr -c -l0 -t0 -r0 -o.00"
term-here() {
	command kitty --directory "$PWD" >/dev/null 2>&1 & disown
}
alias th='term-here'
alias dup='term-here'
alias djvu2pdf="~/arch-setup/.scripts/djvu2pdf.sh"
alias mcp="~/mcp-config/start_mcp_servers.sh"
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
	rsync --exclude-from=$head_path/.driveignore drive:$tail_path $head_path/$tail_path
}
dpush() { 
	PATH_PARSE=$(drive_command_helper $@) RCODE=$?
	if [[ $RCODE -ne 0 ]]; then
		echo $PATH_PARSE
		return $RCODE
	fi
	{ read head_path; read tail_path;} <<<"$PATH_PARSE"
	rsync -v --exclude-from=$head_path/.driveignore $head_path/$tail_path drive:$tail_path
}
alias sd='sync-documents'
alias sdata='sync-data'

# obsidian
export OBSIDIAN_HOME=$HOME/Documents/vaults
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

export AGENT_VAULT_NAME='agent-vault'
export AGENT_VAULT_PATH=$OBSIDIAN_HOME/$AGENT_VAULT_NAME
agent_vault() {
if [[ ! -d $AGENT_VAULT_PATH  ]]
then
	mkdir -p $OBSIDIAN_HOME && \
	cd $OBSIDIAN_HOME && \
	git clone git@github.com:abhmul/$AGENT_VAULT_NAME.git
fi
cd $AGENT_VAULT_PATH
}
alias agent='agent_vault'

export RESEARCH_VAULT_NAME='research-vault'
export RESEARCH_VAULT_PATH=$OBSIDIAN_HOME/$RESEARCH_VAULT_NAME
research_vault() {
if [[ ! -d $RESEARCH_VAULT_PATH  ]]
then
	mkdir -p $OBSIDIAN_HOME && \
	cd $OBSIDIAN_HOME && \
	git clone git@github.com:abhmul/$RESEARCH_VAULT_NAME.git
fi
cd $RESEARCH_VAULT_PATH
}
alias research='research_vault'


alias agent-python='source $HOME/.local/share/agent-python/.venv/bin/activate'
# Route python and venv console scripts inside claude's process tree
# to ~/.local/share/agent-python/.venv. Workaround for claude-code
# issue #15897 (updatedInput hooks clobbered in multi-hook configs).
# Only affects the claude subprocess; this shell's PATH is untouched.
# Set temporary-directory defaults for Claude and its child processes.
claude() {
	local -a agent_tracker=()
	if [[ -x "$HOME/.local/bin/i3-session" ]]; then
		agent_tracker=("$HOME/.local/bin/i3-session" agent-launch --launcher claude --)
	fi
	command env -u PYTHONHOME \
		TMPDIR="$HOME/tmp" \
		TMP="$HOME/tmp" \
		TEMP="$HOME/tmp" \
		CLAUDE_CODE_TMPDIR="$HOME/tmp/claude" \
		VIRTUAL_ENV="$HOME/.local/share/agent-python/.venv" \
		PATH="$HOME/.local/share/agent-python/.venv/bin:$PATH" \
		"${agent_tracker[@]}" claude "$@"
}
# Effort is not forced here (was --effort max until 2026-09-18): the settings
# files decide (user modelSettings / project .claude/settings.json), so /effort
# and per-project defaults take effect. Pass --effort <level> by hand to override.

# Both accounts use the same launch options, temporary directory, and Python environment.
# ~/.codex-academic shares configuration and memory with ~/.codex.
_codex_account() {
	local codex_account_home="$1"
	local codex_account_binary="$2"
	shift 2
	local agent_launcher=codex
	[[ "$codex_account_home" != "$HOME/.codex-academic" ]] || agent_launcher=codex-academic
	local -a agent_tracker=()
	if [[ -x "$HOME/.local/bin/i3-session" ]]; then
		agent_tracker=("$HOME/.local/bin/i3-session" agent-launch --launcher "$agent_launcher" --)
	fi
	local -a codex_profile_args=(-p auto)
	local -a codex_remote_args=(--remote unix://)
	local -a codex_positionals=()
	local codex_remote=unix:// codex_use_daemon=true codex_value_flag= codex_arg
	# Inspect options without changing argv; option values and text after --
	# must not be mistaken for commands or connection flags.
	for codex_arg in "$@"; do
		if [[ -n "$codex_value_flag" ]]; then
			[[ "$codex_value_flag" != --remote ]] || codex_remote="$codex_arg"
			codex_value_flag=
			continue
		fi
		case "$codex_arg" in
			--) break ;;
			-h|--help|-V|--version|--no-daemon) codex_use_daemon=false ;;
			--remote)
				codex_remote_args=()
				codex_remote=
				codex_value_flag=--remote
				;;
			--remote=*) codex_remote_args=(); codex_remote="${codex_arg#*=}" ;;
			-p|--profile) codex_profile_args=(); codex_value_flag="$codex_arg" ;;
			-p?*|--profile=*) codex_profile_args=() ;;
			-c|--config|-m|--model|-s|--sandbox|-a|--ask-for-approval|-C|--cd|--add-dir|-i|--image|--enable|--disable|--local-provider|--remote-auth-token-env)
				codex_value_flag="$codex_arg"
				;;
			-*) ;;
			*) codex_positionals+=("$codex_arg") ;;
		esac
	done
	case "${codex_positionals[0]-}" in
		login|logout|doctor|app-server|agents|queue|archive|delete|unarchive|remote-control|completion|update|migrate-rollouts|migrate-nfs-db|plugin|mcp|mcp-server|exec-server|features|apply|a|cloud|help|sandbox)
			# Leave management commands on their native connection behavior.
			codex_profile_args=()
			codex_use_daemon=false
			;;
		resume)
			# Remote resume restores saved permissions and rejects profile overrides.
			[[ "$codex_use_daemon" != true ]] || codex_profile_args=()
			;;
		exec|e|review) codex_use_daemon=false ;;
		debug)
			[[ "${codex_positionals[1]-}" == prompt-input ]] || codex_profile_args=()
			codex_use_daemon=false
			;;
	esac
	local -a codex_env=(env -u PYTHONHOME
		"CODEX_HOME=$codex_account_home"
		"TMPDIR=$HOME/tmp" "TMP=$HOME/tmp" "TEMP=$HOME/tmp"
		"VIRTUAL_ENV=$HOME/.local/share/agent-python/.venv"
		"PATH=$HOME/.local/share/agent-python/.venv/bin:$PATH")
	if [[ "$codex_use_daemon" == true ]]; then
		if [[ "$codex_remote" == unix:// ]]; then
			# Native start checks for an existing daemon and starts only if needed.
			# Use this account's environment, without terminal tracking or a profile.
			command "${codex_env[@]}" "$codex_account_binary" -c 'cli_auth_credentials_store="file"' app-server daemon start >/dev/null || return
		fi
	else
		codex_remote_args=()
	fi
	command "${codex_env[@]}" "${agent_tracker[@]}" "$codex_account_binary" \
		"${codex_profile_args[@]}" "${codex_remote_args[@]}" -c 'cli_auth_credentials_store="file"' "$@"
}

codex() {
	_codex_account "$HOME/.codex" "$HOME/.local/bin/codex" "$@"
}

codex-academic() {
	_codex_account "$HOME/.codex-academic" "$HOME/.codex-academic/bin/codex" "$@"
}
# Initialize pi with default tools
pi() {
  local tools="read,grep,find,ls,edit,write,bash,bg_run,bg_status,bg_logs,bg_kill"

  for arg in "$@"; do
    case "$arg" in
      --tools|-t|--no-tools|-nt|--no-builtin-tools|-nbt)
        command pi "$@"
        return
        ;;
    esac
  done

  command pi --tools "$tools" "$@"
}



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
