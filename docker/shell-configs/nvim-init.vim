" ~/.config/nvim/init.vim -- Classic Vim core (~/.vimrc) + Modern Neovim IDE layer
" Preserves 100% of classic Vim keybindings while adding:
"   - Built-in floating Cheat Sheet (<Space>? or :Cheat)
"   - Live popup keymap guide on <Space> (which-key.nvim)
"   - File Explorer tree sidebar (<Space>e / <Space>o via nvim-tree.lua)
"   - Project-wide Fuzzy File & Ripgrep Search (<Space>ff, <Space>/, <Space>fb via telescope.nvim)
"   - Git gutter diff signs & hunk actions (]c, [c, <Space>hp, <Space>hb via gitsigns.nvim)
"   - On-demand LSP code navigation (gd, gr, K, <Space>rn, <Space>ca, :Mason)
"   - AI coding agents (<Space>a* via coder/claudecode.nvim & nickjvandyke/opencode.nvim)

set runtimepath^=~/.vim runtimepath+=~/.vim/after
let &packpath = &runtimepath

if filereadable(expand('~/.vimrc'))
  execute 'source ' . fnameescape(expand('~/.vimrc'))
endif

if has('nvim-0.9')
lua << EOF
-- ---------------------------------------------------------------------------
-- 1. Built-in Interactive Cheat Sheet (:Cheat or <Space>?)
--    Works immediately, even offline or before plugins install.
-- ---------------------------------------------------------------------------
local cheat_lines = {
  "============================================================================",
  "  NEOVIM FOR VIM VETERANS -- QUICK CHEAT SHEET  (press q or <Esc> to close)",
  "============================================================================",
  "  TIP: Press <Space> and wait 300ms at any time for a live popup menu!",
  "",
  "  FILE EXPLORER SIDEBAR (nvim-tree)",
  "    <Space>e        Toggle file tree sidebar on/off",
  "    <Space>o        Reveal & focus the current file in the sidebar",
  "    Inside tree:    <CR> open | s vsplit | i hsplit | a create file/dir",
  "                    r rename  | d delete | y copy name | H toggle dotfiles",
  "                    ? toggle full tree keybindings help",
  "",
  "  FUZZY FIND & PROJECT SEARCH (telescope + ripgrep + fd)",
  "    <Space><Space>  Fuzzy find files in project (also <Space>ff)",
  "    <Space>/        Live grep text across all files in project (also <Space>fg)",
  "    <Space>fw       Search for the word under cursor across project",
  "    <Space>fb       Switch between open buffers",
  "    <Space>fr       Recently opened files",
  "    <Space>fk       Search all keymaps (interactive cheat sheet!)",
  "    <Space>fh       Search Neovim help tags",
  "    Inside picker:  <C-j>/<C-k> or Up/Down move | <CR> open | <C-v> vsplit",
  "                    <C-x> hsplit | <C-u>/<C-d> scroll preview | <Esc> close",
  "",
  "  BUFFERS, WINDOWS & SAVING",
  "    <Space>w / q    Save file (:w) / Quit (:q)",
  "    [b / ]b         Previous / Next open buffer",
  "    <Space>bb       Toggle last two buffers (same as <C-^>)",
  "    <Space>bd       Close current buffer (:bdelete)",
  "    <C-h/j/k/l>     Move between window splits",
  "    <Esc><Esc>      Clear search highlight",
  "",
  "  GIT INTEGRATION (gitsigns + telescope + lazygit)",
  "    ]c / [c         Jump to next / previous changed git hunk",
  "    <Space>hp       Preview git hunk diff inline",
  "    <Space>hr       Reset git hunk under cursor",
  "    <Space>hb       Show git blame for current line",
  "    <Space>gs       Fuzzy browse modified git files (git status)",
  "",
  "  CODE NAVIGATION & LSP (when a language server is installed via :Mason)",
  "    gd / gD         Go to definition / declaration",
  "    gr / gi         Find all references / Go to implementation",
  "    K               Hover documentation popup for symbol under cursor",
  "    <Space>rn       Rename symbol across project",
  "    <Space>ca       Code actions / quick fixes",
  "    <Space>d        Show line diagnostic/error in float ([d / ]d prev/next)",
  "    :Mason          Open GUI installer for LSP servers (pyright, ts_ls, etc.)",
  "    :Lazy           Open plugin manager status / updates",
  "",
  "  AI CODING AGENTS (claudecode.nvim & opencode.nvim)",
  "    <Space>ac / af  Toggle / Focus Claude Code (ar=resume, aC=continue)",
  "    <Space>ab / as  Add buffer / Send visual selection or tree file to Claude",
  "    <Space>aa / ad  Accept / Deny Claude diff  |  <Space>am = select model",
  "    <Space>ao / aO  Ask OpenCode / Select OpenCode action (<Space>at=toggle)",
  "    go / goo        Send motion range / current line to OpenCode",
  "============================================================================",
}

