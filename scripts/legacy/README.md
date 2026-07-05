# Legacy One-Time Tools

This directory contains compatibility code for historical KenRadar data and
one-time migrations. These files are not part of the production runtime path.

- `sqlite_database.py` preserves the deprecated SQLite storage backend for
  historical migration and inspection only.
- `migrate_sqlite_to_pg.py` migrates old SQLite data into the current
  PostgreSQL schema.

The historical module entrypoint remains available:

```bash
python -m kenradar.storage.migrate_sqlite_to_pg --config config/config.yaml
```
