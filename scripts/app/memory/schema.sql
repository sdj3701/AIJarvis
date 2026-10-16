-- Jarvis SQLite schema version 1. SCHEMAS.md section 5 is the source of truth.
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id    TEXT PRIMARY KEY,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  end_reason    TEXT,
  turn_count    INTEGER NOT NULL DEFAULT 0,
  raw_path      TEXT NOT NULL,
  cost_usd      TEXT NOT NULL DEFAULT '0',
  tokens_in     INTEGER NOT NULL DEFAULT 0,
  tokens_out    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(ended_at) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS session_checkpoints (
  session_id     TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  seq            INTEGER NOT NULL,
  created_at     TEXT NOT NULL,
  last_turn_id   TEXT NOT NULL,
  turn_count     INTEGER NOT NULL,
  history_digest TEXT,
  PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS records (
  id                TEXT PRIMARY KEY,
  schema_version    INTEGER NOT NULL,
  kind              TEXT NOT NULL CHECK (kind IN ('fact','correction','summary','doc_chunk')),
  key               TEXT,
  value             TEXT NOT NULL,
  status            TEXT NOT NULL CHECK (status IN ('candidate','confirmed','superseded','deleted')),
  source_session_id TEXT,
  source_turn_id    TEXT,
  source_kind       TEXT NOT NULL CHECK (source_kind IN ('user_explicit','summarizer','import')),
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  expires_at        TEXT,
  sensitivity       TEXT NOT NULL DEFAULT 'normal'
                      CHECK (sensitivity IN ('normal','sensitive','secret')),
  supersedes        TEXT REFERENCES records(id),
  tags              TEXT NOT NULL DEFAULT '[]',
  deleted_at        TEXT,
  delete_reason     TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_key_live
  ON records(key, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_records_kind_status
  ON records(kind, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_records_key_confirmed
  ON records(key) WHERE status = 'confirmed' AND key IS NOT NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
  value,
  key,
  tags,
  content='records',
  content_rowid='rowid',
  tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS trg_records_ai AFTER INSERT ON records BEGIN
  INSERT INTO records_fts(rowid, value, key, tags)
  SELECT new.rowid, new.value, COALESCE(new.key,''), new.tags
  WHERE new.status NOT IN ('deleted','superseded');
END;
CREATE TRIGGER IF NOT EXISTS trg_records_ad AFTER DELETE ON records BEGIN
  INSERT INTO records_fts(records_fts, rowid, value, key, tags)
  SELECT 'delete', old.rowid, old.value, COALESCE(old.key,''), old.tags
  WHERE old.status NOT IN ('deleted','superseded');
END;
CREATE TRIGGER IF NOT EXISTS trg_records_au AFTER UPDATE ON records BEGIN
  INSERT INTO records_fts(records_fts, rowid, value, key, tags)
  SELECT 'delete', old.rowid, old.value, COALESCE(old.key,''), old.tags
  WHERE old.status NOT IN ('deleted','superseded');
  INSERT INTO records_fts(rowid, value, key, tags)
  SELECT new.rowid, new.value, COALESCE(new.key,''), new.tags
  WHERE new.status NOT IN ('deleted','superseded');
END;

CREATE TABLE IF NOT EXISTS embeddings (
  record_id  TEXT PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
  model      TEXT NOT NULL,
  dim        INTEGER NOT NULL,
  vector     BLOB NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trg_records_embedding_cleanup
AFTER UPDATE OF status ON records
WHEN new.status IN ('deleted','superseded') BEGIN
  DELETE FROM embeddings WHERE record_id = new.id;
END;

CREATE TABLE IF NOT EXISTS documents (
  doc_id         TEXT PRIMARY KEY,
  path           TEXT NOT NULL UNIQUE,
  content_hash   TEXT NOT NULL,
  transfer_class TEXT NOT NULL DEFAULT 'local_only'
                   CHECK (transfer_class IN ('local_only','api_allowed')),
  indexed_at     TEXT NOT NULL,
  bytes          INTEGER NOT NULL,
  chunk_count    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_chunks (
  chunk_id   TEXT PRIMARY KEY,
  doc_id     TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL,
  text       TEXT NOT NULL,
  start_char INTEGER NOT NULL,
  end_char   INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(
  text, content='doc_chunks', content_rowid='rowid', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS trg_doc_chunks_ai AFTER INSERT ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS trg_doc_chunks_ad AFTER DELETE ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, text)
  VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS trg_doc_chunks_au AFTER UPDATE ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, text)
  VALUES ('delete', old.rowid, old.text);
  INSERT INTO doc_chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TABLE IF NOT EXISTS tasks (
  task_id     TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES sessions(session_id),
  request_id  TEXT NOT NULL,
  goal        TEXT NOT NULL,
  state       TEXT NOT NULL CHECK (state IN ('pending','running','succeeded','failed','cancelled')),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  max_steps   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS task_steps (
  task_id         TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
  step_no         INTEGER NOT NULL,
  tool_name       TEXT NOT NULL,
  args_hash       TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  state           TEXT NOT NULL CHECK (state IN ('pending','running','succeeded','failed','cancelled')),
  result_summary  TEXT,
  changed_paths   TEXT NOT NULL DEFAULT '[]',
  started_at      TEXT,
  finished_at     TEXT,
  PRIMARY KEY (task_id, step_no)
);

CREATE TABLE IF NOT EXISTS approvals (
  ticket_id   TEXT PRIMARY KEY,
  request_id  TEXT NOT NULL,
  tool_name   TEXT NOT NULL,
  args_hash   TEXT NOT NULL,
  risk        TEXT NOT NULL,
  channel     TEXT NOT NULL,
  method      TEXT NOT NULL,
  granted_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS budget_usage (
  service     TEXT NOT NULL CHECK (service IN ('llm','search','online_tts')),
  period_kind TEXT NOT NULL CHECK (period_kind IN ('day','month')),
  period_key  TEXT NOT NULL,
  cost_usd    TEXT NOT NULL DEFAULT '0',
  tokens_in   INTEGER NOT NULL DEFAULT 0,
  tokens_out  INTEGER NOT NULL DEFAULT 0,
  requests    INTEGER NOT NULL DEFAULT 0,
  warned_at   TEXT,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (service, period_kind, period_key)
);

CREATE TABLE IF NOT EXISTS metrics (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  metric     TEXT NOT NULL,
  value_ms   INTEGER,
  value_num  REAL,
  labels     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_metrics_metric_ts ON metrics(metric, ts);