local function open_cheat_sheet()
  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, cheat_lines)
  vim.bo[buf].modifiable = false
  vim.bo[buf].buftype = "nofile"
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].filetype = "help"

  local width = math.min(78, vim.o.columns - 4)
  local height = math.min(#cheat_lines, vim.o.lines - 4)
  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    width = width,
    height = height,
    row = math.max(1, math.floor((vim.o.lines - height) / 2) - 1),
    col = math.max(1, math.floor((vim.o.columns - width) / 2)),
    style = "minimal",
    border = "rounded",
    title = " Neovim Cheat Sheet (<Space>?) ",
    title_pos = "center",
  })
  vim.wo[win].cursorline = true
  vim.keymap.set("n", "q", "<cmd>close<CR>", { buffer = buf, silent = true })
  vim.keymap.set("n", "<Esc>", "<cmd>close<CR>", { buffer = buf, silent = true })
end

vim.api.nvim_create_user_command("Cheat", open_cheat_sheet, { desc = "Open Neovim Cheat Sheet" })
vim.keymap.set("n", "<leader>?", open_cheat_sheet, { silent = true, desc = "Neovim Cheat Sheet" })

-- Diagnostics keymaps (always active)
vim.keymap.set("n", "<leader>d", vim.diagnostic.open_float, { silent = true, desc = "Show Line Diagnostics" })
vim.keymap.set("n", "[d", vim.diagnostic.goto_prev, { silent = true, desc = "Previous Diagnostic" })
vim.keymap.set("n", "]d", vim.diagnostic.goto_next, { silent = true, desc = "Next Diagnostic" })

-- LSP keymaps (automatically active whenever an LSP server attaches to a buffer)
vim.api.nvim_create_autocmd("LspAttach", {
  callback = function(ev)
    local opts = { buffer = ev.buf, silent = true }
    vim.keymap.set("n", "gd", vim.lsp.buf.definition, vim.tbl_extend("force", opts, { desc = "Go to Definition" }))
    vim.keymap.set("n", "gD", vim.lsp.buf.declaration, vim.tbl_extend("force", opts, { desc = "Go to Declaration" }))
    vim.keymap.set("n", "gr", vim.lsp.buf.references, vim.tbl_extend("force", opts, { desc = "Find References" }))
    vim.keymap.set("n", "gi", vim.lsp.buf.implementation, vim.tbl_extend("force", opts, { desc = "Go to Implementation" }))
    vim.keymap.set("n", "K", vim.lsp.buf.hover, vim.tbl_extend("force", opts, { desc = "Hover Documentation" }))
    vim.keymap.set("n", "<leader>rn", vim.lsp.buf.rename, vim.tbl_extend("force", opts, { desc = "Rename Symbol" }))
    vim.keymap.set({ "n", "v" }, "<leader>ca", vim.lsp.buf.code_action, vim.tbl_extend("force", opts, { desc = "Code Action" }))
    vim.keymap.set("n", "<leader>cf", function() vim.lsp.buf.format({ async = true }) end, vim.tbl_extend("force", opts, { desc = "Format Buffer" }))
  end,
})

-- ---------------------------------------------------------------------------
-- 2. Secret / Temp File Guard: skip third-party plugins when editing secrets
--    (e.g. `chezmoi edit`, `.env`, `.pem`, `.age`, `/tmp/*`)
-- ---------------------------------------------------------------------------
local function is_secret_invocation()
  for _, arg in ipairs(vim.fn.argv()) do
    local p = arg:gsub("\\", "/")
    if p:match("/tmp/") or p:match("/var/tmp/") or p:match("/dev/shm/")
      or p:match("Temp/") or p:match("chezmoi") or p:match("%.age$")
      or p:match("^%.env") or p:match("/%.env") or p:match("%.env$")
      or p:match("%.pem$") or p:match("%.key$") or p:match("%.asc$")
      or p:match("%-sa%.json$") then
      return true
    end
  end
  return false
end

