#!/usr/bin/env bash
# Grunt CLI Bootstrap — автоматичне встановлення залежностей
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { printf "${CYAN}▸${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}✔${NC} %s\n" "$*"; }

if [ -r /etc/os-release ]; then
    . /etc/os-release
else
    echo "Cannot detect OS: /etc/os-release is missing" >&2
    exit 1
fi

if ! command -v apt-get &>/dev/null; then
    echo "This bootstrap currently supports Debian/Ubuntu (apt-get required)." >&2
    exit 1
fi

if [ "${ID:-}" != "debian" ] && [ "${ID:-}" != "ubuntu" ] && [[ "${ID_LIKE:-}" != *debian* ]]; then
    echo "Unsupported distro: ${ID:-unknown}. Use Debian/Ubuntu or a Debian-based distro." >&2
    exit 1
fi

if command -v sudo &>/dev/null; then
    SUDO="sudo"
elif [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    echo "sudo is required for package installation when not running as root." >&2
    exit 1
fi

info "Оновлення списку пакетів..."
DEBIAN_FRONTEND=noninteractive ${SUDO} apt-get update -y -q

info "Встановлення системних залежностей (curl, git, gnupg)..."
DEBIAN_FRONTEND=noninteractive ${SUDO} apt-get install -y -q curl git gnupg

if ! command -v mise &>/dev/null; then
    info "Встановлення mise..."
    curl https://mise.jdx.dev/install.sh | sh
fi

# Налаштовуємо PATH для mise
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/bin:$PATH"

INSTALL_DIR="${GRUNT_CLI_DIR:-$HOME/.grunt-cli}"
REPO_URL="https://github.com/GruntUA/grunt-cli.git"

if [ ! -d "$INSTALL_DIR" ]; then
    info "Клонування репозиторію в $INSTALL_DIR..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

info "Налаштування grunt-cli..."
mise trust
mise install
mise run install

ok "Готово! Grunt CLI та всі залежності встановлені."
printf "\nПерезавантажте термінал або виконайте: ${CYAN}eval \"\$(mise activate bash)\"${NC}\n\n"
