"""Pydantic models for the three Jarvis YAML configuration files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Ratio = Annotated[float, Field(ge=0, le=1)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3.5:9b"
OLLAMA_MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
OLLAMA_CONTEXT_TOKENS = 16_384

Risk = Literal["low", "medium", "high"]
ExecutionMode = Literal["in_process", "detached_allowlisted", "managed_process"]
Capability = Literal["net_http", "fs_read", "fs_write", "proc_spawn"]
MemoryKind = Literal["correction", "fact", "summary", "doc_chunk"]
SensitiveKind = Literal["secret", "pii_high", "pii", "pii_low"]


class StrictModel(BaseModel):
    """Reject every key that is not part of the documented schema.

    ``extra="forbid"`` is the config contract: a typo in YAML must fail startup
    instead of being silently ignored.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class VersionedModel(StrictModel):
    schema_version: Literal[1]


class AppSettings(StrictModel):
    language: NonEmptyString
    timezone: NonEmptyString


class PathSettings(StrictModel):
    data_root: Path
    memory_db: Path
    raw_dir: Path
    export_dir: Path
    docs_dir: Path
    notes_dir: Path
    skills_dir: Path
    state_dir: Path
    logs_dir: Path
    models_dir: Path
    backups_dir: Path


class ContextSettings(StrictModel):
    max_input_tokens: PositiveInt
    reserve_output_tokens: PositiveInt
    memory_share: Ratio
    history_share: Ratio
    keep_recent_turns: NonNegativeInt

    @model_validator(mode="after")
    def shares_fit_context(self) -> Self:
        if self.memory_share + self.history_share > 1:
            raise ValueError("memory_share와 history_share의 합은 1.0 이하여야 합니다")
        return self


class ModelPricing(StrictModel):
    input_per_1k: NonNegativeDecimal
    output_per_1k: NonNegativeDecimal


class LLMSettings(StrictModel):
    provider: Literal["ollama"]
    base_url: Literal["http://127.0.0.1:11434"]
    local_only: Literal[True]
    model: Literal["qwen3.5:9b"]
    model_digest: Sha256Hex
    runtime_context_tokens: Literal[16384]
    think: Literal[False]
    temperature: Annotated[float, Field(ge=0, le=2)]
    max_output_tokens: PositiveInt
    timeout_s: PositiveFloat
    max_retries: NonNegativeInt
    backoff_base_s: PositiveFloat
    backoff_max_s: PositiveFloat
    retry_on: list[Literal["timeout", "connection_error", "server_error"]]
    context: ContextSettings
    pricing: dict[str, ModelPricing]

    @model_validator(mode="after")
    def selected_model_has_pricing(self) -> Self:
        if self.model_digest != OLLAMA_MODEL_DIGEST:
            raise ValueError("llm.model_digest가 D005 결정과 일치해야 합니다")
        if self.model not in self.pricing:
            raise ValueError("선택한 llm.model의 pricing 항목이 필요합니다")
        selected_pricing = self.pricing[self.model]
        if selected_pricing.input_per_1k != 0 or selected_pricing.output_per_1k != 0:
            raise ValueError("로컬 Ollama 모델의 외부 호출 단가는 0이어야 합니다")
        if self.backoff_max_s < self.backoff_base_s:
            raise ValueError("backoff_max_s는 backoff_base_s 이상이어야 합니다")
        if self.max_output_tokens > self.context.reserve_output_tokens:
            raise ValueError("max_output_tokens는 reserve_output_tokens 이하여야 합니다")
        if (
            self.context.max_input_tokens + self.context.reserve_output_tokens
            > self.runtime_context_tokens
        ):
            raise ValueError("입력·출력 토큰 한도가 Ollama 런타임 문맥을 초과합니다")
        if len(self.retry_on) != len(set(self.retry_on)):
            raise ValueError("llm.retry_on 값은 중복될 수 없습니다")
        return self


class BudgetSettings(StrictModel):
    currency: NonEmptyString
    daily_limit: PositiveDecimal
    monthly_limit: PositiveDecimal
    warn_ratio: Annotated[float, Field(gt=0, le=1)]
    on_exceed: Literal["block_new_requests"]


class RetrievalSettings(StrictModel):
    top_k: PositiveInt
    min_score: Ratio
    include_candidates: bool
    max_candidates: NonNegativeInt
    kind_weights: dict[MemoryKind, NonNegativeFloat]
    half_life_days: dict[MemoryKind, PositiveInt]
    fts_weight: Ratio
    embedding_weight: Ratio


