#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias grep='grep --color=auto'
PS1='[\u@\h \W]\$ '

source $HOME/.bashrc.extra




# >>> Codex installer >>>
export PATH="/home/abhmul/.local/bin:$PATH"
# <<< Codex installer <<<
