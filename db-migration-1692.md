# Database Migration v5 - Task 1692

## Summary

Implemented database schema migration v5 for EQUIPA, adding embedding support and lesson graph functionality for enhanced semantic search and relationship mapping.

## Changes Made

### 1. Migration Script (`db_migrate.py`)

- Set `CURRENT_VERSION = 5`
- Added `migrate_v4_to_v5()` function that:
  - Adds `embedding TEXT` column to `lessons_learned` table
  - Adds `embedding TEXT` column to `agent_episodes` table
  - Creates `lesson_graph_edges` table with:
    - `id` (PRIMARY KEY)
    - `src_id` (INTEGER, FK to lessons_learned)
    - `dst_id` (INTEGER, FK to lessons_learned)
    - `edge_type` (TEXT)
    - `weight` (REAL, default 1.0)
    - `created_at` (TIMESTAMP)
    - UNIQUE constraint on `(src_id, dst_id, edge_type)`
  - Creates indexes:
    - `idx_lesson_graph_src` on `src_id`
    - `idx_lesson_graph_dst` on `dst_id`
- Migration uses try/except for idempotency (handles "duplicate column" errors)
- Registered migration in `MIGRATIONS` dict

### 2. Schema Definition (`schema.sql`)

- Already contained v5 schema:
  - `embedding TEXT` column in `lessons_learned` (line 326)
  - `embedding TEXT` column in `agent_episodes` (line 343)
  - `lesson_graph_edges` table definition (lines 566-576)
  - Version stamp `PRAGMA user_version = 5` (line 582)

### 3. Database Layer (`equipa/db.py`)

- `ensure_schema()` already contains v5 schema elements:
  - Embedding columns in both tables
  - `lesson_graph_edges` table with proper constraints
  - Indexes for graph traversal performance

### 4. Test Suite (`tests/test_db_migration_v5.py`)

Created comprehensive test suite with 8 tests:
- `test_migration_adds_embedding_columns` - Verifies columns added to both tables
- `test_migration_creates_graph_table` - Verifies table creation and schema
- `test_migration_creates_indexes` - Verifies index creation on src_id/dst_id
- `test_migration_idempotent` - Ensures migration can run multiple times safely
- `test_graph_edge_insert` - Tests inserting edges into graph
- `test_graph_unique_constraint` - Verifies UNIQUE constraint prevents duplicates
- `test_full_migration_v4_to_v5` - Tests end-to-end migration via `run_migrations()`
- `test_embedding_can_store_json` - Verifies embedding column stores JSON vectors

**All tests pass:** 8/8 in 0.71s

## Migration Details

### Embedding Columns

The `embedding TEXT` column stores JSON-encoded vector representations:
- Enables semantic similarity search for lessons and episodes
- Stored as JSON for SQLite compatibility (no native array type)
- Default `NULL` allows gradual backfilling

### Lesson Graph Table

The `lesson_graph_edges` table enables:
- Relationship mapping between lessons (similar, causes, solves, etc.)
- Weighted edges for similarity scores or strength
- Efficient graph traversal via indexed src/dst lookups
- Unique constraint prevents duplicate edges

Edge types could include:
- `"similar"` - semantically similar lessons
- `"causes"` - lesson A causes error pattern in lesson B
- `"solves"` - lesson A solves problem in lesson B
- `"supersedes"` - lesson A replaces lesson B

### Idempotency

Migration handles re-runs gracefully:
- `ALTER TABLE ADD COLUMN` wrapped in try/except for OperationalError
- `CREATE TABLE IF NOT EXISTS` for graph table
- `CREATE INDEX IF NOT EXISTS` for indexes

## Usage

### Fresh Install
New databases get v5 schema automatically via `schema.sql`.

### Upgrade Existing DB
```bash
python db_migrate.py /path/to/theforge.db
```

Or programmatically:
```python
from db_migrate import run_migrations
success, from_ver, to_ver = run_migrations("/path/to/theforge.db")
```

### Storing Embeddings
```python
import json
import sqlite3

conn = sqlite3.connect("theforge.db")
vector = [0.1, 0.2, 0.3, ...]  # From embedding model
conn.execute(
    "UPDATE lessons_learned SET embedding = ? WHERE id = ?",
    (json.dumps(vector), lesson_id)
)
conn.commit()
```

### Creating Graph Edges
```python
conn.execute("""
    INSERT INTO lesson_graph_edges (src_id, dst_id, edge_type, weight)
    VALUES (?, ?, 'similar', 0.85)
""", (lesson1_id, lesson2_id))
```

## Verification

### Check Current Version
```sql
PRAGMA user_version;  -- Should return 5
```

### Verify Columns Exist
```sql
PRAGMA table_info(lessons_learned);
PRAGMA table_info(agent_episodes);
```

### Verify Graph Table
```sql
SELECT sql FROM sqlite_master WHERE name = 'lesson_graph_edges';
```

### Check Migration History
```sql
SELECT * FROM schema_migrations ORDER BY applied_at DESC;
```

## Backward Compatibility

- Migration preserves all existing data
- Embedding columns default to NULL (non-breaking)
- Graph table is additive (doesn't modify existing tables)
- Rollback: Restore from auto-created backup if needed

## Performance Notes

- Indexes on `src_id` and `dst_id` enable O(log n) graph traversal
- Embedding storage is space-efficient (TEXT compression)
- UNIQUE constraint prevents duplicate edges without extra queries

## Future Enhancements

1. **Embedding Generation**: Integrate with embedding models (OpenAI, Anthropic, local)
2. **Semantic Search**: Query similar lessons by cosine similarity
3. **Graph Algorithms**: Find lesson clusters, detect cycles, compute centrality
4. **Auto-linking**: Automatically create edges based on similarity scores
5. **Compression**: Store embeddings as binary blobs for 50% space savings

## Copyright

Copyright 2026 Forgeborn
