/**
 * Derived SQLite index over append-only JSONL.
 * JSONL remains the source of truth; this DB is rebuildable and disposable.
 */
import { DatabaseSync } from "node:sqlite";
import { existsSync, mkdirSync, unlinkSync } from "node:fs";
import { dirname } from "node:path";
import { readJsonl } from "../recorder.ts";
import { SCHEMA_VERSION, type ContextEvent } from "../schema.ts";

export const INDEX_SCHEMA_VERSION = 1 as const;

const DDL = `
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE events (
  event_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  request_id TEXT,
  attempt_id TEXT,
  producer_seq INTEGER NOT NULL,
  wall_time TEXT NOT NULL,
  observation TEXT NOT NULL,
  evidence TEXT NOT NULL,
  adapter_id TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  boundary TEXT NOT NULL,
  coverage TEXT NOT NULL,
  source_category TEXT,
  source_alias TEXT,
  source_key TEXT,
  content_version_key TEXT,
  usage_input_tokens INTEGER,
  usage_output_tokens INTEGER,
  usage_cached_tokens INTEGER,
  estimated_tokens INTEGER,
  dropped_events INTEGER,
  unsupported_boundary TEXT,
  notes TEXT,
  json TEXT NOT NULL
);
CREATE INDEX idx_events_session ON events(session_id);
CREATE INDEX idx_events_request ON events(session_id, request_id);
CREATE INDEX idx_events_source_version ON events(source_key, content_version_key);
CREATE INDEX idx_events_adapter ON events(adapter_id, boundary);
`;

export type RebuildStats = {
  jsonlPath: string;
  dbPath: string;
  eventCount: number;
  schemaVersion: typeof SCHEMA_VERSION;
  indexSchemaVersion: typeof INDEX_SCHEMA_VERSION;
};

export type EventQuery = {
  sessionId?: string;
  requestId?: string;
  sourceKey?: string;
  contentVersionKey?: string;
  adapterId?: string;
  observation?: string;
  limit?: number;
};

export class DerivedSqliteIndex {
  readonly dbPath: string;
  private db: DatabaseSync;

  constructor(dbPath: string) {
    this.dbPath = dbPath;
    mkdirSync(dirname(dbPath), { recursive: true });
    this.db = new DatabaseSync(dbPath);
  }

  close(): void {
    this.db.close();
  }

  /** Drop and rebuild from JSONL. Idempotent for the same JSONL contents. */
  rebuildFromJsonl(jsonlPath: string): RebuildStats {
    const events = readJsonl(jsonlPath);
    this.db.exec("PRAGMA journal_mode = WAL;");
    this.db.exec("DROP TABLE IF EXISTS events;");
    this.db.exec("DROP TABLE IF EXISTS meta;");
    this.db.exec(DDL);

    const insertMeta = this.db.prepare(
      "INSERT INTO meta(key, value) VALUES (?, ?)",
    );
    insertMeta.run("index_schema_version", String(INDEX_SCHEMA_VERSION));
    insertMeta.run("schema_version", SCHEMA_VERSION);
    insertMeta.run("jsonl_path", jsonlPath);
    insertMeta.run("rebuilt_at", new Date().toISOString());
    insertMeta.run("source_of_truth", "jsonl");

    const insert = this.db.prepare(`
      INSERT INTO events (
        event_id, session_id, agent_id, request_id, attempt_id, producer_seq,
        wall_time, observation, evidence, adapter_id, adapter_version, boundary,
        coverage, source_category, source_alias, source_key, content_version_key,
        usage_input_tokens, usage_output_tokens, usage_cached_tokens,
        estimated_tokens, dropped_events, unsupported_boundary, notes, json
      ) VALUES (
        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
      )
    `);

    this.db.exec("BEGIN");
    try {
      for (const e of events) {
        insert.run(
          e.eventId,
          e.sessionId,
          e.agentId,
          e.requestId,
          e.attemptId,
          e.producerSeq,
          e.wallTime,
          e.observation,
          e.evidence,
          e.adapterId,
          e.adapterVersion,
          e.boundary,
          e.coverage,
          e.sourceCategory,
          e.sourceAlias,
          e.sourceKey,
          e.contentVersionKey,
          e.usageInputTokens,
          e.usageOutputTokens,
          e.usageCachedTokens,
          e.estimatedTokens,
          e.droppedEvents,
          e.unsupportedBoundary,
          e.notes,
          JSON.stringify(e),
        );
      }
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }

    return {
      jsonlPath,
      dbPath: this.dbPath,
      eventCount: events.length,
      schemaVersion: SCHEMA_VERSION,
      indexSchemaVersion: INDEX_SCHEMA_VERSION,
    };
  }

  meta(key: string): string | null {
    const row = this.db
      .prepare("SELECT value FROM meta WHERE key = ?")
      .get(key) as { value: string } | undefined;
    return row?.value ?? null;
  }

  count(): number {
    const row = this.db.prepare("SELECT COUNT(*) AS n FROM events").get() as {
      n: number;
    };
    return row.n;
  }

  query(q: EventQuery = {}): ContextEvent[] {
    const clauses: string[] = [];
    const params: unknown[] = [];
    if (q.sessionId) {
      clauses.push("session_id = ?");
      params.push(q.sessionId);
    }
    if (q.requestId) {
      clauses.push("request_id = ?");
      params.push(q.requestId);
    }
    if (q.sourceKey) {
      clauses.push("source_key = ?");
      params.push(q.sourceKey);
    }
    if (q.contentVersionKey) {
      clauses.push("content_version_key = ?");
      params.push(q.contentVersionKey);
    }
    if (q.adapterId) {
      clauses.push("adapter_id = ?");
      params.push(q.adapterId);
    }
    if (q.observation) {
      clauses.push("observation = ?");
      params.push(q.observation);
    }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const limit = q.limit != null ? `LIMIT ${Number(q.limit)}` : "";
    const rows = this.db
      .prepare(
        `SELECT json FROM events ${where} ORDER BY producer_seq ASC ${limit}`,
      )
      .all(...params) as Array<{ json: string }>;
    return rows.map((r) => JSON.parse(r.json) as ContextEvent);
  }

  fingerprint(): string {
    const rows = this.db
      .prepare(
        "SELECT event_id, producer_seq, content_version_key FROM events ORDER BY producer_seq",
      )
      .all() as Array<{
      event_id: string;
      producer_seq: number;
      content_version_key: string | null;
    }>;
    return JSON.stringify(rows);
  }
}

/** Rebuild into a fresh file path (deletes existing db first). */
export function rebuildDerivedIndex(
  jsonlPath: string,
  dbPath: string,
): RebuildStats {
  if (existsSync(dbPath)) unlinkSync(dbPath);
  for (const suffix of ["-wal", "-shm"]) {
    const side = `${dbPath}${suffix}`;
    if (existsSync(side)) unlinkSync(side);
  }
  const index = new DerivedSqliteIndex(dbPath);
  try {
    return index.rebuildFromJsonl(jsonlPath);
  } finally {
    index.close();
  }
}
