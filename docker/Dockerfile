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
    # Development & CLI tools
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
    dnsutils \
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
    # Shells
    zsh \
    bash-completion \
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
    apt-get update && \
    apt-get install -y --no-install-recommends gh stripe && \
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
    JIRA_VERSION=$(curl -fsSL "https://api.github.com/repos/ankitpokhrel/jira-cli/releases/latest" | jq -r '.tag_name' | sed 's/^v//') && \
    curl -fsSL "https://github.com/ankitpokhrel/jira-cli/releases/download/v${JIRA_VERSION}/jira_${JIRA_VERSION}_linux_${JIRA_ARCH}.tar.gz" -o /tmp/jira.tar.gz && \
    tar -xzf /tmp/jira.tar.gz -C /tmp/ && \
    mv "/tmp/jira_${JIRA_VERSION}_linux_${JIRA_ARCH}/bin/jira" /usr/local/bin/jira && \
    rm -rf /tmp/jira* && \
    curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${DEB_ARCH}" -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq && \
    sh -c "$(curl -fsLS get.chezmoi.io)" -- -b /usr/local/bin && \
    chezmoi --version

# Install AWS SAM CLI, pre-commit, and uv
RUN pip install aws-sam-cli pre-commit && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -s /root/.local/bin/uv /usr/local/bin/uv && \
    ln -s /root/.local/bin/uvx /usr/local/bin/uvx

# Configure uv to use centralized venv location (not in-project)
ENV UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/project

# Install Node.js (required for Claude Code) and Bun (required by Plannotator OpenCode plugin)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://bun.sh/install | bash && \
    ln -s /root/.bun/bin/bun /usr/local/bin/bun && \
    ln -s /root/.bun/bin/bunx /usr/local/bin/bunx

# Install PHP 8.4 CLI + extensions (deb.sury.org) and Composer 2
RUN curl -fsSL https://packages.sury.org/debsuryorg-archive-keyring.deb -o /tmp/sury-keyring.deb && \
    dpkg -i /tmp/sury-keyring.deb && \
    rm /tmp/sury-keyring.deb && \
    echo "deb [signed-by=/usr/share/keyrings/deb.sury.org-php.gpg] https://packages.sury.org/php/ bookworm main" \
        > /etc/apt/sources.list.d/php.list && \
    apt-get update && apt-get install -y --no-install-recommends \
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
    curl -fsSL https://opencode.ai/install | bash
ENV PATH="/root/.local/bin:/root/.opencode/bin:${PATH}"

# Consolidate all global npm packages into a single layer
RUN npm install -g \
    corepack \
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
    corepack enable && \
    agent-browser install

# Install Playwright with Chrome and ALL dependencies
RUN npx playwright install chrome --with-deps

# IMPORTANT: Set environment to tell Chrome it's OK to run as root in a container
ENV CHROME_NO_SANDBOX=1
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Build argument for flexible project directory
ARG PROJECT_DIR=current-project

# Create root's directory structure and login-shell PATH profile
RUN mkdir -p /root/projects/${PROJECT_DIR} /root/.cache/uv /root/.ssh && \
    chmod 700 /root/.ssh && \
    echo 'export PATH="/root/.local/bin:/root/.opencode/bin:$PATH"' > /etc/profile.d/ai-shell-path.sh

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
    mkdir -p /root/.config

# Copy shell configs into place
COPY shell-configs/bash_profile /root/.bash_profile
COPY shell-configs/bashrc /root/.bashrc
COPY shell-configs/zshrc /root/.zshrc
COPY shell-configs/starship.toml /root/.config/starship.toml
COPY shell-configs/vimrc /root/.vimrc
COPY shell-configs/tmux.conf.local /root/.tmux.conf.local

# Pre-install vim plugins and zsh completions headlessly so first launch is instant
RUN (vim -es -u /root/.vimrc -i NONE -c "PlugInstall --sync" -c "qa" || true) && \
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

# Copy entrypoint, update-tools, and MOTD scripts
COPY docker-entrypoint.sh /docker-entrypoint.sh
COPY update-tools.sh /usr/local/bin/update-tools.sh
COPY motd.sh /usr/local/bin/motd.sh
RUN chmod +x /docker-entrypoint.sh /usr/local/bin/update-tools.sh /usr/local/bin/motd.sh && \
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
