" ~/.config/nvim/init.vim -- Default Neovim entrypoint sharing ~/.vimrc
set runtimepath^=~/.vim runtimepath+=~/.vim/after
let &packpath = &runtimepath

if filereadable(expand('~/.vimrc'))
  execute 'source ' . fnameescape(expand('~/.vimrc'))
endif
