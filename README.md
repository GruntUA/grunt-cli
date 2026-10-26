# Grunt CLI

Command-line interface for managing [Grunt Framework](https://github.com/GruntUA/Grunt) projects and applications.

## Installation

### Option 1: One-command setup (recommended)

On Ubuntu/Debian you only need **curl** — the script installs everything else:

```bash
# if curl is missing: as root (fresh server, no sudo yet)
apt update && apt install -y curl
# ...or as a regular user
sudo apt update && sudo apt install -y curl

curl -fsSL https://raw.githubusercontent.com/GruntUA/grunt-cli/master/bootstrap.sh | bash
```

What it does:
- installs system packages via apt: **git**, **gnupg**, **sudo**, **Redis**;
- installs **[mise](https://mise.jdx.dev/)** and adds its activation to `~/.bashrc`;
- clones grunt-cli into `~/.grunt-cli` and installs it; mise brings **Python 3.15**, **Node.js** and **uv**.

It asks whether this is a server — then it also installs **nginx** and sets the time zone.
Run as **root** on a fresh server, it asks for a user name (default `grunt`), creates that user
with sudo rights and a password, and installs grunt-cli for them — continue with `su - grunt`.
Without a terminal (CI) it takes the defaults.

### Option 2: Manual step-by-step

#### 1. Install system packages and mise

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y curl git redis-server

curl https://mise.jdx.dev/install.sh | sh
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc && exec bash
```

#### 2. Install Grunt CLI

Clone the repository and use `mise` to set up the environment (Python 3.15, Node.js, uv) and install the CLI globally:

```bash
git clone https://github.com/GruntUA/grunt-cli.git
cd grunt-cli
mise trust
mise install
mise run install
```

---

## Quick start: Running Grunt Framework

Once the CLI is installed, follow these steps to set up a new Grunt project:

### 1. Create a new site
Create a local Grunt project (clones the framework and sets up the directory structure):

```bash
grunt install my-site
cd my-site
```

### 2. Initialize the site
Run database migrations and create an admin user:

```bash
grunt init
```

### 3. Start development servers
Start the FastAPI backend and Vite frontend:

```bash
grunt serve
```

Your site should now be running at `http://localhost:8000`.

---

## Commands

```bash
grunt install my-site
cd my-site
grunt init
grunt serve
```

---

### `grunt init`

Initialize the site: run database migrations and create an admin user.

```bash
grunt init
```

Must be run inside a Grunt project directory (where `grunt.site` exists).

---

### `grunt serve`

Start development servers (FastAPI backend + Vite frontend).

```bash
grunt serve [OPTIONS]

# Options:
#   --host           Bind host          (default: 0.0.0.0)
#   --port           Backend port       (default: 8000)
#   --no-reload      Disable auto-reload
#   --backend-only   Start only FastAPI
#   --frontend-only  Start only Vite
```

---

### `grunt update`

Update grunt-cli, the framework and apps (`git pull`), then packages, npm and the DB schema.

```bash
grunt update              # everything
grunt update cli          # only grunt-cli itself (works outside a project too)
grunt update framework    # framework + packages, npm, migrations
grunt update apps         # apps + packages, npm, migrations
```

For a private GitHub repository `grunt update` (like `grunt app get`) asks for a
fine-grained token and stores it for that repository only.

---

### `grunt upgrade`

Upgrade all dependencies to their latest versions and update configuration files (`mise.toml`, `package.json`, `pyproject.toml`, lock files):

```bash
grunt upgrade                 # upgrade everything: mise, uv, Node.js, Python, rclone, packages
grunt upgrade --dry-run       # preview updates without modifying files
grunt upgrade runtimes        # only system runtimes (mise, uv, node, python, rclone)
grunt upgrade packages        # only Python & Node.js packages and version files
grunt upgrade python          # only Python and its packages
grunt upgrade node            # only Node.js and npm packages
```

---

### `grunt setup production`

Turn the active site into a production deployment behind Cloudflare:

```bash
grunt setup production [--site mlt.gov.ua] [--port 8000]
```

It asks for the domain(s), the IP of a Cloudflare Tunnel (`cloudflared`) / proxy host in between
(if Cloudflare does not reach the server directly) and an optional Cloudflare Origin Certificate, then:
1. sets `DEBUG=false`, `APP_URL`, `ALLOWED_ORIGINS`, `REDIS_URL` (and a real `SECRET_KEY`) in the site `.env`;
2. builds the frontend (`npm run build`);
3. writes `config/production/`: `<bench>-web.service` (uvicorn, one process),
   `<bench>-worker.service` (taskiq) and an nginx site that takes the visitor IP
   from `CF-Connecting-IP` only for Cloudflare addresses;
4. after confirmation installs them with `sudo`, restarts the services and nginx, and checks the site answers.

With a certificate use Cloudflare SSL/TLS mode **Full (strict)**, without one — **Flexible**.
Logs: `journalctl -u <bench>-web -u <bench>-worker -f`.

---

### `grunt restart`

Restart the production services installed by `grunt setup production`
(`<bench>-web`, `<bench>-worker`) and check they came up:

```bash
grunt restart             # both
grunt restart --web       # only uvicorn
grunt restart --worker    # only the background worker
```

---

### `grunt app get`

Download an app from a Git repository into `./apps/` (works without the
framework's venv, so it can fetch an app into a fresh bench).

```bash
grunt app get <REPO_URL> [--branch BRANCH]
grunt app get https://github.com/MyOrg/my-app --branch develop
```

---

### Framework commands

Everything that works with sites, the database or DocTypes is implemented by
the framework (`apps/grunt`, `grunt/cli/`). Inside a bench `grunt` forwards
any command it does not know itself to the framework's CLI unchanged, so
`grunt <command> --help` always shows the real options.

```bash
grunt migrate [--site SITE]          # Alembic + DocType tables + fixtures
grunt app install|uninstall|list|create|remove|deps|export
grunt site list|info|create|delete|use   # `sites`, `site new/drop` still work
grunt users list|create|set-password
grunt db backup|restore|rollback|history|...
grunt doctype list|show|sync|scaffold|sync-types|export|import|test-gen
grunt fixtures export|dump|load
grunt data export|import
grunt shell [--site SITE]            # Python REPL inside a site
grunt test [APP] [pytest args]
grunt lint [--app APP] [--fix] [--format json]
```

The split: grunt-cli keeps what runs *around* a bench — creating it
(`install`, `init`, `master`), updating it (`update`, `upgrade`), running it
(`serve`, `restart`, `setup production`), `auth` and `app get`. A command is
implemented in exactly one place; add new site/DB/DocType commands to the
framework, not here.

---

### `grunt auth`

Authentication for API-based commands.

```bash
grunt auth login    # Log in and save token to ~/.grunt_token
grunt auth logout   # Remove saved token
grunt auth whoami   # Show current logged-in user
```

---

## Development

We use `mise` and `uv` for development.

```bash
# Set up environment
mise install
mise run dev

# Run tests, lint, format
mise run test
mise run lint
mise run fmt
```

---

## Directory structure

A Grunt project created with `grunt install`:

```
my-site/
├── apps/
│   ├── grunt/      ← Grunt framework (cloned from GitHub)
│   └── my-app/     ← Custom applications
├── grunt.site      ← Site configuration marker
└── .env            ← Environment variables (DB, SECRET_KEY, etc.)
```

When working outside a project directory, downloaded apps are cached in `~/.grunt/apps/`.

---

## Requirements

- Ubuntu/Debian for `bootstrap.sh` (it installs everything below); other systems — manual setup
- Git, Redis, [mise](https://mise.jdx.dev/)
- Python 3.15, Node.js and uv — installed by mise, no need to install them yourself
