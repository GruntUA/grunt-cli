#!/usr/bin/env bash
# Grunt CLI — швидка інсталяція через uv
# Використання: curl -fsSL https://raw.githubusercontent.com/GruntUA/grunt-cli/master/install.sh | bash

set -euo pipefail

REPO="https://github.com/GruntUA/grunt-cli.git"
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

# ---------- визначення менеджера пакетів ----------
detect_pkg_manager() {
    if command -v apt-get &>/dev/null; then echo "apt"
    elif command -v dnf &>/dev/null; then echo "dnf"
    elif command -v yum &>/dev/null; then echo "yum"
    elif command -v pacman &>/dev/null; then echo "pacman"
    elif command -v brew &>/dev/null; then echo "brew"
    elif command -v apk &>/dev/null; then echo "apk"
    else echo "unknown"
    fi
}

# Встановлює системний пакет через виявлений менеджер
pkg_install() {
    local pkg="$1"
    local mgr
    mgr=$(detect_pkg_manager)

    info "Встановлення $pkg через $mgr..."
    case "$mgr" in
        apt)    sudo apt-get install -y -q "$pkg" ;;
        dnf)    sudo dnf install -y -q "$pkg" ;;
        yum)    sudo yum install -y -q "$pkg" ;;
        pacman) sudo pacman -S --noconfirm --quiet "$pkg" ;;
        brew)   brew install "$pkg" ;;
        apk)    sudo apk add --quiet "$pkg" ;;
        *)      fail "Không thể автоматично встановити $pkg. Встанови вручну та повтори." ;;
    esac
    ok "$pkg встановлено"
}

# ---------- перевірка й автоінсталяція утиліт ----------
ensure_cmd() {
    local cmd="$1"
    local pkg="${2:-$1}"  # ім'я пакету може відрізнятись від команди

    if command -v "$cmd" &>/dev/null; then
        ok "$cmd"
        return
    fi

    warn "$cmd не знайдено. Встановлюю..."
    pkg_install "$pkg"

    command -v "$cmd" &>/dev/null || fail "$cmd не вдалося встановити"
}

# ---------- перевірка / встановлення uv ----------
ensure_uv() {
    if command -v uv &>/dev/null; then
        ok "uv $(uv --version | awk '{print $2}')"
        return
    fi

    warn "uv не знайдено. Встановлюю..."

    # Потрібен curl для завантаження uv
    ensure_cmd curl

    curl -LsSf https://astral.sh/uv/install.sh | sh

    # оновлюємо PATH поточного сесії
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    command -v uv &>/dev/null || fail "uv не вдалося встановити. Спробуй вручну: https://docs.astral.sh/uv/"
    ok "uv встановлено"
}

# ---------- основна логіка ----------
main() {
    printf "\n${CYAN}⚡ Grunt CLI — інсталяція${NC}\n\n"

    ensure_cmd git
    ensure_uv

    # Клонуємо або оновлюємо репозиторій
    if [[ -d "$INSTALL_DIR" ]]; then
        info "Оновлення $INSTALL_DIR ..."
        git -C "$INSTALL_DIR" pull --quiet
        ok "Репозиторій оновлено"
    else
        info "Клонування в $INSTALL_DIR ..."
        git clone --quiet "$REPO" "$INSTALL_DIR"
        ok "Репозиторій клоновано"
    fi

    # Встановлюємо як uv tool
    info "Встановлення grunt-cli..."
    uv tool install --editable "$INSTALL_DIR" --quiet
    ok "grunt-cli встановлено"

    # Перевіряємо PATH
    local bin_dir
    bin_dir="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"

    if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
        warn "$bin_dir не в PATH"
        printf "  Додай до ~/.bashrc або ~/.zshrc:\n"
        printf "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n\n"
    fi

    # Фінальна перевірка
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
