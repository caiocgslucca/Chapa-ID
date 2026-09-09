import sqlite3
import re
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "chapa_id.sqlite3"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def connect():
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        address TEXT NOT NULL,
        family TEXT,
        thickness TEXT,
        color TEXT,
        manufacturer TEXT,
        source TEXT,
        source_url TEXT,
        source_image_url TEXT,
        source_synced_at TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
    CREATE INDEX IF NOT EXISTS idx_products_description ON products(description);
    CREATE INDEX IF NOT EXISTS idx_products_address ON products(address);

    CREATE TABLE IF NOT EXISTS product_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        media_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        feature_json TEXT,
        source TEXT,
        source_url TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id)
    );
    CREATE INDEX IF NOT EXISTS idx_product_media_product ON product_media(product_id);

    CREATE TABLE IF NOT EXISTS identifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_file TEXT NOT NULL,
        suggested_sku TEXT,
        confirmed_sku TEXT,
        score REAL,
        status TEXT,
        printed INTEGER NOT NULL DEFAULT 0,
        operator TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_identifications_created ON identifications(created_at);

    CREATE TABLE IF NOT EXISTS catalog_sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        status TEXT NOT NULL,
        products_found INTEGER NOT NULL DEFAULT 0,
        products_updated INTEGER NOT NULL DEFAULT 0,
        images_downloaded INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        message TEXT,
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT
    );

    CREATE TABLE IF NOT EXISTS catalog_sync_errors (
        source_url TEXT PRIMARY KEY,
        sku TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 1,
        last_error TEXT,
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_catalog_sync_errors_status ON catalog_sync_errors(status);

    CREATE TABLE IF NOT EXISTS catalog_site_items (
        site_key TEXT PRIMARY KEY,
        source_url TEXT NOT NULL,
        sku TEXT,
        description TEXT,
        image_url TEXT,
        status TEXT NOT NULL DEFAULT 'resolved',
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_synced_at TEXT,
        last_error TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_catalog_site_items_sku ON catalog_site_items(sku);
    CREATE INDEX IF NOT EXISTS idx_catalog_site_items_status ON catalog_site_items(status);

    CREATE TABLE IF NOT EXISTS ai_settings (
        id INTEGER PRIMARY KEY CHECK (id=1),
        enabled INTEGER NOT NULL DEFAULT 0,
        provider TEXT NOT NULL DEFAULT 'gemini',
        model TEXT NOT NULL DEFAULT 'gemini-3.1-flash-lite',
        api_key TEXT,
        mode TEXT NOT NULL DEFAULT 'hybrid',
        min_local_confidence REAL NOT NULL DEFAULT 72,
        audit_below REAL NOT NULL DEFAULT 92,
        max_candidates INTEGER NOT NULL DEFAULT 5,
        learning_enabled INTEGER NOT NULL DEFAULT 1,
        custom_instruction TEXT NOT NULL DEFAULT '',
        max_ai_calls_per_identification INTEGER NOT NULL DEFAULT 1,
        ai_timeout_seconds INTEGER NOT NULL DEFAULT 25,
        require_ai_on_ambiguous INTEGER NOT NULL DEFAULT 1,
        last_test_at TEXT,
        last_test_ok INTEGER,
        last_test_message TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    INSERT OR IGNORE INTO ai_settings(id) VALUES(1);

    CREATE TABLE IF NOT EXISTS learning_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identification_id INTEGER,
        suggested_sku TEXT,
        confirmed_sku TEXT,
        event_type TEXT NOT NULL,
        confidence REAL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_learning_events_created ON learning_events(created_at);

    CREATE TABLE IF NOT EXISTS ai_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identification_id INTEGER,
        provider TEXT,
        model TEXT,
        local_top_sku TEXT,
        local_score REAL,
        ai_selected_sku TEXT,
        ai_confidence REAL,
        outcome TEXT NOT NULL,
        latency_ms REAL,
        details TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_ai_audit_logs_created ON ai_audit_logs(created_at);

    CREATE TABLE IF NOT EXISTS system_check_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        score REAL NOT NULL,
        blockers INTEGER NOT NULL DEFAULT 0,
        warnings INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS industrial_scan_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operator TEXT,
        regions_captured INTEGER NOT NULL DEFAULT 0,
        regions_used INTEGER NOT NULL DEFAULT 0,
        color_stability REAL,
        visual_diversity REAL,
        consensus_sku TEXT,
        consensus_confidence REAL,
        decision_mode TEXT,
        payload_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_industrial_scan_created ON industrial_scan_sessions(created_at);

    CREATE TABLE IF NOT EXISTS learning_quarantine (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identification_id INTEGER,
        sku TEXT NOT NULL,
        query_file TEXT,
        event_type TEXT NOT NULL DEFAULT 'confirmation',
        validation_status TEXT NOT NULL DEFAULT 'pending',
        consistency_score REAL,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_learning_quarantine_status ON learning_quarantine(validation_status);

    CREATE TABLE IF NOT EXISTS visual_equivalence_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_key TEXT NOT NULL,
        sku TEXT NOT NULL,
        reason TEXT,
        confidence REAL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(group_key, sku)
    );
    CREATE INDEX IF NOT EXISTS idx_visual_equivalence_group ON visual_equivalence_groups(group_key);
    """)

    # Migrações compatíveis com bases já existentes.
    def add_column(table, name, ddl):
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    add_column("products", "source", "TEXT")
    add_column("products", "source_url", "TEXT")
    add_column("products", "source_image_url", "TEXT")
    add_column("products", "source_synced_at", "TEXT")
    add_column("product_media", "source", "TEXT")
    add_column("product_media", "source_url", "TEXT")
    add_column("ai_settings", "max_ai_calls_per_identification", "INTEGER NOT NULL DEFAULT 1")
    add_column("ai_settings", "ai_timeout_seconds", "INTEGER NOT NULL DEFAULT 25")
    add_column("ai_settings", "require_ai_on_ambiguous", "INTEGER NOT NULL DEFAULT 1")
    add_column("ai_settings", "last_test_at", "TEXT")
    add_column("ai_settings", "last_test_ok", "INTEGER")
    add_column("ai_settings", "last_test_message", "TEXT")
    # V6: pré-mapeia famílias visualmente equivalentes por descrição técnica.
    # É apenas um agrupamento de candidatos (não confirma SKU): remove dimensões,
    # espessura e quantidade de faces para encontrar variantes do mesmo padrão.
    try:
        rows=con.execute("SELECT sku,description FROM products WHERE active=1").fetchall()
        groups={}
        for r in rows:
            text=unicodedata.normalize("NFKD",str(r["description"] or "")).encode("ascii","ignore").decode("ascii").lower()
            text=re.sub(r"\b\d+(?:[.,]\d+)?\s*mm\b"," ",text)
            text=re.sub(r"\b\d{3,4}\s*x\s*\d{3,4}\s*mm\b"," ",text)
            text=re.sub(r"\b[12]\s*faces?\b|\b1\s*face\s*branca\b"," ",text)
            text=re.sub(r"\bultra\s+premium\b|\bstandard\b"," ",text)
            text=re.sub(r"[^a-z0-9]+"," ",text).strip()
            key=" ".join(text.split()[:10])
            if len(key)>=8: groups.setdefault(key,[]).append(str(r["sku"]))
        for key,skus in groups.items():
            if len(skus)<2: continue
            for sku in skus:
                con.execute("INSERT OR IGNORE INTO visual_equivalence_groups(group_key,sku,reason,confidence) VALUES(?,?,?,?)",(key,sku,"descrição técnica normalizada; requer confirmação visual",70.0))
    except Exception:
        pass

    con.commit()
    con.close()
