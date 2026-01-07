# PostgreSQL Installation Guide for macOS

Follow these steps to install PostgreSQL and set up the Hyperliquid database.

## Step 1: Install Homebrew

Homebrew is a package manager for macOS that makes installing PostgreSQL easy.

### Open Terminal and run:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**What to expect:**
- The installer will ask for your password (admin/sudo access required)
- It will download and install Homebrew
- Installation takes 2-5 minutes
- At the end, it will show commands to add Homebrew to your PATH

### Important: Add Homebrew to your PATH

After installation completes, the installer will show output like this:

```
==> Next steps:
- Run these two commands in your terminal to add Homebrew to your PATH:
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
```

**Copy and run those exact commands** (they will be specific to your system).

### Verify Homebrew is installed:

```bash
brew --version
```

You should see something like: `Homebrew 4.x.x`

---

## Step 2: Install PostgreSQL

Now that Homebrew is installed, installing PostgreSQL is simple:

```bash
brew install postgresql@15
```

**What to expect:**
- Downloads PostgreSQL 15 and dependencies
- Takes 3-5 minutes
- No password required (Homebrew handles everything)

### Verify PostgreSQL is installed:

```bash
postgres --version
```

You should see: `postgres (PostgreSQL) 15.x`

---

## Step 3: Start PostgreSQL Service

PostgreSQL needs to be running before we can use it.

### Start PostgreSQL now:

```bash
brew services start postgresql@15
```

### Make sure it's running:

```bash
brew services list | grep postgresql
```

You should see:
```
postgresql@15  started  <your-user>  ~/Library/LaunchAgents/...
```

The status should say **"started"** (in green if your terminal supports colors).

---

## Step 4: Add PostgreSQL to PATH

To use `psql` and other PostgreSQL commands easily, add them to your PATH:

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

### Verify psql is accessible:

```bash
psql --version
```

You should see: `psql (PostgreSQL) 15.x`

---

## Step 5: Create the Database

Now we'll create the `hyperliquid` database:

```bash
createdb hyperliquid
```

**What to expect:**
- Command completes silently (no output = success)
- Creates a database named `hyperliquid`
- Uses your current user as the database owner

### Verify the database was created:

```bash
psql -l | grep hyperliquid
```

You should see a line with `hyperliquid` in it.

---

## Step 6: Apply the Database Schema

Now we'll create all the tables using the schema file:

```bash
cd /Users/willyb/hyperliquid-wallet-dashboard
psql -d hyperliquid -f db/schema.sql
```

**What to expect:**
- Lots of output showing CREATE TABLE, CREATE INDEX, INSERT commands
- Should end without errors
- Takes 1-2 seconds

### Verify tables were created:

```bash
psql -d hyperliquid -c "\dt"
```

You should see a list of 11 tables:
- alerts
- alert_state
- ingest_health
- ingest_runs
- signal_contributors
- signals
- snapshot_anomalies
- wallet_snapshots
- wallet_universe_current
- wallet_universe_members
- wallet_universe_runs

---

## Step 7: Test Database Connection

Let's make sure everything works:

```bash
psql -d hyperliquid -c "SELECT version();"
```

You should see PostgreSQL version information.

---

## ✅ Installation Complete!

PostgreSQL is now installed and the `hyperliquid` database is ready.

### Next Step: Test the Full Ingestion

Run a test ingestion cycle:

```bash
cd /Users/willyb/hyperliquid-wallet-dashboard
python3 -m src.ingest.fetch --once --refresh-universe
```

This will:
1. Fetch the top 200 wallets from Hyperliquid
2. Fetch current positions for all wallets
3. Write data to the database
4. Show you the results

Expected output:
```
============================================================
UNIVERSE REFRESH STARTING
============================================================
Fetching leaderboard data...
Parsing X leaderboard rows...
Universe diff: Y entered, Z exited
...
✓ Snapshot 2026-01-06 XX:XX:00+00:00: success | coverage=XX.X% | rows=XXX
```

### Verify Data Was Saved

```bash
# Check health status
psql -d hyperliquid -c "SELECT * FROM v_latest_health;"

# Check wallet count
psql -d hyperliquid -c "SELECT COUNT(*) FROM wallet_universe_current;"

# Check recent snapshots
psql -d hyperliquid -c "
  SELECT snapshot_ts, status, coverage_pct, rows_written
  FROM ingest_runs
  ORDER BY snapshot_ts DESC
  LIMIT 5;
"
```

---

## Troubleshooting

### "command not found: brew"

After installing Homebrew, you need to add it to your PATH. Run the commands shown at the end of the Homebrew installation.

### "command not found: psql"

PostgreSQL binaries are not in your PATH. Run:
```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

### "could not connect to server"

PostgreSQL service is not running. Start it:
```bash
brew services start postgresql@15
```

### "database does not exist"

You need to create the database:
```bash
createdb hyperliquid
```

### "permission denied"

Your user doesn't have PostgreSQL admin rights. This shouldn't happen with Homebrew's default setup, but if it does:
```bash
createuser -s $(whoami)
```

---

## Managing PostgreSQL

### Stop PostgreSQL:
```bash
brew services stop postgresql@15
```

### Restart PostgreSQL:
```bash
brew services restart postgresql@15
```

### Check if PostgreSQL is running:
```bash
brew services list | grep postgresql
```

### Uninstall (if needed):
```bash
brew services stop postgresql@15
brew uninstall postgresql@15
```

---

## Summary of Commands

Here's a quick reference of all the commands in order:

```bash
# 1. Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Add Homebrew to PATH (replace with commands shown by installer)
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

# 3. Install PostgreSQL
brew install postgresql@15

# 4. Start PostgreSQL
brew services start postgresql@15

# 5. Add psql to PATH
echo 'export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile

# 6. Create database
createdb hyperliquid

# 7. Apply schema
cd /Users/willyb/hyperliquid-wallet-dashboard
psql -d hyperliquid -f db/schema.sql

# 8. Test ingestion
python3 -m src.ingest.fetch --once --refresh-universe
```

---

**Ready to begin? Start with Step 1!**
