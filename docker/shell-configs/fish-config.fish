# ~/.config/fish/config.fish

if status is-interactive
    # ---------- Environment ----------
    set -gx EDITOR vim
    set -gx PAGER less
    set -gx LESS '-R -i -M -w -z-4'
    set -gx CLICOLOR 1

    # ---------- Greeting ----------
    set -g fish_greeting ""

    # ---------- Aliases ----------
    alias ll 'ls -alhF --color=auto'
    alias la 'ls -A --color=auto'
    alias l  'ls -CF --color=auto'
    alias grep 'grep --color=auto'

    # Navigation
    alias ..  'cd ..'
    alias ... 'cd ../..'
    alias .... 'cd ../../..'

    # Git
    alias gs 'git status -sb'
    alias gd 'git diff'
    alias gdc 'git diff --cached'
    alias gco 'git checkout'
    alias gcm 'git commit -m'
    alias gp 'git push'
    alias gl 'git pull'
    alias glog 'git log --oneline --graph --decorate --all'
    alias gb 'git branch'
    alias ga 'git add'

    # Docker
    alias dc 'docker compose'

    # ---------- fzf.fish key-bindings auto-register from the plugin ----------

    # ---------- Prompt ----------
    if type -q starship
        starship init fish | source
    end

    # ---------- Local overrides ----------
    if test -f ~/.config/fish/config.local.fish
        source ~/.config/fish/config.local.fish
    end
end
