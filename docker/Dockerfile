# Dockerfile for development environment
# Optimized for Claude Code SSH access and IDE integration

FROM debian:bookworm-slim

ARG AUGINT_SHELL_VERSION=0.0.0
LABEL org.opencontainers.image.version="${AUGINT_SHELL_VERSION}"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/project \
    PNPM_HOME=/root/.local/share/pnpm \
    NPM_CONFIG_PREFIX=/usr/local
ENV PATH="/root/.local/bin:${PNPM_HOME}/bin:${PNPM_HOME}:/root/.opencode/bin:${PATH}"

# Install system dependencies, core/network/monitoring packages, and development tools
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    # Build essentials & base utilities
    build-essential \
    git \
    curl \
    ca-certificates \
    gnupg \
    openssh-client \
    xz-utils \
    bzip2 \
    file \
    pkg-config \
    libssl-dev \
    libffi-dev \
    # Development & CLI tools
    vim \
    nano \
    less \
    make \
    procps \
    htop \
    btop \
    duf \
    lsd \
    jq \
    sudo \
    dos2unix \
    ripgrep \
    fd-find \
    bat \
    tree \
    httpie \
    jo \
    sqlite3 \
    tmux \
    fzf \
    glances \
    # Network, DNS, packet capture & system diagnostics (dots-bootstrap / dots-doctor)
    netcat-openbsd \
    iproute2 \
    iputils-ping \
    bind9-utils \
    dnsutils \
    tcpdump \
    tshark \
    traceroute \
    mtr-tiny \
    nmap \
    lsof \
    whois \
    net-tools \
    # Shells
    zsh \
    bash-completion \
    # AUTO-UPDATE: cron daemon for background tool updates
    cron \
    # AWS CLI dependencies
    unzip \
    # Sandbox for Codex CLI
    bubblewrap \
    # Docker CLI only (no daemon)
    docker.io \
    # Markdown/LaTeX rendering (pi-studio PDF export)
    pandoc \
    texlive-xetex \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/* && \
    ln -s /usr/bin/fdfind /usr/local/bin/fd && \
    ln -s /usr/bin/batcat /usr/local/bin/bat

# Install Docker Compose plugin (V2) for managing sibling containers (multi-arch)
RUN ARCH=$(uname -m) && \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Install GitHub CLI and Stripe CLI in a single apt pass
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list && \
    curl -s https://packages.stripe.dev/api/security/keypair/stripe-cli-gpg/public | gpg --dearmor | tee /usr/share/keyrings/stripe.gpg > /dev/null && \
    echo "deb [signed-by=/usr/share/keyrings/stripe.gpg] https://packages.stripe.dev/stripe-cli-debian-local stable main" > /etc/apt/sources.list.d/stripe.list && \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gh stripe && \
    rm -rf /var/lib/apt/lists/*

# Install AWS CLI v2 and Session Manager Plugin (multi-arch)
RUN ARCH=$(uname -m) && \
    DEB_ARCH=$(dpkg --print-architecture) && \
    SSM_ARCH=$([ "$DEB_ARCH" = "arm64" ] && echo "ubuntu_arm64" || echo "ubuntu_64bit") && \
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o "awscliv2.zip" && \
    unzip -q awscliv2.zip && \
    ./aws/install && \
    rm -rf awscliv2.zip aws/ && \
    curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/${SSM_ARCH}/session-manager-plugin.deb" -o "session-manager-plugin.deb" && \
    dpkg -i session-manager-plugin.deb && \
    rm session-manager-plugin.deb

# Install GitLab CLI (glab), Jira CLI, yq, and chezmoi (multi-arch)
RUN DEB_ARCH=$(dpkg --print-architecture) && \
    JIRA_ARCH=$([ "$DEB_ARCH" = "arm64" ] && echo "arm64" || echo "x86_64") && \
    GLAB_VERSION=$(curl -fsSL "https://gitlab.com/api/v4/projects/34675721/releases/permalink/latest" | jq -r '.tag_name' | sed 's/^v//') && \
    curl -fsSL "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_${DEB_ARCH}.deb" -o /tmp/glab.deb && \
    dpkg -i /tmp/glab.deb && \
    rm /tmp/glab.deb && \
    JIRA_VERSION=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/ankitpokhrel/jira-cli/releases/latest" | sed 's#.*/tag/v##') && \
    curl -fsSL "https://github.com/ankitpokhrel/jira-cli/releases/download/v${JIRA_VERSION}/jira_${JIRA_VERSION}_linux_${JIRA_ARCH}.tar.gz" -o /tmp/jira.tar.gz && \
    tar -xzf /tmp/jira.tar.gz -C /tmp/ && \
    mv "/tmp/jira_${JIRA_VERSION}_linux_${JIRA_ARCH}/bin/jira" /usr/local/bin/jira && \
    rm -rf /tmp/jira* && \
    curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${DEB_ARCH}" -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq && \
    sh -c "$(curl -fsLS get.chezmoi.io)" -- -b /usr/local/bin && \
    chezmoi --version

