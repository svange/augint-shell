# ~/.config/fish/config.fish

if status is-interactive
    # ---------- Environment ----------
    set -gx EDITOR vim
    set -gx PAGER less
    set -gx LESS '-R -i -M -w -z-4'
    set -gx CLICOLOR 1

    # ---------- Greeting ----------
    set -g fish_greeting ""

    # ---------- History ----------
    set -g fish_history default
    set -g fish_history_max 100000

    # ---------- Abbreviations ----------
    # Fish handles --color=auto natively via built-in wrapper functions.
    # Abbreviations expand in-place, giving readable history and real commands.

    # Listing
    abbr -a ll 'ls -alhF'
    abbr -a la 'ls -A'
    abbr -a l  'ls -CF'

    # Navigation
    abbr -a .. 'cd ..'
    abbr -a ... 'cd ../..'
    abbr -a .... 'cd ../../..'

    # Git
    abbr -a gs 'git status -sb'
    abbr -a gd 'git diff'
    abbr -a gdc 'git diff --cached'
    abbr -a gco 'git checkout'
    abbr -a gcm 'git commit -m'
    abbr -a gp 'git push'
    abbr -a gl 'git pull'
    abbr -a glog 'git log --oneline --graph --decorate --all'
    abbr -a gb 'git branch'
    abbr -a ga 'git add'

    # Docker
    abbr -a dc 'docker compose'

    # ---------- Prompt ----------
    if type -q starship
        starship init fish | source
    end

    # ---------- Local overrides ----------
    if test -f ~/.config/fish/config.local.fish
        source ~/.config/fish/config.local.fish
    end
end
