#!/usr/bin/env bash
# Grunt CLI — швидка інсталяція
# Використання: curl -fsSL https://raw.githubusercontent.com/GruntUA/grunt-cli/master/install.sh | bash

set -euo pipefail

REPO="https://github.com/GruntUA/grunt-cli.git"
MIN_PYTHON="3.12"
INSTALL_DIR="${GRUNT_CLI_DIR:-$HOME/.grunt-cli}"

# ---------- кольори ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}▸${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}✔${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail()  { printf "${RED}✗ %s${NC}\n" "$*" >&2; exit 1; }

# ---------- перевірка залежностей ----------
check_cmd() {
    command -v "$1" &>/dev/null || fail "$1 не знайдено. Встанови $1 та спробуй знову."
}

check_python() {
    local py=""
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            py="$candidate"
            break
        fi
    done
    [[ -z "$py" ]] && fail "Python не знайдено. Потрібен Python >= $MIN_PYTHON"

    local ver
    ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if [[ "$(printf '%s\n' "$MIN_PYTHON" "$ver" | sort -V | head -n1)" != "$MIN_PYTHON" ]]; then
        fail "Python $ver знайдено, але потрібен >= $MIN_PYTHON"
    fi

    PYTHON="$py"
    ok "Python $ver"
}

# ---------- основна логіка ----------
main() {
    printf "\n${CYAN}⚡ Grunt CLI — інсталяція${NC}\n\n"

    check_cmd git
    ok "git"

    check_python

    # Клонуємо або оновлюємо
    if [[ -d "$INSTALL_DIR" ]]; then
        info "Оновлення $INSTALL_DIR ..."
        git -C "$INSTALL_DIR" pull --quiet
        ok "Репозиторій оновлено"
    else
        info "Клонування в $INSTALL_DIR ..."
        git clone --quiet "$REPO" "$INSTALL_DIR"
        ok "Репозиторій клоновано"
    fi

    # Створюємо venv
    local venv="$INSTALL_DIR/.venv"
    if [[ ! -d "$venv" ]]; then
        info "Створення віртуального середовища..."
        "$PYTHON" -m venv "$venv"
    fi

    # Встановлюємо пакет
    info "Встановлення grunt-cli..."
    "$venv/bin/pip" install --quiet --upgrade pip
    "$venv/bin/pip" install --quiet -e "$INSTALL_DIR"
    ok "grunt-cli встановлено"

    # Симлінк у ~/.local/bin
    local bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
    ln -sf "$venv/bin/grunt" "$bin_dir/grunt"
    ok "Симлінк: $bin_dir/grunt"

    # Перевіряємо PATH
    if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
        warn "$bin_dir не в PATH"
        printf "  Додай до ~/.bashrc або ~/.zshrc:\n"
        printf "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n\n"
    fi

    # Перевірка
    if command -v grunt &>/dev/null; then
        local ver
        ver=$(grunt --version 2>/dev/null || true)
        ok "Готово! $ver"
    else
        ok "Встановлено. Перезавантаж термінал або виконай: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

    printf "\n  Почни з: ${CYAN}grunt install my-site${NC}\n\n"
}

main "$@"