# Install Neovim, zoxide, and modern terminal/network/security CLI tools from dots-bootstrap (multi-arch)
# Uses GitHub's /releases/latest HTTP redirect rather than api.github.com to avoid anonymous rate limits.
RUN set -eu && \
    ARCH=$(uname -m) && \
    DEB_ARCH=$(dpkg --print-architecture) && \
    ALT_ARCH=$([ "$DEB_ARCH" = "arm64" ] && echo "arm64" || echo "x86_64") && \
    FF_ARCH=$([ "$DEB_ARCH" = "arm64" ] && echo "aarch64" || echo "amd64") && \
    GL_ARCH=$([ "$DEB_ARCH" = "arm64" ] && echo "arm64" || echo "x64") && \
    _gh_tag() { curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$1/releases/latest" | sed 's#.*/tag/##'; } && \
    _install_tar_bin() { \
        mkdir -p /tmp/tool-extract && \
        curl -fsSL "$1" | tar -xz -C /tmp/tool-extract && \
        find /tmp/tool-extract -type f -name "$2" -exec install -m 0755 {} "/usr/local/bin/$2" \; && \
        rm -rf /tmp/tool-extract; \
    } && \
    _install_zip_bins() { \
        url="$1"; shift; \
        mkdir -p /tmp/tool-extract && \
        curl -fsSL "$url" -o /tmp/tool.zip && \
        unzip -q /tmp/tool.zip -d /tmp/tool-extract && \
        for bin in "$@"; do \
            find /tmp/tool-extract -type f -name "$bin" -exec install -m 0755 {} "/usr/local/bin/$bin" \; ; \
        done && \
        rm -rf /tmp/tool-extract /tmp/tool.zip; \
    } && \
    # Neovim (>= 0.10 so modern Lua init.vim works)
    mkdir -p /usr/local/share/nvim && \
    curl -fsSL "https://github.com/neovim/neovim/releases/latest/download/nvim-linux-${ALT_ARCH}.tar.gz" | tar -xz --strip-components=1 -C /usr/local/share/nvim && \
    ln -sf /usr/local/share/nvim/bin/nvim /usr/local/bin/nvim && \
    # zoxide
    curl -sSfL https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | sh -s -- --bin-dir /usr/local/bin && \
    # delta (syntax-highlighted git diff)
    DELTA_VER=$(_gh_tag dandavison/delta) && \
    curl -fsSL "https://github.com/dandavison/delta/releases/download/${DELTA_VER}/git-delta_${DELTA_VER}_${DEB_ARCH}.deb" -o /tmp/delta.deb && \
    dpkg -i /tmp/delta.deb && rm -f /tmp/delta.deb && \
    # lazygit
    LG_TAG=$(_gh_tag jesseduffield/lazygit) && LG_VER="${LG_TAG#v}" && \
    _install_tar_bin "https://github.com/jesseduffield/lazygit/releases/download/${LG_TAG}/lazygit_${LG_VER}_linux_${ALT_ARCH}.tar.gz" lazygit && \
    # yazi (terminal file manager)
    _install_zip_bins "https://github.com/sxyazi/yazi/releases/latest/download/yazi-${ARCH}-unknown-linux-musl.zip" yazi ya && \
    # bottom (btm TUI system monitor)
    _install_tar_bin "https://github.com/ClementTsang/bottom/releases/latest/download/bottom_${ARCH}-unknown-linux-musl.tar.gz" btm && \
    # procs (modern ps)
    PROCS_TAG=$(_gh_tag dalance/procs) && \
    _install_zip_bins "https://github.com/dalance/procs/releases/download/${PROCS_TAG}/procs-${PROCS_TAG}-${ARCH}-linux.zip" procs && \
    # dust (modern du)
    DUST_TAG=$(_gh_tag bootandy/dust) && \
    _install_tar_bin "https://github.com/bootandy/dust/releases/download/${DUST_TAG}/dust-${DUST_TAG}-${ARCH}-unknown-linux-musl.tar.gz" dust && \
    # fastfetch (polyfilled deb for Bookworm glibc compatibility)
    curl -fsSL "https://github.com/fastfetch-cli/fastfetch/releases/latest/download/fastfetch-linux-${FF_ARCH}-polyfilled.deb" -o /tmp/fastfetch.deb && \
    dpkg -i /tmp/fastfetch.deb && rm -f /tmp/fastfetch.deb && \
    # doggo (modern DNS client)
    _install_tar_bin "https://github.com/mr-karan/doggo/releases/latest/download/doggo-linux-${ARCH}.tar.gz" doggo && \
    # trippy (trip interactive traceroute + ping TUI)
    TRIP_VER=$(_gh_tag fujiapple852/trippy) && \
    _install_tar_bin "https://github.com/fujiapple852/trippy/releases/download/${TRIP_VER}/trippy-${TRIP_VER}-${ARCH}-unknown-linux-musl.tar.gz" trip && \
    # gping (ping with live graph)
    _install_tar_bin "https://github.com/orf/gping/releases/latest/download/gping-Linux-musl-${ALT_ARCH}.tar.gz" gping && \
    # xh (fast HTTP client)
    XH_TAG=$(_gh_tag ducaale/xh) && \
    _install_tar_bin "https://github.com/ducaale/xh/releases/download/${XH_TAG}/xh-${XH_TAG}-${ARCH}-unknown-linux-musl.tar.gz" xh && \
    # gitleaks (git secret scanner)
    GL_TAG=$(_gh_tag gitleaks/gitleaks) && GL_VER="${GL_TAG#v}" && \
    _install_tar_bin "https://github.com/gitleaks/gitleaks/releases/download/${GL_TAG}/gitleaks_${GL_VER}_linux_${GL_ARCH}.tar.gz" gitleaks && \
    # tlrc (tldr cheat sheets)
    TLRC_TAG=$(_gh_tag tldr-pages/tlrc) && \
    _install_tar_bin "https://github.com/tldr-pages/tlrc/releases/download/${TLRC_TAG}/tlrc-${TLRC_TAG}-${ARCH}-unknown-linux-musl.tar.gz" tldr && \
    # glow (terminal Markdown reader)
    GLOW_TAG=$(_gh_tag charmbracelet/glow) && GLOW_VER="${GLOW_TAG#v}" && \
    curl -fsSL "https://github.com/charmbracelet/glow/releases/download/${GLOW_TAG}/glow_${GLOW_VER}_${DEB_ARCH}.deb" -o /tmp/glow.deb && \
    dpkg -i /tmp/glow.deb && rm -f /tmp/glow.deb

# Install uv, standardize Python 3.13 via uv, and install Python CLI tools via uv tool
# (replaces standalone Python / global pip so uv is the single Python manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -sf /root/.local/bin/uv /usr/local/bin/uv && \
    ln -sf /root/.local/bin/uvx /usr/local/bin/uvx && \
    uv python install 3.13 --default && \
    uv tool install --python 3.13 aws-sam-cli && \
    uv tool install --python 3.13 pre-commit && \
    # aws-bedrock-token-generator is a library with no command, so `uv tool install`
    # refuses it. ai-shell imports it with `python3 -c`, so it goes into the managed 3.13.
    uv pip install --python "$(uv python find --managed-python 3.13)" --system \
        --break-system-packages aws-bedrock-token-generator && \
    uv tool install --python 3.13 git-remote-codecommit

# Install pnpm, standardize Node.js LTS via pnpm (replaces standalone NodeSource + corepack), and Bun
RUN mkdir -p "${PNPM_HOME}/bin" "${PNPM_HOME}/store" && \
    curl -fsSL https://get.pnpm.io/install.sh | env PNPM_HOME="${PNPM_HOME}" SHELL=/bin/bash sh - && \
    PNPM_MAJOR=$(pnpm --version | cut -d. -f1) && \
    if [ "${PNPM_MAJOR:-0}" -ge 11 ] 2>/dev/null; then \
        pnpm runtime set node lts -g; \
    else \
        pnpm env use --global lts; \
    fi && \
    # pnpm's node runtime ships node only, without npm and npx; the npm layer below needs them.
    { command -v npm >/dev/null 2>&1 || pnpm add -g npm; } && \
    npm --version && \
    pnpm config set store-dir "${PNPM_HOME}/store" --global && \
    printf 'prefix=/usr/local\n' > /etc/npmrc && \
    curl -fsSL https://bun.sh/install | bash && \
    ln -s /root/.bun/bin/bun /usr/local/bin/bun && \
    ln -s /root/.bun/bin/bunx /usr/local/bin/bunx

# Install PHP 8.4 CLI + extensions (deb.sury.org) and Composer 2
RUN curl -fsSL https://packages.sury.org/debsuryorg-archive-keyring.deb -o /tmp/sury-keyring.deb && \
    dpkg -i /tmp/sury-keyring.deb && \
    rm /tmp/sury-keyring.deb && \
    echo "deb [signed-by=/usr/share/keyrings/deb.sury.org-php.gpg] https://packages.sury.org/php/ bookworm main" \
        > /etc/apt/sources.list.d/php.list && \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    php8.4-cli \
    php8.4-pgsql \
    php8.4-sqlite3 \
    php8.4-mbstring \
    php8.4-xml \
    php8.4-curl \
    php8.4-zip \
    php8.4-intl \
    php8.4-bcmath \
    php8.4-readline \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://getcomposer.org/installer -o /tmp/composer-setup.php && \
    php /tmp/composer-setup.php --install-dir=/usr/local/bin --filename=composer && \
    rm /tmp/composer-setup.php

# Install Claude Code and OpenCode native binaries
RUN curl -fsSL https://claude.ai/install.sh | bash && \
    curl -fsSL https://opencode.ai/install | bash && \
    ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode && \
    mkdir -p /root/.config/opencode /root/.local/share/opencode /root/.agents/skills

# Consolidate all global npm packages into a single layer
RUN npm install -g \
    aws-cdk \
    @openai/codex \
    @mariozechner/pi-coding-agent \
    t3 \
    @agentclientprotocol/claude-agent-acp \
    @agentclientprotocol/codex-acp \
    @expo/ngrok@^4.1.0 \
    agent-browser \
    @playwright/cli \
    chrome-devtools-mcp@latest \
    zapier-platform-cli && \
    agent-browser install

# Install Playwright with Chrome and ALL dependencies
RUN npx playwright install chrome --with-deps

# IMPORTANT: Set environment to tell Chrome it's OK to run as root in a container
ENV CHROME_NO_SANDBOX=1
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Build argument for flexible project directory
ARG PROJECT_DIR=current-project

# Create root's directory structure and login-shell PATH profile
RUN mkdir -p /root/projects/${PROJECT_DIR} /root/.cache/uv /root/.ssh /root/.config/nvim && \
    chmod 700 /root/.ssh && \
    printf '%s\n' \
        'export PNPM_HOME="/root/.local/share/pnpm"' \
        'export PATH="/root/.local/bin:$PNPM_HOME/bin:$PNPM_HOME:/root/.opencode/bin:$PATH"' \
        > /etc/profile.d/ai-shell-path.sh

# Set working directory
WORKDIR /root/projects/${PROJECT_DIR}

# Switch to root and configure environment
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root
USER root

# Install Starship, Oh My Zsh + plugins, Oh My Tmux, and vim-plug
RUN curl -sS https://starship.rs/install.sh | sh -s -- --yes --bin-dir /usr/local/bin && \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended && \
    git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions \
        /root/.oh-my-zsh/custom/plugins/zsh-autosuggestions && \
    git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting \
        /root/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting && \
    git clone --depth=1 https://github.com/zsh-users/zsh-completions \
        /root/.oh-my-zsh/custom/plugins/zsh-completions && \
    git clone --depth=1 https://github.com/zsh-users/zsh-history-substring-search \
        /root/.oh-my-zsh/custom/plugins/zsh-history-substring-search && \
    git clone --depth=1 https://github.com/gpakosz/.tmux.git /root/.tmux && \
    ln -sf /root/.tmux/.tmux.conf /root/.tmux.conf && \
    curl -fLo /root/.vim/autoload/plug.vim --create-dirs \
        https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim && \
    mkdir -p /root/.config/nvim

# Copy shell configs into place
COPY shell-configs/bash_profile /root/.bash_profile
COPY shell-configs/bashrc /root/.bashrc
COPY shell-configs/zshrc /root/.zshrc
COPY shell-configs/starship.toml /root/.config/starship.toml
COPY shell-configs/vimrc /root/.vimrc
COPY shell-configs/nvim-init.vim /root/.config/nvim/init.vim
COPY shell-configs/tmux.conf.local /root/.tmux.conf.local

# Pre-install vim/neovim plugins and zsh completions headlessly so first launch is instant
RUN (vim -es -u /root/.vimrc -i NONE -c "PlugInstall --sync" -c "qa" || true) && \
    (nvim --headless "+Lazy! sync" +qa || true) && \
    (zsh -c "autoload -Uz compinit && compinit" || true)

# Configure git globally as root and install git wrapper
RUN git config --global --add safe.directory '*' && \
    git config --global color.ui auto && \
    git config --global core.editor vim && \
    git config --global init.defaultBranch main && \
    git config --global core.filemode false && \
    (git config --global --unset-all http.sslbackend || true) && \
    printf '%s\n' \
        '#!/bin/bash' \
        '# Prevent writing SSL backend to local repo config which would break Windows Git' \
        'if [[ "$*" == *"config"* ]] && [[ "$*" == *"sslbackend"* ]] && [[ "$*" != *"--global"* ]]; then' \
        '    echo "Warning: Preventing local sslbackend config. Use --global if needed." >&2' \
        '    exit 0' \
        'fi' \
        'exec /usr/bin/git -c http.sslBackend=gnutls "$@"' \
        > /usr/local/bin/git && \
    chmod +x /usr/local/bin/git

# Copy entrypoint, update-tools, env-doctor, and MOTD scripts
COPY docker-entrypoint.sh /docker-entrypoint.sh
COPY update-tools.sh /usr/local/bin/update-tools.sh
COPY env-doctor.sh /usr/local/bin/env-doctor
COPY motd.sh /usr/local/bin/motd.sh
RUN chmod +x /docker-entrypoint.sh /usr/local/bin/update-tools.sh /usr/local/bin/env-doctor /usr/local/bin/motd.sh && \
    mkdir -p /var/run/ai-shell/update-markers /var/log/ai-shell

# Standalone host CLI binary (built in CI via `python -m ai_shell.standalone --output docker/ai-shell`).
# Bundling it in the image lets systems that block PyPI and GitHub Releases extract
# the host executable directly with `docker run --rm --entrypoint "" svange/augint-shell:latest cat /usr/local/bin/ai-shell`.
COPY docker-entrypoint.sh ai-shell* /tmp/ai-shell-bootstrap/
RUN if [ -f /tmp/ai-shell-bootstrap/ai-shell ]; then \
        install -m 0755 /tmp/ai-shell-bootstrap/ai-shell /usr/local/bin/ai-shell; \
    fi && rm -rf /tmp/ai-shell-bootstrap

ENTRYPOINT ["/docker-entrypoint.sh"]


# Default command keeps container running
CMD ["tail", "-f", "/dev/null"]
