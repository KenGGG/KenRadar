-- Frozen SQLite V2 baseline. Reviewed against PG 0018; no PG migrations run here.
CREATE TABLE platform (
    id           INTEGER PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    display_name TEXT,
    enabled      INTEGER DEFAULT 1,
    config_json  TEXT DEFAULT '{}' CHECK (config_json IS NULL OR json_valid(config_json)),
    created_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE TABLE creator (
    id              INTEGER PRIMARY KEY,
    platform_id     INTEGER NOT NULL REFERENCES platform(id),
    platform_uid    TEXT NOT NULL,
    nickname        TEXT,
    profile_url     TEXT,
    avatar_url      TEXT,
    enabled         INTEGER DEFAULT 1,
    check_modes     TEXT DEFAULT 'post',
    last_check_at   TEXT,
    last_content_id TEXT,
    extra           TEXT DEFAULT '{}' CHECK (extra IS NULL OR json_valid(extra)),
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE(platform_id, platform_uid)
);

CREATE TABLE content_item (
    id              INTEGER PRIMARY KEY,
    platform_id     INTEGER NOT NULL REFERENCES platform(id),
    content_id      TEXT NOT NULL,
    creator_id      INTEGER NOT NULL REFERENCES creator(id),
    content_type    TEXT DEFAULT 'video',
    title           TEXT,
    description     TEXT,
    publish_time    TEXT,
    duration        INTEGER,
    source_url      TEXT,
    media_url       TEXT,
    cover_url       TEXT,
    local_path      TEXT,
    download_status TEXT DEFAULT 'pending',
    extra           TEXT DEFAULT '{}' CHECK (extra IS NULL OR json_valid(extra)),
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    status TEXT NOT NULL DEFAULT 'discovered',
    discovery_source TEXT NOT NULL DEFAULT 'monitor',
    discovered_at TEXT,
    review_status TEXT NOT NULL DEFAULT 'none',
    current_error_code TEXT NOT NULL DEFAULT '',
    current_error_message TEXT NOT NULL DEFAULT '',
    media_sha256 TEXT,
    media_size_bytes INTEGER,
    media_deleted_at TEXT,
    UNIQUE(platform_id, content_id)
);

CREATE TABLE transcript (
    id               INTEGER PRIMARY KEY,
    content_item_id  INTEGER NOT NULL REFERENCES content_item(id),
    aweme_id         TEXT,
    text_content     TEXT,
    segments_json    TEXT CHECK (segments_json IS NULL OR json_valid(segments_json)),
    text_path        TEXT,
    json_path        TEXT,
    model            TEXT DEFAULT 'large-v3-turbo',
    language         TEXT,
    status           TEXT DEFAULT 'pending',
    error_message    TEXT,
    duration_seconds REAL,
    created_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    source_type TEXT NOT NULL DEFAULT 'funasr',
    quality_score REAL,
    quality_details TEXT CHECK (quality_details IS NULL OR json_valid(quality_details)),
    input_sha256 TEXT,
    completed_at TEXT,
    UNIQUE(content_item_id)
);

CREATE TABLE ai_analysis (
    id              INTEGER PRIMARY KEY,
    content_item_id INTEGER NOT NULL REFERENCES content_item(id),
    analysis_type   TEXT DEFAULT 'summary',
    result_json     TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
    result_text     TEXT,
    model           TEXT,
    provider        TEXT,
    prompt_hash     TEXT,
    status          TEXT DEFAULT 'pending',
    error_message   TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    profile_name TEXT NOT NULL DEFAULT 'default',
    user_instruction TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    transcript_hash TEXT,
    result_hash TEXT,
    completed_at TEXT,
    UNIQUE(content_item_id, analysis_type)
);

CREATE TABLE content_note (
    id              INTEGER PRIMARY KEY,
    content_item_id INTEGER NOT NULL REFERENCES content_item(id),
    note_type       TEXT DEFAULT 'content',
    note_path       TEXT NOT NULL,
    title           TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    content_sha256 TEXT,
    analysis_result_hash TEXT,
    rendered_at TEXT,
    UNIQUE(content_item_id, note_type)
);

CREATE TABLE content_curation (
    content_item_id    INTEGER PRIMARY KEY REFERENCES content_item(id),
    favorite           INTEGER DEFAULT 0,
    topic_pool_status  TEXT DEFAULT '',
    research_status    TEXT DEFAULT '',
    user_note          TEXT,
    created_at         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE TABLE push_log (
    id              INTEGER PRIMARY KEY,
    content_item_id INTEGER REFERENCES content_item(id),
    aweme_id        TEXT,
    batch_id        TEXT,
    channel         TEXT DEFAULT 'feishu',
    message_type    TEXT,
    status          TEXT,
    error_message   TEXT,
    pushed_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    idempotency_key TEXT,
    research_job_id INTEGER REFERENCES research_job(id) ON DELETE SET NULL,
    target_url TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE TABLE alert_log (
    id              INTEGER PRIMARY KEY,
    level           TEXT NOT NULL,
    component       TEXT NOT NULL,
    content_item_id INTEGER REFERENCES content_item(id),
    aweme_id        TEXT,
    title           TEXT,
    message         TEXT NOT NULL,
    context         TEXT CHECK (context IS NULL OR json_valid(context)),
    notified        INTEGER DEFAULT 0,
    fingerprint     TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at   TEXT,
    last_seen_at    TEXT,
    aggregation_window_started_at TEXT,
    last_notified_at TEXT,
    resolved_at     TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE TABLE research_job (
    id              INTEGER PRIMARY KEY,
    platform_id     INTEGER REFERENCES platform(id),
    creator_id      INTEGER REFERENCES creator(id),
    creator_name    TEXT,
    platform        TEXT DEFAULT 'douyin',
    blogger_id      INTEGER,
    blogger_name    TEXT,
    status          TEXT DEFAULT 'pending',
    total_count     INTEGER DEFAULT 0,
    pending_count   INTEGER DEFAULT 0,
    success_count   INTEGER DEFAULT 0,
    failed_count    INTEGER DEFAULT 0,
    skipped_count   INTEGER DEFAULT 0,
    limit_count     INTEGER DEFAULT 0,
    since_time      TEXT,
    until_time      TEXT,
    push_enabled    INTEGER DEFAULT 0,
    force_enabled   INTEGER DEFAULT 0,
    started_at      TEXT,
    finished_at     TEXT,
    last_error      TEXT,
    report_path     TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    scan_scope TEXT NOT NULL DEFAULT 'recent',
    history_capability TEXT NOT NULL DEFAULT 'unknown',
    source_subscription_id INTEGER REFERENCES source_subscription(id) ON DELETE SET NULL,
    external_content_id TEXT,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    confirmed_count INTEGER NOT NULL DEFAULT 0,
    confirm_status TEXT NOT NULL DEFAULT 'pending',
    confirmed_by TEXT,
    confirmed_at TEXT,
    CHECK (scan_scope IN ('recent','full')),
    CHECK (confirm_status IN ('pending','confirmed','rejected','executed'))
);

CREATE TABLE research_job_item (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES research_job(id),
    content_item_id INTEGER REFERENCES content_item(id),
    aweme_id        TEXT,
    status          TEXT DEFAULT 'pending',
    error_message   TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    external_content_id TEXT,
    published_at TEXT,
    title TEXT,
    url TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(job_id, aweme_id),
    CHECK (review_status IN ('pending','approved','rejected'))
);

CREATE TABLE task_run (
    id               INTEGER PRIMARY KEY,
    task_type        TEXT NOT NULL,
    payload_json     TEXT DEFAULT '{}' CHECK (payload_json IS NULL OR json_valid(payload_json)),
    message          TEXT,
    requested_by     TEXT DEFAULT 'web',
    worker_name      TEXT DEFAULT '',
    priority         INTEGER DEFAULT 50,
    idempotency_key  TEXT,
    status           TEXT DEFAULT 'queued',
    progress_json    TEXT DEFAULT '{}' CHECK (progress_json IS NULL OR json_valid(progress_json)),
    stats_json       TEXT DEFAULT '{}' CHECK (stats_json IS NULL OR json_valid(stats_json)),
    available_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    lease_expires_at TEXT,
    heartbeat_at     TEXT,
    cancel_requested_at TEXT,
    attempt          INTEGER DEFAULT 0,
    max_attempts     INTEGER DEFAULT 3,
    started_at       TEXT,
    finished_at      TEXT,
    last_error       TEXT,
    created_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    pause_requested_at TEXT,
    paused_at TEXT,
    resumed_at TEXT,
    error_code TEXT,
    checkpoint_json TEXT NOT NULL DEFAULT '{}' CHECK (checkpoint_json IS NULL OR json_valid(checkpoint_json)),
    parent_task_run_id INTEGER REFERENCES task_run(id),
    lease_token TEXT,
    config_revision TEXT,
    CHECK (status IN ('queued','running','retry_wait','paused','success','failed','cancelled'))
);

CREATE TABLE task_attempt (
    id            INTEGER PRIMARY KEY,
    task_run_id   INTEGER NOT NULL REFERENCES task_run(id) ON DELETE CASCADE,
    attempt_no    INTEGER NOT NULL,
    worker_name   TEXT,
    provider      TEXT,
    status        TEXT NOT NULL,
    error_code    TEXT,
    error_message TEXT,
    started_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    finished_at   TEXT,
    lease_token TEXT,
    UNIQUE(task_run_id, attempt_no)
);

CREATE TABLE task_step (
    id               INTEGER PRIMARY KEY,
    task_run_id      INTEGER REFERENCES task_run(id),
    content_item_id  INTEGER,
    stage            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    input_version    TEXT,
    output_ref       TEXT DEFAULT '{}' CHECK (output_ref IS NULL OR json_valid(output_ref)),
    priority         INTEGER DEFAULT 50,
    available_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    locked_by        TEXT,
    locked_at        TEXT,
    lease_expires_at TEXT,
    heartbeat_at     TEXT,
    attempt          INTEGER DEFAULT 0,
    max_attempts     INTEGER DEFAULT 3,
    error_code       TEXT,
    error_message    TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    created_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    lease_token TEXT,
    UNIQUE(content_item_id, stage, input_version),
    FOREIGN KEY(content_item_id) REFERENCES content_item(id),
    CHECK (status IN ('pending','running','retry_wait','success','failed','cancelled','paused')),
    CHECK (attempt >= 0 AND max_attempts >= 1)
);

CREATE TABLE state_transition (
    id          INTEGER PRIMARY KEY,
    object_type TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    reason      TEXT,
    actor       TEXT,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE TABLE artifact (
    id              INTEGER PRIMARY KEY,
    content_item_id INTEGER REFERENCES content_item(id),
    task_run_id     INTEGER REFERENCES task_run(id),
    kind            TEXT NOT NULL,
    path            TEXT NOT NULL,
    size_bytes      INTEGER,
    sha256          TEXT,
    status          TEXT DEFAULT 'active',
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE(kind, path)
);

CREATE TABLE outbox_event (
    id              INTEGER PRIMARY KEY,
    event_type      TEXT NOT NULL,
    aggregate_type  TEXT,
    aggregate_id    TEXT,
    idempotency_key TEXT,
    payload_json    TEXT DEFAULT '{}' CHECK (payload_json IS NULL OR json_valid(payload_json)),
    status          TEXT DEFAULT 'pending',
    available_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    attempt         INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 5,
    last_error      TEXT,
    locked_by       TEXT,
    lease_expires_at TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    processed_at    TEXT,
    locked_at TEXT,
    lease_token TEXT,
    CHECK (status IN ('pending','running','success','failed','unknown','paused')),
    CHECK (attempt >= 0 AND max_attempts >= 1)
);

CREATE TABLE resource_lease (
    resource_key    TEXT PRIMARY KEY,
    owner           TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    metadata_json   TEXT DEFAULT '{}' CHECK (metadata_json IS NULL OR json_valid(metadata_json)),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE TABLE source_subscription (
    id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platform(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    source_url TEXT,
    feed_url TEXT,
    category TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    check_interval_minutes INTEGER,
    last_checked_at TEXT,
    last_item_published_at TEXT,
    last_error TEXT,
    extra TEXT NOT NULL DEFAULT '{}' CHECK (extra IS NULL OR json_valid(extra)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    status TEXT NOT NULL DEFAULT 'active',
    is_priority INTEGER NOT NULL DEFAULT 0,
    next_check_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    default_analysis_profile TEXT,
    default_instruction TEXT,
    auto_publish INTEGER NOT NULL DEFAULT 1,
    review_required INTEGER NOT NULL DEFAULT 0,
    notify_mode TEXT NOT NULL DEFAULT 'on_success',
    media_retention_policy TEXT NOT NULL DEFAULT 'after_success',
    media_retention_days INTEGER,
    history_capability TEXT NOT NULL DEFAULT 'unknown',
    last_scan_scope TEXT,
    UNIQUE(platform_id, source_key)
);

CREATE TABLE source_daily_metrics (
    id                  INTEGER PRIMARY KEY,
    source_id           INTEGER NOT NULL
                REFERENCES source_subscription(id) ON DELETE CASCADE,
    metric_date         TEXT NOT NULL,
    total_content       INTEGER NOT NULL DEFAULT 0,
    rated_count         INTEGER NOT NULL DEFAULT 0,
    high_value_count    INTEGER NOT NULL DEFAULT 0,
    avg_rating          REAL,
    push_count          INTEGER NOT NULL DEFAULT 0,
    review_count        INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    calculation_version TEXT NOT NULL DEFAULT 'v1',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE (source_id, metric_date)
);

CREATE TABLE source_topic_metrics (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES source_subscription(id) ON DELETE CASCADE,
    metric_date TEXT NOT NULL,
    topic TEXT NOT NULL,
    content_count INTEGER NOT NULL DEFAULT 0,
    content_ratio REAL,
    taxonomy_version TEXT NOT NULL DEFAULT 'v1',
    model_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE (source_id, metric_date, topic, taxonomy_version)
);

CREATE TABLE publication_log (
    id INTEGER PRIMARY KEY,
    content_item_id INTEGER NOT NULL REFERENCES content_item(id),
    source_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'running',
    target_url TEXT,
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    completed_at TEXT
);

CREATE TABLE transcript_revision (
    id INTEGER PRIMARY KEY,
    content_item_id INTEGER NOT NULL REFERENCES content_item(id),
    text_content TEXT NOT NULL,
    record_json TEXT NOT NULL CHECK (record_json IS NULL OR json_valid(record_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

CREATE INDEX IF NOT EXISTS idx_creator_platform_uid ON creator(platform_id, platform_uid);
CREATE INDEX IF NOT EXISTS idx_content_item_content_id ON content_item(platform_id, content_id);
CREATE INDEX IF NOT EXISTS idx_content_item_creator ON content_item(creator_id);
CREATE INDEX IF NOT EXISTS idx_content_item_publish ON content_item(publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_transcript_content ON transcript(content_item_id);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_content ON ai_analysis(content_item_id, analysis_type);
CREATE INDEX IF NOT EXISTS idx_push_log_pushed ON push_log(pushed_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_log_created ON alert_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_job_status ON research_job(status);
CREATE INDEX IF NOT EXISTS idx_research_job_item_job ON research_job_item(job_id);
CREATE INDEX IF NOT EXISTS idx_task_run_status_created ON task_run(status, priority DESC, available_at, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_run_idempotency
    ON task_run(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_task_attempt_run ON task_attempt(task_run_id, attempt_no);
CREATE INDEX IF NOT EXISTS idx_state_transition_object ON state_transition(object_type, object_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_content ON artifact(content_item_id, kind);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_event(status, available_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_idempotency
    ON outbox_event(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_task_step_stage_status
            ON task_step(stage, status, priority DESC, available_at, created_at)
;
CREATE INDEX IF NOT EXISTS idx_source_subscription_platform_enabled
            ON source_subscription(platform_id, enabled)
;
CREATE INDEX IF NOT EXISTS idx_source_daily_metrics_date
            ON source_daily_metrics(metric_date)
;
CREATE INDEX IF NOT EXISTS idx_source_daily_metrics_source_date
            ON source_daily_metrics(source_id, metric_date DESC)
;
CREATE INDEX IF NOT EXISTS idx_source_topic_metrics_source_date ON source_topic_metrics(source_id, metric_date DESC);
CREATE INDEX IF NOT EXISTS idx_push_log_aweme ON push_log(aweme_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_aweme ON alert_log(aweme_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_notified ON alert_log(notified);
CREATE INDEX IF NOT EXISTS idx_research_job_item_aweme ON research_job_item(aweme_id);
CREATE INDEX IF NOT EXISTS idx_task_step_claim ON task_step(stage, status, available_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_step_null_version
    ON task_step(content_item_id, stage) WHERE input_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_log_active_fingerprint ON alert_log(fingerprint) WHERE fingerprint IS NOT NULL AND resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_alert_log_active_last_seen ON alert_log(last_seen_at DESC) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_task_run_lease_expiry ON task_run(lease_expires_at) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_task_run_paused ON task_run(paused_at DESC) WHERE status = 'paused';
CREATE INDEX IF NOT EXISTS idx_task_attempt_status ON task_attempt(status);
CREATE INDEX IF NOT EXISTS idx_content_item_current_error ON content_item(current_error_code) WHERE current_error_code <> '';
CREATE INDEX IF NOT EXISTS idx_source_subscription_due ON source_subscription(next_check_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_content_item_discovery ON content_item(discovery_source, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_job_subscription
            ON research_job(source_subscription_id)
;
CREATE INDEX IF NOT EXISTS idx_research_job_item_external
            ON research_job_item(job_id, external_content_id)
;
CREATE INDEX IF NOT EXISTS idx_publication_log_content ON publication_log(content_item_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_push_log_idempotency
            ON push_log(idempotency_key) WHERE idempotency_key IS NOT NULL
;
CREATE INDEX IF NOT EXISTS idx_transcript_revision_content ON transcript_revision(content_item_id,id);
