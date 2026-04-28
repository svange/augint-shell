# Dockerfile for development environment
# Optimized for Claude Code SSH access and IDE integration

FROM python:3.12-bookworm

ARG AUGINT_SHELL_VERSION=0.0.0
LABEL org.opencontainers.image.version="${AUGINT_SHELL_VERSION}"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies and development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    git \
    curl \
    ca-certificates \
    # Development tools
    vim \
    nano \
    less \
    make \
    procps \
    htop \
    jq \
    netcat-openbsd \
    sudo \
    iproute2 \
    dos2unix \
    bind9-utils \
    # AUTO-UPDATE: cron daemon for background tool updates
    cron \
    # Python development
    python3-dev \
    # AWS CLI dependencies
    unzip \
    # Sandbox for Codex CLI
    bubblewrap \
    # Docker CLI only (no daemon)
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Docker Compose plugin (V2) for managing sibling containers
RUN mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -fsSL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Install AWS CLI v2
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf awscliv2.zip aws/

# Install Stripe CLI
RUN curl -s https://packages.stripe.dev/api/security/keypair/stripe-cli-gpg/public | gpg --dearmor | tee /usr/share/keyrings/stripe.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/stripe.gpg] https://packages.stripe.dev/stripe-cli-debian-local stable main" | tee -a /etc/apt/sources.list.d/stripe.list && \
    apt-get update && \
    apt-get install -y stripe && \
    rm -rf /var/lib/apt/lists/*

# Install AWS SAM CLI and pre-commit
RUN pip install aws-sam-cli pre-commit

# Install AWS Session Manager Plugin for SSO
RUN curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb" && \
    dpkg -i session-manager-plugin.deb && \
    rm session-manager-plugin.deb

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -s /root/.local/bin/uv /usr/local/bin/uv && \
    ln -s /root/.local/bin/uvx /usr/local/bin/uvx

# Configure uv to use centralized venv location (not in-project)
ENV UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/project

# Install Node.js (required for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install AWS CDK CLI
RUN npm install -g aws-cdk

# Install Claude Code via native installer (installs to ~/.local/bin)
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"

# Install codex
RUN npm install -g @openai/codex

# Install opencode (local coding assistant for Ollama)
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/root/.opencode/bin:${PATH}"

# Install pi (terminal coding agent, provider-agnostic)
RUN npm install -g @mariozechner/pi-coding-agent

# Install aider (alternative local coding assistant)
RUN curl -LsSf https://aider.chat/install.sh | sh

# Install Playwright with Chrome and ALL dependencies
# The --with-deps flag is CRUCIAL - it installs ~100+ system libraries Chrome needs
RUN npx playwright install chrome --with-deps

# IMPORTANT: Set environment to tell Chrome it's OK to run as root in a container
ENV CHROME_NO_SANDBOX=1
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Install agent-browser (lightweight browser automation CLI)
RUN npm install -g agent-browser && \
    agent-browser install

# Install Playwright CLI (advanced browser automation)
RUN npm install -g @playwright/cli

# Build argument for flexible project directory
ARG PROJECT_DIR=current-project

# Create root's directory structure
RUN mkdir -p /root/projects/${PROJECT_DIR} && \
    mkdir -p /root/.cache/uv && \
    mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh

# Set working directory
WORKDIR /root/projects/${PROJECT_DIR}

# Switch to root and configure environment
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root
USER root

# Install zsh, fish, and bash-completion for multi-shell support
RUN apt-get update && apt-get install -y --no-install-recommends \
    zsh \
    fish \
    bash-completion \
    && rm -rf /var/lib/apt/lists/*

# Install Starship (cross-shell prompt, used by bash/zsh/fish)
RUN curl -sS https://starship.rs/install.sh | sh -s -- --yes --bin-dir /usr/local/bin

# Install Oh My Zsh (unattended) + popular plugins
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended && \
    git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions \
        /root/.oh-my-zsh/custom/plugins/zsh-autosuggestions && \
    git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting \
        /root/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting && \
    git clone --depth=1 https://github.com/zsh-users/zsh-completions \
        /root/.oh-my-zsh/custom/plugins/zsh-completions && \
    git clone --depth=1 https://github.com/zsh-users/zsh-history-substring-search \
        /root/.oh-my-zsh/custom/plugins/zsh-history-substring-search

# Install Fisher (fish plugin manager) + plugins
# Bootstrap fisher by downloading it, then install plugins individually.
# Do NOT run "fisher install jorgebucaran/fisher" -- it conflicts with the
# manually downloaded fisher.fish file.
RUN mkdir -p /root/.config/fish/functions /root/.config/fish/completions /root/.config/fish/conf.d && \
    curl -sSL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish \
        -o /root/.config/fish/functions/fisher.fish
RUN fish -c "fisher install jorgebucaran/autopair.fish"
RUN fish -c "fisher install PatrickF1/fzf.fish"
RUN fish -c "fisher install meaningful-ooo/sponge"
RUN fish -c "fisher install jorgebucaran/replay.fish"
RUN fish -c "fisher install jethrokuan/z"

# Install Oh My Tmux (gpakosz/.tmux)
RUN git clone --depth=1 https://github.com/gpakosz/.tmux.git /root/.tmux && \
    ln -sf /root/.tmux/.tmux.conf /root/.tmux.conf

# Install vim-plug
RUN curl -fLo /root/.vim/autoload/plug.vim --create-dirs \
    https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim

# Copy shell configs into place
COPY shell-configs/bash_profile /root/.bash_profile
COPY shell-configs/bashrc /root/.bashrc
COPY shell-configs/zshrc /root/.zshrc
COPY shell-configs/fish-config.fish /root/.config/fish/config.fish
COPY shell-configs/starship.toml /root/.config/starship.toml
COPY shell-configs/vimrc /root/.vimrc
COPY shell-configs/tmux.conf.local /root/.tmux.conf.local

# Pre-install vim plugins headlessly so first launch is instant
RUN vim -es -u /root/.vimrc -i NONE -c "PlugInstall --sync" -c "qa" || true

# Pre-generate zsh completion dump so first launch is fast
RUN zsh -c "autoload -Uz compinit && compinit" || true

# Install additional useful development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Search and file tools
    ripgrep \
    fd-find \
    bat \
    tree \
    # Network tools
    httpie \
    # JSON/YAML tools
    jo \
    # Database tools
    sqlite3 \
    # Terminal multiplexer and fuzzy finder
    tmux \
    fzf \
    # Process monitoring
    glances \
    # DNS tools
    dnsutils \
    && rm -rf /var/lib/apt/lists/* && \
    # Create symlinks for fd and bat (Debian names them differently)
    ln -s /usr/bin/fdfind /usr/local/bin/fd && \
    ln -s /usr/bin/batcat /usr/local/bin/bat

# Install yq (YAML processor) - not available in Debian repos
RUN curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
    -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

# Configure git globally as root
RUN git config --global --add safe.directory '*' && \
    git config --global color.ui auto && \
    git config --global core.editor vim && \
    git config --global init.defaultBranch main && \
    # Ignore file permission changes on drvfs/9p-mounted Windows filesystems
    git config --global core.filemode false && \
    git config --global --unset-all http.sslbackend || true

# Note: Running as root to avoid Windows/Docker permission issues
# The docker-compose.yml should NOT specify user: "1000:1000"

# Create git wrapper that forces gnutls SSL backend and prevents local config pollution
RUN echo '#!/bin/bash' > /usr/local/bin/git && \
    echo '# Prevent writing SSL backend to local repo config which would break Windows Git' >> /usr/local/bin/git && \
    echo 'if [[ "$*" == *"config"* ]] && [[ "$*" == *"sslbackend"* ]] && [[ "$*" != *"--global"* ]]; then' >> /usr/local/bin/git && \
    echo '    echo "Warning: Preventing local sslbackend config. Use --global if needed." >&2' >> /usr/local/bin/git && \
    echo '    exit 0' >> /usr/local/bin/git && \
    echo 'fi' >> /usr/local/bin/git && \
    echo 'exec /usr/bin/git -c http.sslBackend=gnutls "$@"' >> /usr/local/bin/git && \
    chmod +x /usr/local/bin/git

# Note: Project dependencies are installed on container startup via entrypoint
# This is because the project files aren't available during build time
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# AUTO-UPDATE: Tool update script and runtime directories
COPY update-tools.sh /usr/local/bin/update-tools.sh
RUN chmod +x /usr/local/bin/update-tools.sh && \
    mkdir -p /var/run/ai-shell/update-markers /var/log/ai-shell

# MOTD: Environment status dashboard shown at container launch
COPY motd.sh /usr/local/bin/motd.sh
RUN chmod +x /usr/local/bin/motd.sh


ENTRYPOINT ["/docker-entrypoint.sh"]


# Default command keeps container running
CMD ["tail", "-f", "/dev/null"]
