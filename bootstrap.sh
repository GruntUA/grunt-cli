#!/usr/bin/env bash
# Grunt CLI Bootstrap — автоматичне встановлення залежностей
#
#   curl -fsSL https://raw.githubusercontent.com/GruntUA/grunt-cli/master/bootstrap.sh | bash
#
# Питає, чи це сервер (тоді ще nginx і часовий пояс), а запущений від root —
# від імені якого користувача встановлювати grunt-cli (створює його).
# Без термінала (CI) бере відповіді за замовчуванням.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { printf "${CYAN}▸${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}✔${NC} %s\n" "$*"; }
fail() { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

# ask "Питання" "за замовчуванням" — відповідь у $REPLY. Читає з /dev/tty,
# бо при `curl ... | bash` stdin — це сам скрипт.
HAVE_TTY=false
{ : </dev/tty; } 2>/dev/null && HAVE_TTY=true

ask() {
    REPLY=""
    if $HAVE_TTY; then
        printf "${CYAN}?${NC} %s [%s]: " "$1" "$2" >/dev/tty
        read -r REPLY </dev/tty || REPLY=""
    fi
    REPLY="${REPLY:-$2}"
}

# ask_yn "Питання" y|n — код повернення 0 для «так»
ask_yn() {
    ask "$1 (y/n)" "$2"
    [[ "$REPLY" =~ ^[YyТт] ]]
}

if [ -r /etc/os-release ]; then
    . /etc/os-release
else
    fail "Cannot detect OS: /etc/os-release is missing"
fi

if ! command -v apt-get &>/dev/null; then
    fail "This bootstrap currently supports Debian/Ubuntu (apt-get required)."
fi

if [ "${ID:-}" != "debian" ] && [ "${ID:-}" != "ubuntu" ] && [[ "${ID_LIKE:-}" != *debian* ]]; then
    fail "Unsupported distro: ${ID:-unknown}. Use Debian/Ubuntu or a Debian-based distro."
fi

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
elif command -v sudo &>/dev/null; then
    SUDO="sudo"
else
    fail "sudo is required for package installation when not running as root."
fi

# ─── Питання ─────────────────────────────────────────────────────────────────
SERVER=false
if ask_yn "Це сервер (встановити nginx і задати часовий пояс)?" n; then
    SERVER=true
    ask "Часовий пояс" "Europe/Kyiv"
    GRUNT_TZ="$REPLY"
    [ -f "/usr/share/zoneinfo/$GRUNT_TZ" ] || fail "Невідомий часовий пояс: $GRUNT_TZ"
fi

if [ "$(id -u)" -eq 0 ]; then
    ask "Від імені якого користувача встановити Grunt (створю, якщо немає)" "grunt"
    GRUNT_USER="$REPLY"
    [ "$GRUNT_USER" != "root" ] || fail "Не встановлюйте Grunt від root — вкажіть звичайного користувача."
fi

# ─── Системна частина ────────────────────────────────────────────────────────
PACKAGES="curl git gnupg sudo redis-server"
$SERVER && PACKAGES="$PACKAGES nginx"

info "Оновлення списку пакетів..."
DEBIAN_FRONTEND=noninteractive ${SUDO} apt-get update -y -q

info "Встановлення системних залежностей ($PACKAGES)..."
# shellcheck disable=SC2086
DEBIAN_FRONTEND=noninteractive ${SUDO} apt-get install -y -q $PACKAGES

if $SERVER; then
    info "Часовий пояс: $GRUNT_TZ"
    ${SUDO} ln -sf "/usr/share/zoneinfo/$GRUNT_TZ" /etc/localtime
    echo "$GRUNT_TZ" | ${SUDO} tee /etc/timezone >/dev/null
fi

# ─── grunt-cli (від звичайного користувача) ──────────────────────────────────
install_cli() {
    set -euo pipefail
    if ! command -v mise &>/dev/null && [ ! -x "$HOME/.local/bin/mise" ]; then
        printf "▸ Встановлення mise...\n"
        curl -fsSL https://mise.jdx.dev/install.sh | sh
    fi

    # Налаштовуємо PATH для mise
    export PATH="$HOME/.local/bin:$HOME/.local/share/mise/bin:$PATH"

    # mise у кожному новому терміналі
    local activate='eval "$(~/.local/bin/mise activate bash)"'
    grep -qsF "$activate" "$HOME/.bashrc" || echo "$activate" >> "$HOME/.bashrc"

    local install_dir="${GRUNT_CLI_DIR:-$HOME/.grunt-cli}"
    if [ ! -d "$install_dir" ]; then
        printf "▸ Клонування репозиторію в %s...\n" "$install_dir"
        git clone --quiet https://github.com/GruntUA/grunt-cli.git "$install_dir"
    fi

    cd "$install_dir"
    printf "▸ Налаштування grunt-cli...\n"
    mise trust
    mise install
    mise run install
}

if [ "$(id -u)" -eq 0 ]; then
    if ! id "$GRUNT_USER" &>/dev/null; then
        info "Створення користувача $GRUNT_USER..."
        useradd --create-home --shell /bin/bash --groups sudo "$GRUNT_USER"
        if $HAVE_TTY; then
            info "Пароль для $GRUNT_USER (потрібен для sudo):"
            passwd "$GRUNT_USER" </dev/tty >/dev/tty 2>&1
        fi
    fi
    info "Встановлення grunt-cli від імені $GRUNT_USER..."
    sudo -u "$GRUNT_USER" -H env ${GRUNT_CLI_DIR:+GRUNT_CLI_DIR="$GRUNT_CLI_DIR"} \
        bash -c "$(declare -f install_cli); install_cli"
    ok "Готово! Grunt CLI встановлено для користувача $GRUNT_USER."
    printf "\nДалі працюйте від його імені: ${CYAN}su - %s${NC}\n\n" "$GRUNT_USER"
else
    install_cli
    ok "Готово! Grunt CLI та всі залежності встановлені."
    printf "\nПерезавантажте термінал або виконайте: ${CYAN}exec bash${NC}\n\n"
fi