class EmbeddingSettings(StrictModel):
    enabled: bool
    provider: Literal["local", "api"]
    model: str
    dim: NonNegativeInt


class MemorySettings(StrictModel):
    retrieval: RetrievalSettings
    key_aliases: dict[str, list[str]]
    checkpoint_every_turns: PositiveInt
    summarize_on_exit: bool
    quota_gb: PositiveFloat
    quota_warn_ratio: Annotated[float, Field(gt=0, le=1)]
    embedding: EmbeddingSettings


class FetchSettings(StrictModel):
    max_bytes: PositiveInt
    max_redirects: NonNegativeInt
    timeout_s: PositiveFloat
    allowed_content_types: list[NonEmptyString]


class SearchSettings(StrictModel):
    provider: NonEmptyString
    max_results: PositiveInt
    require_min_sources: PositiveInt
    cost_per_request: NonNegativeDecimal


class RagSettings(StrictModel):
    chunk_chars: PositiveInt
    chunk_overlap_chars: NonNegativeInt
    max_chunks_per_answer: PositiveInt
    max_file_bytes: PositiveInt
    supported_extensions: list[NonEmptyString]
    fetch: FetchSettings
    search: SearchSettings

    @model_validator(mode="after")
    def chunk_overlap_is_smaller(self) -> Self:
        if self.chunk_overlap_chars >= self.chunk_chars:
            raise ValueError("chunk_overlap_chars는 chunk_chars보다 작아야 합니다")
        return self


class AgentSettings(StrictModel):
    max_steps: PositiveInt
    max_tool_calls_per_step: PositiveInt
    step_timeout_s: PositiveFloat
    total_timeout_s: PositiveFloat
    auto_retry_idempotent: NonNegativeInt


class SessionSettings(StrictModel):
    recovery: Literal["prompt", "auto", "discard"]
    idle_timeout_min: PositiveInt


