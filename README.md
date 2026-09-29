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
- clones grunt-cli into `~/.grunt-cli` and installs it; mise brings **Python 3.14**, **Node.js** and **uv**.

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

Clone the repository and use `mise` to set up the environment (Python 3.14, Node.js, uv) and install the CLI globally:

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

### `grunt app`

Manage Grunt applications.

#### `grunt app get`

Download an app from a Git repository.

```bash
grunt app get <REPO_URL> [--branch BRANCH]
```

```bash
grunt app get https://github.com/GruntUA/Grunt
grunt app get https://github.com/MyOrg/my-app --branch develop
```

Downloaded apps are stored in `./apps/` (if inside a Grunt project) or `~/.grunt/apps/` (globally).

#### `grunt app install`

Install a downloaded app on a site.

```bash
grunt app install <NAME> --site <SITE>
```

`--site` accepts a hostname or full URL:

| Value | Resolves to |
|---|---|
| `localhost` | `http://localhost:8000` |
| `localhost:9000` | `http://localhost:9000` |
| `dev.myproject.com` | `https://dev.myproject.com` |
| `http://10.0.0.1:8080` | `http://10.0.0.1:8080` |

```bash
grunt app install Grunt --site localhost
grunt app install my-app --site dev.myproject.com
```

#### `grunt app create`

Scaffold a new app structure locally.

```bash
grunt app create <NAME> [--title "My App"]
```

#### `grunt app list`

List apps installed on a site.

```bash
grunt app list [--api http://localhost:8000]
```

#### `grunt app export`

Export DocTypes from a site to local JSON files.

```bash
grunt app export <NAME> [--api http://localhost:8000]
```

---

### `grunt db`

Database management commands.

```bash
grunt db migrate          # Apply all pending migrations
grunt db rollback [N]     # Revert N migrations (default: 1)
grunt db history          # Show migration history
grunt db reset --yes      # Delete all data (DEBUG mode only)
```

---

### `grunt doctype`

Inspect and manage DocTypes on a running site.

```bash
grunt doctype list [--module MODULE]   # List all DocTypes
grunt doctype show <NAME>              # Show DocType details and fields
grunt doctype sync <NAME>              # Sync DocType schema with the database
```

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
- Python 3.14, Node.js and uv — installed by mise, no need to install them yourself
