# Grunt CLI

Command-line interface for managing [Grunt Framework](https://github.com/GruntUA/Grunt) projects and applications.

## Installation

### Quick install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/GruntUA/grunt-cli/master/install.sh | bash
```

The script will:
- Check for Python 3.12+ and Git
- Clone the repository to `~/.grunt-cli`
- Create a virtual environment and install dependencies
- Add `grunt` symlink to `~/.local/bin`

You can set a custom install path via `GRUNT_CLI_DIR`:

```bash
GRUNT_CLI_DIR=~/my-path curl -fsSL https://raw.githubusercontent.com/GruntUA/grunt-cli/master/install.sh | bash
```

### Via pip

```bash
pip install grunt-cli
```

### From source

```bash
git clone https://github.com/GruntUA/grunt-cli.git
cd grunt-cli
pip install -e .
```

### Verify

```bash
grunt --version
```

---

## Quick start

Grunt CLI works standalone — no framework installation required upfront.

```bash
# 1. Download the Grunt framework
grunt app get https://github.com/GruntUA/Grunt

# 2. Install it on a site
grunt app install Grunt --site localhost

# 3. Install any other custom app the same way
grunt app get https://github.com/MyOrg/my-app
grunt app install my-app --site dev.myproject.com
```

---

## Commands

### `grunt install`

Create a new local Grunt project (clones the framework, sets up directory structure).

```bash
grunt install [PROJECT_NAME]

# Options:
#   --repo    Git URL of the Grunt framework  (default: https://github.com/GruntUA/Grunt.git)
#   --branch  Branch to clone                 (default: master)
```

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

- Python 3.12+
- Git
- Node.js + npm (for frontend development)