if not is_secret_invocation() and vim.fn.executable("git") == 1 then
  -- Bootstrap lazy.nvim automatically on first launch
  local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
  if not (vim.uv or vim.loop).fs_stat(lazypath) then
    vim.fn.system({
      "git", "clone", "--filter=blob:none",
      "https://github.com/folke/lazy.nvim.git",
      "--branch=stable", lazypath,
    })
  end
  vim.opt.rtp:prepend(lazypath)

  local ok_lazy, lazy = pcall(require, "lazy")
  if ok_lazy then
    lazy.setup({
      -- 1. Live popup keymap cheat sheet when pressing <Space>
      {
        "folke/which-key.nvim",
        event = "VeryLazy",
        opts = {
          delay = 250,
          spec = {
            { "<leader>a", group = "AI (Claude Code & OpenCode)" },
            { "<leader>f", group = "Find / Search (Telescope)" },
            { "<leader>g", group = "Git" },
            { "<leader>h", group = "Git Hunks" },
            { "<leader>b", group = "Buffers" },
            { "<leader>c", group = "Code / LSP" },
          },
        },
      },

      -- 2. File Explorer sidebar with Nerd Font icons (<Space>e / <Space>o)
      {
        "nvim-tree/nvim-tree.lua",
        dependencies = { "nvim-tree/nvim-web-devicons" },
        keys = {
          { "<leader>e", "<cmd>NvimTreeToggle<CR>", desc = "Toggle File Explorer Sidebar" },
          { "<leader>o", "<cmd>NvimTreeFindFile<CR>", desc = "Reveal Current File in Explorer" },
        },
        init = function()
          vim.g.loaded_netrw = 1
          vim.g.loaded_netrwPlugin = 1
        end,
        opts = {
          view = { width = 32 },
          renderer = { group_empty = true, icons = { show = { git = true, folder = true, file = true } } },
          filters = { dotfiles = false },
          git = { ignore = false },
        },
      },

      -- 3. Fuzzy file finder & live ripgrep search across project (<Space><Space>, <Space>/)
      {
        "nvim-telescope/telescope.nvim",
        dependencies = { "nvim-lua/plenary.nvim" },
        cmd = "Telescope",
        keys = {
          { "<leader><leader>", "<cmd>Telescope find_files<CR>", desc = "Fuzzy Find Files" },
          { "<leader>ff", "<cmd>Telescope find_files<CR>", desc = "Fuzzy Find Files" },
          { "<leader>/", "<cmd>Telescope live_grep<CR>", desc = "Live Grep Text Across Project" },
          { "<leader>fg", "<cmd>Telescope live_grep<CR>", desc = "Live Grep Text Across Project" },
          { "<leader>fw", "<cmd>Telescope grep_string<CR>", desc = "Grep Word Under Cursor" },
          { "<leader>fb", "<cmd>Telescope buffers<CR>", desc = "Switch Open Buffers" },
          { "<leader>fr", "<cmd>Telescope oldfiles<CR>", desc = "Recent Files" },
          { "<leader>fk", "<cmd>Telescope keymaps<CR>", desc = "Search All Keymaps (Cheat Sheet)" },
          { "<leader>fh", "<cmd>Telescope help_tags<CR>", desc = "Search Help Tags" },
          { "<leader>gs", "<cmd>Telescope git_status<CR>", desc = "Git Status / Modified Files" },
          { "<leader>gc", "<cmd>Telescope git_commits<CR>", desc = "Git Commits" },
        },
        opts = {
          defaults = {
            sorting_strategy = "ascending",
            layout_config = { prompt_position = "top" },
          },
        },
      },

      -- 4. Git diff signs in gutter & hunk navigation (]c, [c, <Space>hp, <Space>hb)
      {
        "lewis6991/gitsigns.nvim",
        event = { "BufReadPre", "BufNewFile" },
        opts = {
          on_attach = function(bufnr)
            local gs = package.loaded.gitsigns
            local function map(mode, l, r, desc)
              vim.keymap.set(mode, l, r, { buffer = bufnr, silent = true, desc = desc })
            end
            map("n", "]c", function()
              if vim.wo.diff then return "]c" end
              vim.schedule(function() gs.next_hunk() end)
              return "<Ignore>"
            end, "Next Git Hunk")
            map("n", "[c", function()
              if vim.wo.diff then return "[c" end
              vim.schedule(function() gs.prev_hunk() end)
              return "<Ignore>"
            end, "Previous Git Hunk")
            map("n", "<leader>hp", gs.preview_hunk, "Preview Git Hunk")
            map("n", "<leader>hr", gs.reset_hunk, "Reset Git Hunk")
            map("n", "<leader>hb", function() gs.blame_line({ full = true }) end, "Git Blame Line")
          end,
        },
      },

      -- 5. On-demand LSP installer (:Mason) & language server support
      {
        "williamboman/mason-lspconfig.nvim",
        cmd = { "Mason", "MasonInstall", "MasonUpdate", "LspInfo" },
        event = { "BufReadPre", "BufNewFile" },
        dependencies = {
          { "williamboman/mason.nvim", opts = {} },
          "neovim/nvim-lspconfig",
        },
        opts = {
          automatic_installation = false,
        },
      },

      -- 6. Shared UI utilities (terminal, input, picker) for claudecode.nvim & opencode.nvim
      {
        "folke/snacks.nvim",
        lazy = false,
        opts = {
          input = { enabled = true },
          picker = { enabled = true },
          terminal = { enabled = true },
        },
      },

      -- 7. Claude Code IDE integration (<Space>ac, <Space>af, <Space>ab, <Space>as, <Space>aa/ad)
      {
        "coder/claudecode.nvim",
        dependencies = { "folke/snacks.nvim" },
        config = true,
        cmd = {
          "ClaudeCode",
          "ClaudeCodeFocus",
          "ClaudeCodeSelectModel",
          "ClaudeCodeAdd",
          "ClaudeCodeSend",
          "ClaudeCodeTreeAdd",
          "ClaudeCodeStatus",
          "ClaudeCodeStart",
          "ClaudeCodeStop",
          "ClaudeCodeOpen",
          "ClaudeCodeClose",
          "ClaudeCodeDiffAccept",
          "ClaudeCodeDiffDeny",
          "ClaudeCodeCloseAllDiffs",
        },
        keys = {
          { "<leader>ac", "<cmd>ClaudeCode<cr>", desc = "Toggle Claude Code" },
          { "<leader>af", "<cmd>ClaudeCodeFocus<cr>", desc = "Focus Claude Code" },
          { "<leader>ar", "<cmd>ClaudeCode --resume<cr>", desc = "Resume Claude Code" },
          { "<leader>aC", "<cmd>ClaudeCode --continue<cr>", desc = "Continue Claude Code" },
          { "<leader>am", "<cmd>ClaudeCodeSelectModel<cr>", desc = "Select Claude Model" },
          { "<leader>ab", "<cmd>ClaudeCodeAdd %<cr>", desc = "Add Current Buffer to Claude" },
          { "<leader>as", "<cmd>ClaudeCodeSend<cr>", mode = "v", desc = "Send Selection to Claude" },
          {
            "<leader>as",
            "<cmd>ClaudeCodeTreeAdd<cr>",
            desc = "Add Tree File to Claude",
            ft = { "NvimTree", "neo-tree", "oil", "minifiles", "netrw", "snacks_picker_list" },
          },
          { "<leader>aa", "<cmd>ClaudeCodeDiffAccept<cr>", desc = "Accept Claude Diff" },
          { "<leader>ad", "<cmd>ClaudeCodeDiffDeny<cr>", desc = "Deny Claude Diff" },
        },
      },

      -- 8. OpenCode IDE integration (<Space>ao, <Space>aO, <Space>at, go, goo)
      {
        "nickjvandyke/opencode.nvim",
        dependencies = { "folke/snacks.nvim" },
        keys = {
          {
            "<leader>ao",
            function() require("opencode").ask("@this: ") end,
            mode = { "n", "x" },
            desc = "Ask OpenCode",
          },
          {
            "<leader>aO",
            function() require("opencode").select() end,
            mode = { "n", "x" },
            desc = "Select OpenCode Action",
          },
          {
            "<leader>at",
            function() require("opencode").toggle() end,
            mode = { "n", "t" },
            desc = "Toggle OpenCode",
          },
          {
            "go",
            function() return require("opencode").operator("@this") end,
            mode = { "n", "x" },
            expr = true,
            desc = "Send Range to OpenCode",
          },
          {
            "goo",
            function() return require("opencode").operator("@this") .. "_" end,
            mode = "n",
            expr = true,
            desc = "Send Line to OpenCode",
          },
        },
        config = function()
          vim.g.opencode_opts = {}
        end,
      },
    }, {
      checker = { enabled = false },
      change_detection = { notify = false },
    })
  end
end
EOF
endif
