# CLAUDE.md – Hyperliquid Wallet Dashboard

## Current State
- [ ] Phase 1: DB schema + ingestion working for HYPE/BTC/ETH at 60s
- [ ] Phase 2: Signals computed at 5m + playbook outputs
- [ ] Phase 3: Alerts + throttling + historical charts
- [ ] Phase 4: Validation (50+ trades logged, review outcomes)

---

## Purpose (WHY)

Local prototype to track **top Hyperliquid wallet behavior** on **HYPE, BTC, and ETH** in order to provide **objective regime filters** for manual discretionary trading.

The dashboard surfaces:
- Consensus alignment among top wallets
- Dispersion (agreement vs disagreement)
- Early exit behavior from large / smart wallets
- Clear playbook outputs (Long-only / Short-only / No-trade)

This system is informational only. No automated trading in the prototype.

---

## Repository Map (WHAT)

```
├── src/
│   ├── ingest/       # 60s wallet snapshot collection
│   ├── aggregate/    # 5m aggregation and signal persistence
│   ├── signals/      # Signal computation logic (alignment, dispersion, exits)
│   ├── alerts/       # Alert evaluation and throttling
│   └── ui/           # Streamlit dashboard
├── db/               # PostgreSQL schema and migrations
├── docs/             # Source of truth for math, logic, and operational specs
├── skills/           # Task-specific implementation playbooks
├── tests/            # Unit and integration tests
└── .env.example      # Environment template (copy to .env)
```

---

## How to Work in This Repo (HOW)

### General Rules
- **Scope:** ONLY HYPE, BTC, and ETH.
- **Statelessness:** Treat every session as fresh; consult `docs/` for logic.
- **Cadence:** Snapshots = 60s | Signals = 5m.
- **Actionability:** Every signal must map to a playbook output.
- **Fail loud:** Surface data staleness in UI; never silently serve old signals.
- Prefer **behavioral deltas** over absolute values.
- Keep the dashboard **single-screen and fast-loading**.

### Data Source
- Use the **Hyperliquid public APIs** (no authentication required).
- API docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- Primary endpoints: `/info` for positions, leaderboard, and wallet data.
- Respect rate limits; implement retries with backoff on failures.

### Making Changes
1. Update documentation first if definitions or behavior change.
2. Update schema/migrations only if required.
3. Implement changes in small, testable steps.
4. Add sanity checks for new signals or alerts.
5. Verify cadence, bounds, and alert throttling.

---

## Local Development

### Environment Setup
```bash
cp .env.example .env        # Configure local settings
pip install -r requirements.txt
createdb hyperliquid        # Create Postgres database
psql -d hyperliquid -f db/schema.sql
```

### Common Commands
```bash
# Run components
python -m src.ingest.fetch          # Start ingestion (60s loop)
python -m src.aggregate.run         # Start aggregation (5m loop)
streamlit run src/ui/app.py         # Launch dashboard

# Verification
ruff check .                        # Lint
pytest tests/                       # Test suite
```

---

## Non-Goals
- Automated trade execution
- Price prediction or indicator replacement (RSI/MACD)
- Machine learning models
- Adding assets before prototype validation
- Overfitting thresholds on small samples

---

## Progressive Disclosure (Read When Relevant)

| Topic | File |
|-------|------|
| Signal definitions & formulas | `docs/product/metrics.md` |
| Playbook & alert logic | `docs/product/playbooks.md` |
| Database schema | `docs/architecture/schema.md` |
| Local ops & troubleshooting | `docs/runbooks/local_dev.md` |

If a task requires detailed logic, read the relevant file in `docs/` before writing code.

---

## Skills Usage

Use the appropriate file in `skills/` when implementing or modifying:

| Task | Skill File |
|------|------------|
| Wallet data collection | `skills/ingestion.md` |
| Signal computation | `skills/signals.md` |
| Alert evaluation | `skills/alerts.md` |
| Dashboard layout | `skills/dashboard.md` |
| Testing & QA | `skills/qa.md` |
| Operations & debugging | `skills/runbooks.md` |

**Do not invent new logic that conflicts with `docs/`.** Skills files contain implementation guidance; `docs/` contains the source of truth for definitions and behavior.
