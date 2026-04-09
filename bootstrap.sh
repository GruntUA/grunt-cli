#!/usr/bin/env bash
# Grunt CLI Bootstrap — автоматичне встановлення залежностей
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { printf "${CYAN}▸${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}✔${NC} %s\n" "$*"; }

info "Оновлення списку пакетів..."
sudo apt update -y -q

info "Встановлення системних залежностей (curl, git, gnupg)..."
sudo apt install -y -q curl git gnupg

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