class LoggingSettings(StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    fsync_events: bool
    rotate_daily: bool
    keep_days: PositiveInt
    mask_in_logs: bool


class MetricsSettings(StrictModel):
    enabled: bool
    p95_window: PositiveInt


class WakeSTTSettings(StrictModel):
    engine: Literal["vosk"]
    model: Literal["vosk-model-small-ko-0.22"]
    model_archive_sha256: Sha256Hex


class CommandSTTSettings(StrictModel):
    engine: Literal["faster-whisper"]
    model: Literal["faster-whisper-small"]
    model_revision: NonEmptyString
    model_sha256: Sha256Hex
    device: Literal["cuda", "cpu"]
    compute_type: Literal["int8_float16", "int8"]
    cpu_fallback: bool
    cpu_compute_type: Literal["int8"]
    beam_size: PositiveInt
    vad_filter: bool
    initial_prompt: NonEmptyString
    pre_roll_ms: PositiveInt
    speech_threshold_dbfs: Annotated[float, Field(ge=-96, le=0)]
    trailing_silence_ms: PositiveInt
    min_speech_ms: PositiveInt
    min_avg_logprob: Annotated[float, Field(ge=-10, le=0)]
    max_no_speech_probability: Ratio


class STTSettings(StrictModel):
    engine: Literal["hybrid"]
    device: NonEmptyString
    sample_rate_hz: Literal[16000]
    language: Literal["ko"]
    max_command_seconds: PositiveFloat
    wake: WakeSTTSettings
    command: CommandSTTSettings


class TTSSettings(StrictModel):
    engine: Literal["disabled", "edge-tts", "local"]
    voice: str
    rate: Annotated[int, Field(ge=-10, le=10)]
    max_chars: PositiveInt
    cost_per_1k_chars: NonNegativeDecimal


class BargeInSettings(StrictModel):
    enabled: bool
    speech_threshold_dbfs: Annotated[float, Field(ge=-96, le=0)]
    min_onset_rise_db: Annotated[float, Field(ge=0, le=96)]
    baseline_window_ms: PositiveInt
    startup_guard_ms: PositiveInt
    recent_speech_ms: PositiveInt
    pre_roll_ms: PositiveInt
    vad_mode: Literal[0, 1, 2, 3]
    vad_frame_ms: Literal[10, 20, 30]
    vad_min_voiced_ratio: Annotated[float, Field(gt=0, le=1)]
    interrupt_hotkey_enabled: bool
    interrupt_hotkey: NonEmptyString


class VoiceSettings(StrictModel):
    enabled: bool
    mode: Literal["wake_word"]
    wake_word: NonEmptyString
    acknowledgement: NonEmptyString
    stt: STTSettings
    barge_in: BargeInSettings
    tts: TTSSettings
    push_to_talk_hotkey: NonEmptyString

    @model_validator(mode="after")
    def enabled_voice_is_fully_local(self) -> Self:
        if self.enabled and self.tts.engine != "local":
            raise ValueError("활성화된 음성 모드는 로컬 TTS만 사용할 수 있습니다")
        return self


class UISettings(StrictModel):
    tray_enabled: bool
    hotkey: NonEmptyString
    autostart: bool
    show_mic_indicator: bool


class Settings(VersionedModel):
    dev_mode: bool
    app: AppSettings
    paths: PathSettings
    llm: LLMSettings
    budget: BudgetSettings
    memory: MemorySettings
    rag: RagSettings
    agent: AgentSettings
    session: SessionSettings
    logging: LoggingSettings
    metrics: MetricsSettings
    voice: VoiceSettings
    ui: UISettings


class ApprovalPolicy(StrictModel):
    ticket_ttl_s: PositiveInt
    typed_confirm_phrase: NonEmptyString
    voice_max_risk: Risk


class ToolLimits(StrictModel):
    max_arg_len: PositiveInt
    max_args_bytes: PositiveInt
    max_output_bytes: PositiveInt
    max_concurrent_tools: PositiveInt
    default_timeout_s: PositiveFloat
    deny_child_processes: bool
    env_allowlist: list[NonEmptyString]


class SandboxPolicy(StrictModel):
    write_roots: list[Path]
    read_roots: list[Path]
    roots: dict[str, Path]
    deny_paths: list[str]
    follow_reparse_points: bool
    deny_unc_paths: bool
    deny_device_paths: bool
    forbidden_write_extensions: list[NonEmptyString]
    allowed_write_extensions: list[NonEmptyString]


class NetworkPolicy(StrictModel):
    allowed_schemes: list[Literal["http", "https"]]
    deny_loopback: bool
    deny_private_ranges: bool
    deny_credentials_in_url: bool
    deny_mixed_script_idn: bool
    url_allowlist: list[NonEmptyString]


class SkillRegistration(StrictModel):
    skill_name: NonEmptyString
    path: Path
    sha256: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
    capabilities: list[Capability]


class ToolDefinition(StrictModel):
    name: NonEmptyString
    enabled: bool
    phase: Annotated[int, Field(ge=0, le=8)]
    risk: Risk
    capabilities: list[Capability]
    execution_mode: ExecutionMode
    idempotent: bool
    untrusted_output: bool
    timeout_s: PositiveFloat
    description: NonEmptyString
    risk_escalation: dict[str, Risk] | None = None
    app_map: dict[str, Path] | None = None
    allow_args: bool | None = None
    allowed_roots: list[str] | None = None
    max_content_bytes: PositiveInt | None = None
    require_manifest: bool | None = None
    require_hash_match: bool | None = None
    require_text_channel: bool | None = None
    registry: list[SkillRegistration] | None = None

    @model_validator(mode="after")
    def execution_contract_is_safe(self) -> Self:
        if self.name == "open_app" and (
            self.execution_mode != "detached_allowlisted" or not self.app_map
        ):
            raise ValueError("open_app은 detached_allowlisted와 app_map이 필요합니다")
        if self.name == "close_app" and not self.app_map:
            raise ValueError("close_app은 app_map이 필요합니다")
        if self.name == "run_skill" and self.execution_mode != "managed_process":
            raise ValueError("run_skill은 managed_process여야 합니다")
        return self


class ForbiddenAction(StrictModel):
    id: NonEmptyString
    reason: NonEmptyString


class ToolPolicy(VersionedModel):
    default: Literal["deny"]
    approval: ApprovalPolicy
    limits: ToolLimits
    sandbox: SandboxPolicy
    network: NetworkPolicy
    tools: list[ToolDefinition]
    forbidden: list[ForbiddenAction]

    @model_validator(mode="after")
    def names_are_unique(self) -> Self:
        tool_names = [tool.name for tool in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("도구 이름은 중복될 수 없습니다")
        forbidden_ids = [item.id for item in self.forbidden]
        if len(forbidden_ids) != len(set(forbidden_ids)):
            raise ValueError("금지 동작 ID는 중복될 수 없습니다")
        return self


class ApiServices(StrictModel):
    llm: bool
    search_query: bool
    online_tts: bool


class TransmissionAllow(StrictModel):
    memory_kinds: list[Literal["fact", "correction", "summary"]]
    allow_candidates: bool
    max_sensitivity: Literal["normal", "sensitive"]
    current_turn: bool
    history: bool


class DocumentClassRule(StrictModel):
    match: NonEmptyString
    classification: Literal["local_only", "api_allowed"] = Field(alias="class")


class DocumentPolicy(StrictModel):
    default_class: Literal["local_only", "api_allowed"]
    class_rules: list[DocumentClassRule]
    allow_local_only_excerpt: bool


class ApiTransmissionPolicy(StrictModel):
    default: Literal["deny"]
    services: ApiServices
    allow: TransmissionAllow
    documents: DocumentPolicy
    on_block: Literal["ask_user", "deny", "local_only"]
    never_send_actions: list[Literal["block"]]


class DetectorPolicy(StrictModel):
    id: NonEmptyString
    label: NonEmptyString
    pattern: NonEmptyString
    action: Literal["mask", "block"]
    kind: SensitiveKind

    @field_validator("pattern")
    @classmethod
    def pattern_compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError("detector 정규식이 올바르지 않습니다") from error
        return pattern


class MaskPolicy(StrictModel):
    replacement: NonEmptyString
    keep_tail: dict[str, NonNegativeInt]


class ApiOutputPolicy(StrictModel):
    apply_detectors: Literal["all"]
    on_block: Literal["inherit"]
    purposes: list[Literal["llm", "search_query", "online_tts"]]


class LogOutputPolicy(StrictModel):
    apply_detectors: Literal["all"]
    exempt_fields: list[NonEmptyString]
    mask_all_secret_kinds: bool


class TTSOutputPolicy(StrictModel):
    apply_detectors: Literal["all"]
    refuse_kinds: list[SensitiveKind]
    mask_kinds: list[SensitiveKind]
    max_chars: PositiveInt
    fallback_text: NonEmptyString


class MemoryWriteOutputPolicy(StrictModel):
    apply_detectors: Literal["all"]
    refuse_kinds: list[SensitiveKind]
    mark_sensitive_kinds: list[SensitiveKind]


class OutputPolicies(StrictModel):
    api: ApiOutputPolicy
    logs: LogOutputPolicy
    tts: TTSOutputPolicy
    memory_write: MemoryWriteOutputPolicy


class RetentionPolicy(StrictModel):
    raw_days: PositiveInt
    raw_on_expire: Literal["delete", "compress"]
    events_days: PositiveInt
    audit_days: PositiveInt
    metrics_days: PositiveInt
    run_on_startup: bool


class DeletionPolicy(StrictModel):
    leave_tombstone: bool
    purge_from_backups: Literal["on_next_full_backup"]


class BackupPolicy(StrictModel):
    enabled: bool
    staging_dir: Path
    target: NonEmptyString
    encryption: Literal["aes256", "age"]
    passphrase_source: Literal["keyring"]
    schedule: Literal["daily", "weekly", "monthly"]
    keep_copies: PositiveInt
    restore_test_interval: Literal["monthly"]
    include: list[Path]
    exclude: list[Path]


class PrivacyPolicy(VersionedModel):
    api_transmission: ApiTransmissionPolicy
    detectors: list[DetectorPolicy]
    mask: MaskPolicy
    outputs: OutputPolicies
    retention: RetentionPolicy
    deletion: DeletionPolicy
    backup: BackupPolicy

    @model_validator(mode="after")
    def required_privacy_guards_exist(self) -> Self:
        if not any(detector.kind == "secret" for detector in self.detectors):
            raise ValueError("secret 종류 detector가 하나 이상 필요합니다")
        if not self.outputs.memory_write.refuse_kinds:
            raise ValueError("memory_write.refuse_kinds는 비어 있을 수 없습니다")
        return self


@dataclass(frozen=True, slots=True)
class Policies:
    tools: ToolPolicy
    privacy: PrivacyPolicy


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    settings: Settings
    policies: Policies
    config_hash: str
