/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

export interface VideoContent {
  id: string; // aweme_id
  title: string;
  brief_summary?: string;
  blogger: string;
  rating: number; // 1-10
  recommend_action: 'push' | 'skip' | 'review' | 'research' | 'archive' | '';
  status: 'completed' | 'failed' | 'processing' | 'queued';
  failed_at_step?: 'download' | 'transcribe' | 'ai' | 'push';
  failure_stage?: 'download' | 'transcribe' | 'ai' | 'push';
  failed_at?: string;
  error_message?: string;
  created_at: string;
  published_at?: string;
  collected_at?: string;
  updated_at?: string;
  duration: string;
  original_url: string;
  download_status?: string;
  transcript_status?: string;
  summary_status?: string;
  push_status?: string;
  summary_path?: string;
  current_stage?: string;
  pipeline_steps?: {
    key: 'download' | 'transcribe' | 'ai' | 'note' | 'push';
    label: string;
    state: string;
  }[];
  tags: string[];
  whisper_text: string;
  summary_markdown: string;
  one_sentence_conclusion?: string;
  importance_score?: number;
  novelty_score?: number;
  information_density?: number;
  business_relevance?: number;
  recommendation_reason?: string;
}

export interface ResearchTask {
  id: string;
  type: 'single' | 'blogger';
  target: string; // url, short code, or blogger handle
  status: 'completed' | 'failed' | 'processing' | 'queued' | 'paused';
  total_items?: number;
  completed_items?: number;
  failed_items?: number;
  skipped_items?: number;
  created_at: string;
  pipeline_stage?: 'downloading' | 'transcribing' | 'summarizing' | 'publishing' | 'pushing' | 'completed' | 'failed';
  pipeline_progress: number; // 0-100
  pipeline_stages?: {
    downloading: number;
    transcribing: number;
    ai: number;
    done: number;
    failed: number;
  };
  force_retry?: boolean;
}

export interface MonitorSource {
  id: string;
  name: string;
  url: string;
  category: string;
  status: 'enabled' | 'disabled';
  quality_score: number; // 0-100
  last_checked: string;
  total_captured: number;
  parse_success_rate: number; // percentage
  source_scope?: 'config' | 'database';
  source_label?: string;
  in_config?: boolean;
  monitor_enabled?: boolean;
  config_enabled?: boolean;
  can_toggle?: boolean;
  can_delete_config?: boolean;
}

export interface PushRecord {
  id: string;
  aweme_id: string;
  title: string;
  blogger: string;
  push_type: 'card' | 'text';
  sent_at: string;
  status: 'success' | 'failed';
  response_msg?: string;
  payload: string; // JSON or text preview
}

export interface SystemLog {
  id: string;
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  module: 'Scheduler' | 'Downloader' | 'Whisper' | 'AI' | 'Ollama' | 'Feishu' | 'WebUI';
  message: string;
}

export interface NoteFile {
  path: string;
  name: string;
  platform: string;
  blogger: string;
  title: string;
  updated_at: string;
  size_kb: number;
}

export interface BriefFile {
  path: string;
  name: string;
  title: string;
  created_at: string;
  item_count: number;
  status: string;
}

export interface LibraryStats {
  total_items: number;
  content_notes: number;
  transcripts: number;
  loaded_items: number;
  display_limit: number;
}

export interface SystemConfig {
  scheduler: {
    enabled: boolean;
    cronExpression: string; // e.g. "0 */2 * * *"
    grace_period_mins: number;
    max_concurrent_tasks: number;
    retry_times: number;
    max_items_per_blogger: number;
    manual_trigger_enabled: boolean;
  };
  whisper: {
    model: string;
    device: 'cpu' | 'cuda';
    threads: number;
    use_gpu: boolean;
    vram_offload_gb: number;
    staged_gpu_scheduling: boolean;
  };
  ai: {
    api_type: string;
    endpoint: string;
    model: string;
    provider_name: string;
    fallback_enabled: boolean;
    fallback_provider_name: string;
    fallback_endpoint: string;
    fallback_provider_model: string;
    fallback_model: string;
    temperature: number;
    top_p: number;
    top_k: number;
    timeout_sec: number;
    max_tokens: number;
    max_input_chars: number;
    keep_alive: string;
    no_think: boolean;
    compact_prompt: boolean;
    prompt_template: string;
  };
  download: {
    path: string;
    max_workers: number;
    batch_size: number;
    batch_cooldown_seconds: number;
    max_duration_seconds: number;
    retry_failed: boolean;
    circuit_breaker_failures: number;
    circuit_breaker_cooldown_seconds: number;
    save_json: boolean;
  };
  feishu: {
    webhook_url: string;
    message_type: 'auto' | 'card' | 'text';
    push_threshold_rating: number; // e.g. 7.5
    retry_attempts: number;
    card_max_items: number;
    card_theme: 'blue' | 'turquoise' | 'violet' | 'orange' | 'red';
  };
  security: {
    port: number;
    bind_ip: string;
    password_auth: boolean;
    web_password: string;
    access_token_ttl_hours: number;
  };
  publishing: {
    github_pages_enabled: boolean;
    github_pages_output_dir: string;
    github_pages_public_base_url: string;
    github_pages_public_base_url_configured: boolean;
    github_sync_enabled: boolean;
    github_sync_repo_dir: string;
    github_sync_branch: string;
    github_sync_auto_commit: boolean;
    github_sync_auto_push: boolean;
    github_sync_include_html_docs: boolean;
    github_sync_include_markdown_notes: boolean;
    github_sync_include_briefs: boolean;
    github_sync_include_transcripts: boolean;
  };
}

export interface AlertRecord {
  id: string;
  title: string;
  desc: string;
  time: string;
  level: 'critical' | 'warn';
  module: string;
}

export interface SystemInfo {
  port: number;
  gpu_label: string;
  gpu_status: string;
  gpu_percent: number | null;
  whisper_model: string;
  log_path: string;
  health: Record<string, string | number>;
  publishing?: {
    docs_exists: boolean;
    docs_path: string;
    latest_html_published_at: string;
    github_pages_enabled: boolean;
    github_pages_public_base_url_configured: boolean;
    github_sync_enabled: boolean;
    github_sync_auto_commit: boolean;
    github_sync_auto_push: boolean;
    last_sync?: {
      ok?: boolean;
      message?: string;
      synced_at?: string;
      files?: string[];
    };
  };
  background_task?: {
    running: boolean;
    message: string;
    started_at: string | null;
    finished_at: string | null;
    status: string;
    requested_by?: string;
    queue?: {
      position: number;
      task_id: string;
      message: string;
      queued_at: string;
      requested_by?: string;
      run_id?: number;
    }[];
    progress?: {
      total: number;
      current: number;
      aweme_id: string;
      stage: string;
      message: string;
    };
  };
}
