# Append to path
export LOCALPATH=$HOME/.local
export PATH=$LOCALPATH/bin:$PATH

export EDITOR=nvim

if [ -f $HOME/.bashrc ]; then
        source $HOME/.bashrc
fi

# Start X11
if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
	exec startx
fi


