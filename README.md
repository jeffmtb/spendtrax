# SpendTrax

SpendTrax is a small Python/SQLite expense-tracking tool for retirement planning. It imports transaction CSV exports from multiple financial institutions, normalizes them into one database, assigns each expense to a small set of retirement-planning buckets, and prints summary totals by year, account, category, and retirement relevance.

## Requirements

- Python 3
- pandas
- CSV exports from the supported financial institutions

Install the Python dependency from the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\\Scripts\\activate` instead.

## Import transactions

Place the exported CSV files in a directory, then run:

```bash
python3 spendtrax_import.py --dir . --db spendtrax.db --fresh
```

Options:

```text
--dir, -d   Directory containing CSV files; defaults to the current directory
--db        SQLite database path; defaults to spendtrax.db
--fresh     Delete the selected database before importing
```

Use `--fresh` when rebuilding the database from the CSV exports. Without it, imported rows are appended to the existing database and may be duplicated.

The importer recognizes these CSV formats:

- Chase credit-card exports
- FTCU Mastercard exports
- Capital One credit-card exports

Files are identified primarily by their filenames and secondarily by their headers. A successful import prints a summary of the loaded transactions.

## Categories

Expenses are consolidated into seven buckets:

| Category | Needed for retirement |
| --- | --- |
| Housing & Utilities | Yes |
| Food & Dining | Yes |
| Transportation | Yes |
| Health & Wellness | Yes |
| Personal & Household | No |
| Travel & Entertainment | No |
| Giving | No |

The importer uses the source bank category when available and merchant-description rules when it is missing or too broad. Descriptions are normalized so common variations such as hyphens and asterisks do not prevent matching.

## Date handling

The database uses the source posted date consistently:

- Chase: `Post Date`
- Capital One: `Posted Date`
- FTCU: `Posting Date`

The stored `year` is derived from that same date.

## Input validation

Before processing a file, the importer checks for required headers. It also validates dates, descriptions, amounts, and check numbers. Invalid rows are skipped with warnings, allowing other valid rows and files to continue importing.

## Query the database

To review the largest transactions in the `Personal & Household` bucket and its account breakdown:

```bash
python3 query_misc.py
```

This command expects `spendtrax.db` in the current directory. To inspect the database directly with SQLite:

```bash
sqlite3 spendtrax.db
```

Useful SQLite commands:

```sql
.tables
.schema transactions
SELECT category, COUNT(*), SUM(amount)
FROM transactions
GROUP BY category
ORDER BY SUM(amount) DESC;
```

## Database output

The importer creates `spendtrax.db` with a `transactions` table containing the date, year, description, category, amount, retirement flag, account, check number, and creation timestamp.

The database is generated from the CSV files. Keep the CSV exports as the source data so the database can be rebuilt with `--fresh` when needed.
