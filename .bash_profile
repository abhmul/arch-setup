# Append to path
export LOCALPATH=$HOME/.local
export GOPATH=$HOME/go
export PATH=$LOCALPATH/bin:$GOPATH/bin:$PATH

export EDITOR=nvim

# Start X11
if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
	exec startx
fi


source "$HOME/.cargo/env"

# Login shells also need the interactive shell setup.
if [[ $- == *i* ]]; then
	source "$HOME/.bashrc"
fi
