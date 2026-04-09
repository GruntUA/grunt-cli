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

info "Встановлення curl та git..."
sudo apt install -y -q curl git

if ! command -v mise &>/dev/null; then
    info "Встановлення mise..."
    curl https://mise.jdx.dev/install.sh | sh
    # Додаємо mise в PATH для поточного сеансу
    export PATH="$HOME/.local/share/mise/bin:$PATH"
    eval "$(mise activate bash)"
fi

info "Налаштування grunt-cli..."
mise trust
mise install
mise run install

ok "Готово! Grunt CLI та всі залежності встановлені."
printf "\nПерезавантажте термінал або виконайте: ${CYAN}eval \"\$(mise activate bash)\"${NC}\n\n"
