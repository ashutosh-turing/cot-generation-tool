# How to Run Django Migrations (Manual Schema Update)

## Context

- The deployment process (`deploy_enhanced.sh`) no longer runs database migrations automatically, to avoid accidental schema changes on production.
- You must now apply migrations manually when you are ready to update the schema.

## Steps to Run Migrations Safely

1. **(Recommended) Take a database backup before running migrations.**
   - You can use the backup functionality in your deployment scripts or manually copy the DB file.

2. **Activate the virtual environment:**
   ```bash
   source /home/cot-generation-tool/venv/bin/activate
   ```

3. **Set the Django settings module (if not already set):**
   ```bash
   export DJANGO_SETTINGS_MODULE=coreproject.settings
   ```

4. **Run migrations:**
   ```bash
   python3 manage.py migrate --noinput
   ```

   - This will apply all unapplied migrations to your database.

5. **(Optional) Check migration status:**
   ```bash
   python3 manage.py showmigrations
   ```

## When to Run

- Only run migrations after reviewing the changes and ensuring you have a backup.
- Prefer to run during a maintenance window or low-traffic period if the migration is expected to be disruptive.

## Rollback

- If something goes wrong, restore the database from your backup.

---

**Summary:**  
- Migrations are now a manual step for safety.
- Use the above commands to apply schema changes when you are ready.
