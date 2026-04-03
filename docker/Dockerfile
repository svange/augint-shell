# Dockerfile for development environment
# Optimized for Claude Code SSH access and IDE integration

FROM python:3.12-bookworm

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
    # Python development
    python3-dev \
    # AWS CLI dependencies
    unzip \
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
USER root

# Set up root's bash environment with useful aliases and settings
RUN echo '# Useful aliases' >> /root/.bashrc && \
    echo 'alias ll="ls -la"' >> /root/.bashrc && \
    echo 'alias la="ls -A"' >> /root/.bashrc && \
    echo 'alias l="ls -CF"' >> /root/.bashrc && \
    echo 'alias ..="cd .."' >> /root/.bashrc && \
    echo 'alias ...="cd ../.."' >> /root/.bashrc && \
    echo 'alias gs="git status"' >> /root/.bashrc && \
    echo 'alias gd="git diff"' >> /root/.bashrc && \
    echo 'alias gl="git log --oneline -10"' >> /root/.bashrc && \
    echo 'alias dc="docker compose"' >> /root/.bashrc && \
    echo '' >> /root/.bashrc && \
    echo '# Environment settings' >> /root/.bashrc && \
    echo 'export EDITOR=vim' >> /root/.bashrc && \
    echo 'export HISTSIZE=10000' >> /root/.bashrc && \
    echo 'export HISTFILESIZE=20000' >> /root/.bashrc && \
    echo 'export HISTCONTROL=ignoreboth:erasedups' >> /root/.bashrc && \
    echo '' >> /root/.bashrc && \
    echo '# Better prompt showing git branch' >> /root/.bashrc && \
    echo 'parse_git_branch() {' >> /root/.bashrc && \
    echo '    git branch 2> /dev/null | sed -e "/^[^*]/d" -e "s/* \(.*\)/ (\1)/"' >> /root/.bashrc && \
    echo '}' >> /root/.bashrc && \
    echo 'export PS1="\[\033[01;31m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[33m\]\$(parse_git_branch)\[\033[00m\]\$ "' >> /root/.bashrc && \
    echo '' >> /root/.bashrc && \
    echo '# Useful functions' >> /root/.bashrc && \
    echo 'mkcd() { mkdir -p "$1" && cd "$1"; }' >> /root/.bashrc && \
    echo 'extract() {' >> /root/.bashrc && \
    echo '    if [ -f "$1" ]; then' >> /root/.bashrc && \
    echo '        case "$1" in' >> /root/.bashrc && \
    echo '            *.tar.bz2) tar xjf "$1" ;;' >> /root/.bashrc && \
    echo '            *.tar.gz) tar xzf "$1" ;;' >> /root/.bashrc && \
    echo '            *.tar) tar xf "$1" ;;' >> /root/.bashrc && \
    echo '            *.zip) unzip "$1" ;;' >> /root/.bashrc && \
    echo '            *) echo "Unknown archive format" ;;' >> /root/.bashrc && \
    echo '        esac' >> /root/.bashrc && \
    echo '    fi' >> /root/.bashrc && \
    echo '}' >> /root/.bashrc

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
    # Disable git hooks in container - AI tools commit frequently; pre-commit is run explicitly
    git config --global core.hooksPath /dev/null && \
    git config --global --unset-all http.sslbackend || true

# Set up vim with basic config
RUN echo 'set number' >> /root/.vimrc && \
    echo 'set autoindent' >> /root/.vimrc && \
    echo 'set expandtab' >> /root/.vimrc && \
    echo 'set tabstop=4' >> /root/.vimrc && \
    echo 'set shiftwidth=4' >> /root/.vimrc && \
    echo 'syntax on' >> /root/.vimrc

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


ENTRYPOINT ["/docker-entrypoint.sh"]


# Default command keeps container running
CMD ["tail", "-f", "/dev/null"]
