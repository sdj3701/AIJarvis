# 파이썬 공부 | scripts/app/config/models.py
# Pydantic으로 설정 데이터의 형태와 허용 범위를 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Pydantic models for the three Jarvis YAML configuration files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 오른쪽 식을 계산한 값을 PositiveInt에 대입합니다.
PositiveInt = Annotated[int, Field(gt=0)]
# 오른쪽 식을 계산한 값을 NonNegativeInt에 대입합니다.
NonNegativeInt = Annotated[int, Field(ge=0)]
# 오른쪽 식을 계산한 값을 PositiveFloat에 대입합니다.
PositiveFloat = Annotated[float, Field(gt=0)]
# 오른쪽 식을 계산한 값을 NonNegativeFloat에 대입합니다.
NonNegativeFloat = Annotated[float, Field(ge=0)]
# 오른쪽 식을 계산한 값을 Ratio에 대입합니다.
Ratio = Annotated[float, Field(ge=0, le=1)]
# 오른쪽 식을 계산한 값을 PositiveDecimal에 대입합니다.
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
# 오른쪽 식을 계산한 값을 NonNegativeDecimal에 대입합니다.
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
# 오른쪽 식을 계산한 값을 NonEmptyString에 대입합니다.
NonEmptyString = Annotated[str, Field(min_length=1)]
# 오른쪽 식을 계산한 값을 Sha256Hex에 대입합니다.
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

# OLLAMA_BASE_URL에 문자열을 대입합니다.
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
# OLLAMA_MODEL에 문자열을 대입합니다.
OLLAMA_MODEL = "qwen3.5:9b"
# OLLAMA_MODEL_DIGEST에 문자열을 대입합니다.
OLLAMA_MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
# OLLAMA_CONTEXT_TOKENS에 숫자 등 고정된 값을 대입합니다.
OLLAMA_CONTEXT_TOKENS = 16_384

# 오른쪽 식을 계산한 값을 Risk에 대입합니다.
Risk = Literal["low", "medium", "high"]
# 오른쪽 식을 계산한 값을 ExecutionMode에 대입합니다.
ExecutionMode = Literal["in_process", "detached_allowlisted", "managed_process"]
# 오른쪽 식을 계산한 값을 Capability에 대입합니다.
Capability = Literal["net_http", "fs_read", "fs_write", "proc_spawn", "proc_terminate"]
# 오른쪽 식을 계산한 값을 MemoryKind에 대입합니다.
MemoryKind = Literal["correction", "fact", "summary", "doc_chunk"]
# 오른쪽 식을 계산한 값을 SensitiveKind에 대입합니다.
SensitiveKind = Literal["secret", "pii_high", "pii", "pii_low"]


# StrictModel: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: BaseModel.
class StrictModel(BaseModel):
    """Reject every key that is not part of the documented schema.

    ``extra="forbid"`` is the config contract: a typo in YAML must fail startup
    instead of being silently ignored.
    """

    # ConfigDict()의 반환값을 model_config에 대입합니다.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


# VersionedModel: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class VersionedModel(StrictModel):
    # schema_version: Literal[1] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    schema_version: Literal[1]


# AppSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class AppSettings(StrictModel):
    # language: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    language: NonEmptyString
    # timezone: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    timezone: NonEmptyString


# PathSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class PathSettings(StrictModel):
    # data_root: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    data_root: Path
    # memory_db: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    memory_db: Path
    # raw_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    raw_dir: Path
    # export_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    export_dir: Path
    # docs_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    docs_dir: Path
    # notes_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    notes_dir: Path
    # skills_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    skills_dir: Path
    # state_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    state_dir: Path
    # logs_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    logs_dir: Path
    # models_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    models_dir: Path
    # backups_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    backups_dir: Path


# ContextSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ContextSettings(StrictModel):
    # max_input_tokens: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_input_tokens: PositiveInt
    # reserve_output_tokens: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    reserve_output_tokens: PositiveInt
    # memory_share: Ratio 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    memory_share: Ratio
    # history_share: Ratio 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    history_share: Ratio
    # keep_recent_turns: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    keep_recent_turns: NonNegativeInt

    # shares_fit_context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def shares_fit_context(self) -> Self:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.memory_share + self.history_share
        # > 1.
        if self.memory_share + self.history_share > 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("memory_share와 history_share의 합은 1.0 이하여야 합니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# 오른쪽 식을 계산한 값을 LLMContextSettings에 대입합니다.
LLMContextSettings = ContextSettings


# ModelPricing: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ModelPricing(StrictModel):
    # input_per_1k: NonNegativeDecimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    input_per_1k: NonNegativeDecimal
    # output_per_1k: NonNegativeDecimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    output_per_1k: NonNegativeDecimal


# LLMSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class LLMSettings(StrictModel):
    # provider: Literal['ollama'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    provider: Literal["ollama"]
    # base_url: Literal['http://127.0.0.1:11434'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    base_url: Literal["http://127.0.0.1:11434"]
    # local_only: Literal[True] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    local_only: Literal[True]
    # model: Literal['qwen3.5:9b'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    model: Literal["qwen3.5:9b"]
    # model_digest: Sha256Hex 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    model_digest: Sha256Hex
    # runtime_context_tokens: Literal[16384] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    runtime_context_tokens: Literal[16384]
    # think: Literal[False] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    think: Literal[False]
    # native_tool_calling_enabled을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    native_tool_calling_enabled: bool = False
    # temperature: Annotated[float, Field(ge=0, le=2)] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    temperature: Annotated[float, Field(ge=0, le=2)]
    # max_output_tokens: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_output_tokens: PositiveInt
    # timeout_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    timeout_s: PositiveFloat
    # max_retries: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_retries: NonNegativeInt
    # backoff_base_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    backoff_base_s: PositiveFloat
    # backoff_max_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    backoff_max_s: PositiveFloat
    # retry_on: list[Literal['timeout', 'connection_error', 'server_error']] 타입을 기대하는
    # 필드입니다. 이
    # 줄만으로 값이 대입되지는 않습니다.
    retry_on: list[Literal["timeout", "connection_error", "server_error"]]
    # context: ContextSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    context: ContextSettings
    # pricing: dict[str, ModelPricing] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    pricing: dict[str, ModelPricing]

    # selected_model_has_pricing(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def selected_model_has_pricing(self) -> Self:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.model_digest !=
        # OLLAMA_MODEL_DIGEST.
        if self.model_digest != OLLAMA_MODEL_DIGEST:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("llm.model_digest가 D005 결정과 일치해야 합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.model not in self.pricing.
        if self.model not in self.pricing:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("선택한 llm.model의 pricing 항목이 필요합니다")
        # 오른쪽 식을 계산한 값을 selected_pricing에 대입합니다.
        selected_pricing = self.pricing[self.model]
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if selected_pricing.input_per_1k != 0 or selected_pricing.output_per_1k != 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("로컬 Ollama 모델의 외부 호출 단가는 0이어야 합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.backoff_max_s <
        # self.backoff_base_s.
        if self.backoff_max_s < self.backoff_base_s:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("backoff_max_s는 backoff_base_s 이상이어야 합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.max_output_tokens >
        # self.context.reserve_output_tokens.
        if self.max_output_tokens > self.context.reserve_output_tokens:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("max_output_tokens는 reserve_output_tokens 이하여야 합니다")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (
            self.context.max_input_tokens + self.context.reserve_output_tokens
            > self.runtime_context_tokens
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("입력·출력 토큰 한도가 Ollama 런타임 문맥을 초과합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(self.retry_on) !=
        # len(set(self.retry_on)).
        if len(self.retry_on) != len(set(self.retry_on)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("llm.retry_on 값은 중복될 수 없습니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# BudgetSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class BudgetSettings(StrictModel):
    # currency: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    currency: NonEmptyString
    # daily_limit: PositiveDecimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    daily_limit: PositiveDecimal
    # monthly_limit: PositiveDecimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    monthly_limit: PositiveDecimal
    # warn_ratio: Annotated[float, Field(gt=0, le=1)] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    warn_ratio: Annotated[float, Field(gt=0, le=1)]
    # on_exceed: Literal['block_new_requests'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    on_exceed: Literal["block_new_requests"]


# RetrievalSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class RetrievalSettings(StrictModel):
    # top_k: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    top_k: PositiveInt
    # min_score: Ratio 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    min_score: Ratio
    # include_candidates: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    include_candidates: bool
    # max_candidates: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_candidates: NonNegativeInt
    # kind_weights: dict[MemoryKind, NonNegativeFloat] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    kind_weights: dict[MemoryKind, NonNegativeFloat]
    # half_life_days: dict[MemoryKind, PositiveInt] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    half_life_days: dict[MemoryKind, PositiveInt]
    # fts_weight: Ratio 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    fts_weight: Ratio
    # embedding_weight: Ratio 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    embedding_weight: Ratio


# EmbeddingSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class EmbeddingSettings(StrictModel):
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # provider: Literal['local', 'api'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    provider: Literal["local", "api"]
    # model: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    model: str
    # dim: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    dim: NonNegativeInt


# MemorySettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class MemorySettings(StrictModel):
    # retrieval: RetrievalSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    retrieval: RetrievalSettings
    # key_aliases: dict[str, list[str]] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    key_aliases: dict[str, list[str]]
    # checkpoint_every_turns: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    checkpoint_every_turns: PositiveInt
    # summarize_on_exit: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    summarize_on_exit: bool
    # quota_gb: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    quota_gb: PositiveFloat
    # quota_warn_ratio: Annotated[float, Field(gt=0, le=1)] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이 대입되지는 않습니다.
    quota_warn_ratio: Annotated[float, Field(gt=0, le=1)]
    # embedding: EmbeddingSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    embedding: EmbeddingSettings


# FetchSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class FetchSettings(StrictModel):
    # max_bytes: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_bytes: PositiveInt
    # max_redirects: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_redirects: NonNegativeInt
    # timeout_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    timeout_s: PositiveFloat
    # allowed_content_types: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    allowed_content_types: list[NonEmptyString]


# SearchSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class SearchSettings(StrictModel):
    # provider: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    provider: NonEmptyString
    # max_results: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_results: PositiveInt
    # require_min_sources: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    require_min_sources: PositiveInt
    # cost_per_request: NonNegativeDecimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    cost_per_request: NonNegativeDecimal


# RagSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class SemanticSettings(StrictModel):
    """Local learned embeddings and a persistent sqlite-vec index."""

    enabled: bool = True
    model: Literal["embeddinggemma"] = "embeddinggemma"
    timeout_s: PositiveFloat = 30
    conversations_enabled: bool = True
    conversation_top_k: Annotated[int, Field(ge=1, le=20)] = 3
    conversation_context_chars: Annotated[int, Field(ge=200, le=12000)] = 2400
    retention_days: PositiveInt = 90
    min_similarity: Annotated[float, Field(ge=-1, le=1)] = 0.3


class RerankSettings(StrictModel):
    """Local multilingual Cross-Encoder; no network inference or automatic download."""

    enabled: bool = True
    candidate_count: Annotated[int, Field(ge=2, le=100)] = 24
    batch_size: Annotated[int, Field(ge=1, le=16)] = 4
    max_length: Annotated[int, Field(ge=64, le=512)] = 512
    cpu_threads: Annotated[int, Field(ge=1, le=16)] = 2
    timeout_s: PositiveFloat = 10


class RagSettings(StrictModel):
    pdf_max_pages: Annotated[int, Field(ge=1, le=5000)] = 300
    pdf_max_characters: Annotated[int, Field(ge=1000, le=20_000_000)] = 2_000_000
    chunk_max_tokens: Annotated[int, Field(ge=64, le=1500)] = 384
    chunk_overlap_tokens: Annotated[int, Field(ge=0, le=256)] = 48
    refresh_interval_s: Annotated[float, Field(ge=0, le=3600)] = 5.0
    max_chunks_per_document: Annotated[int, Field(ge=1, le=20)] = 6
    max_structured_chunks: Annotated[int, Field(ge=1, le=32)] = 16
    neighbor_chunks: Annotated[int, Field(ge=0, le=2)] = 1
    rerank: RerankSettings = Field(default_factory=RerankSettings)
    semantic: SemanticSettings = Field(default_factory=SemanticSettings)
    # chunk_chars: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chunk_chars: PositiveInt
    # chunk_overlap_chars: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    chunk_overlap_chars: NonNegativeInt
    # max_chunks_per_answer: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_chunks_per_answer: PositiveInt
    # max_file_bytes: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_file_bytes: PositiveInt
    # supported_extensions: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    supported_extensions: list[NonEmptyString]
    # rrf_k에 숫자 등 고정된 값을 대입합니다.
    rrf_k: PositiveInt = 60
    # fetch: FetchSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    fetch: FetchSettings
    # search: SearchSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    search: SearchSettings

    # chunk_overlap_is_smaller(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def chunk_overlap_is_smaller(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_overlap_tokens must be below chunk_max_tokens")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.chunk_overlap_chars >=
        # self.chunk_chars.
        if self.chunk_overlap_chars >= self.chunk_chars:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("chunk_overlap_chars는 chunk_chars보다 작아야 합니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# AgentSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class AgentSettings(StrictModel):
    # max_steps: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_steps: PositiveInt
    # max_tool_calls_per_step: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_tool_calls_per_step: PositiveInt
    # step_timeout_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    step_timeout_s: PositiveFloat
    # total_timeout_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    total_timeout_s: PositiveFloat
    # auto_retry_idempotent: NonNegativeInt 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    auto_retry_idempotent: NonNegativeInt


# SessionSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class SessionSettings(StrictModel):
    # recovery: Literal['prompt', 'auto', 'discard'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    recovery: Literal["prompt", "auto", "discard"]
    # idle_timeout_min: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    idle_timeout_min: PositiveInt


# LoggingSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class LoggingSettings(StrictModel):
    # level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] 타입을 기대하는 필드입니다.
    # 이 줄만으로 값이
    # 대입되지는 않습니다.
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    # fsync_events: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    fsync_events: bool
    # rotate_daily: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    rotate_daily: bool
    # keep_days: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    keep_days: PositiveInt
    # mask_in_logs: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    mask_in_logs: bool


# MetricsSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class MetricsSettings(StrictModel):
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # p95_window: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    p95_window: PositiveInt


# WakeSTTSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class WakeSTTSettings(StrictModel):
    # engine: Literal['vosk'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    engine: Literal["vosk"]
    # model: Literal['vosk-model-small-ko-0.22'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    model: Literal["vosk-model-small-ko-0.22"]
    # model_archive_sha256: Sha256Hex 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    model_archive_sha256: Sha256Hex


# CommandSTTSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class CommandSTTSettings(StrictModel):
    # engine: Literal['faster-whisper'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    engine: Literal["faster-whisper"]
    # model: Literal['faster-whisper-small'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    model: Literal["faster-whisper-small"]
    # model_revision: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    model_revision: NonEmptyString
    # model_sha256: Sha256Hex 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    model_sha256: Sha256Hex
    # device: Literal['cuda', 'cpu'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    device: Literal["cuda", "cpu"]
    # compute_type: Literal['int8_float16', 'int8'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    compute_type: Literal["int8_float16", "int8"]
    # cpu_fallback: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    cpu_fallback: bool
    # cpu_compute_type: Literal['int8'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    cpu_compute_type: Literal["int8"]
    # beam_size: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    beam_size: PositiveInt
    # vad_filter: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    vad_filter: bool
    # initial_prompt: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    initial_prompt: NonEmptyString
    # pre_roll_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pre_roll_ms: PositiveInt
    # speech_threshold_dbfs: Annotated[float, Field(ge=-96, le=0)] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이
    # 대입되지는 않습니다.
    speech_threshold_dbfs: Annotated[float, Field(ge=-96, le=0)]
    # trailing_silence_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    trailing_silence_ms: PositiveInt
    # min_speech_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    min_speech_ms: PositiveInt
    # min_avg_logprob: Annotated[float, Field(ge=-10, le=0)] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이 대입되지는
    # 않습니다.
    min_avg_logprob: Annotated[float, Field(ge=-10, le=0)]
    # max_no_speech_probability: Ratio 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_no_speech_probability: Ratio


# STTSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class STTSettings(StrictModel):
    # engine: Literal['hybrid'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    engine: Literal["hybrid"]
    # device: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    device: NonEmptyString
    # sample_rate_hz: Literal[16000] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    sample_rate_hz: Literal[16000]
    # language: Literal['ko'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    language: Literal["ko"]
    # max_command_seconds: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_command_seconds: PositiveFloat
    # wake: WakeSTTSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    wake: WakeSTTSettings
    # command: CommandSTTSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    command: CommandSTTSettings


# TTSSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class TTSSettings(StrictModel):
    # engine: Literal['disabled', 'edge-tts', 'local'] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    engine: Literal["disabled", "edge-tts", "local"]
    # voice: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    voice: str
    # rate: Annotated[int, Field(ge=-10, le=10)] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    rate: Annotated[int, Field(ge=-10, le=10)]
    # max_chars: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_chars: PositiveInt
    # cost_per_1k_chars: NonNegativeDecimal 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    cost_per_1k_chars: NonNegativeDecimal


# BargeInSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class BargeInSettings(StrictModel):
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # speech_threshold_dbfs: Annotated[float, Field(ge=-96, le=0)] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이
    # 대입되지는 않습니다.
    speech_threshold_dbfs: Annotated[float, Field(ge=-96, le=0)]
    # min_onset_rise_db: Annotated[float, Field(ge=0, le=96)] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이 대입되지는
    # 않습니다.
    min_onset_rise_db: Annotated[float, Field(ge=0, le=96)]
    # baseline_window_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    baseline_window_ms: PositiveInt
    # startup_guard_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    startup_guard_ms: PositiveInt
    # recent_speech_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    recent_speech_ms: PositiveInt
    # pre_roll_ms: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pre_roll_ms: PositiveInt
    # vad_mode: Literal[0, 1, 2, 3] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    vad_mode: Literal[0, 1, 2, 3]
    # vad_frame_ms: Literal[10, 20, 30] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    vad_frame_ms: Literal[10, 20, 30]
    # vad_min_voiced_ratio: Annotated[float, Field(gt=0, le=1)] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이 대입되지는
    # 않습니다.
    vad_min_voiced_ratio: Annotated[float, Field(gt=0, le=1)]
    # interrupt_hotkey_enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    interrupt_hotkey_enabled: bool
    # interrupt_hotkey: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    interrupt_hotkey: NonEmptyString


# VoiceSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class VoiceSettings(StrictModel):
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # mode: Literal['wake_word'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    mode: Literal["wake_word"]
    # wake_word: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    wake_word: NonEmptyString
    # acknowledgement: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    acknowledgement: NonEmptyString
    # stt: STTSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    stt: STTSettings
    # barge_in: BargeInSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    barge_in: BargeInSettings
    # tts: TTSSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tts: TTSSettings
    # push_to_talk_hotkey: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    push_to_talk_hotkey: NonEmptyString

    # enabled_voice_is_fully_local(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def enabled_voice_is_fully_local(self) -> Self:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.enabled and self.tts.engine !=
        # 'local'.
        if self.enabled and self.tts.engine != "local":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("활성화된 음성 모드는 로컬 TTS만 사용할 수 있습니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# UISettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class UISettings(StrictModel):
    # tray_enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    tray_enabled: bool
    # hotkey: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    hotkey: NonEmptyString
    # autostart: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    autostart: bool
    # show_mic_indicator: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    show_mic_indicator: bool


# CommandMemorySettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class CommandMemorySettings(StrictModel):
    # enabled을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    enabled: bool = False
    # embedding_model에 문자열을 대입합니다.
    embedding_model: Literal["embeddinggemma"] = "embeddinggemma"
    # similarity_threshold에 숫자 등 고정된 값을 대입합니다.
    similarity_threshold: Ratio = 0.60
    # timeout_s에 숫자 등 고정된 값을 대입합니다.
    timeout_s: PositiveFloat = 10
    # max_examples에 숫자 등 고정된 값을 대입합니다.
    max_examples: Annotated[int, Field(ge=1, le=10000)] = 2000


# Settings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: VersionedModel.
class Settings(VersionedModel):
    # Field()의 반환값을 command_memory에 대입합니다.
    command_memory: CommandMemorySettings = Field(default_factory=CommandMemorySettings)
    # dev_mode: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    dev_mode: bool
    # app: AppSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    app: AppSettings
    # paths: PathSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    paths: PathSettings
    # llm: LLMSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    llm: LLMSettings
    # budget: BudgetSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    budget: BudgetSettings
    # memory: MemorySettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    memory: MemorySettings
    # rag: RagSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    rag: RagSettings
    # agent: AgentSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    agent: AgentSettings
    # session: SessionSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session: SessionSettings
    # logging: LoggingSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    logging: LoggingSettings
    # metrics: MetricsSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    metrics: MetricsSettings
    # voice: VoiceSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    voice: VoiceSettings
    # ui: UISettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ui: UISettings


# ApprovalPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ApprovalPolicy(StrictModel):
    # ticket_ttl_s: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ticket_ttl_s: PositiveInt
    # typed_confirm_phrase: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    typed_confirm_phrase: NonEmptyString
    # voice_max_risk: Risk 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    voice_max_risk: Risk


# ToolLimits: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ToolLimits(StrictModel):
    # max_arg_len: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_arg_len: PositiveInt
    # max_args_bytes: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_args_bytes: PositiveInt
    # max_output_bytes: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_output_bytes: PositiveInt
    # max_concurrent_tools: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_concurrent_tools: PositiveInt
    # default_timeout_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    default_timeout_s: PositiveFloat
    # deny_child_processes: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_child_processes: bool
    # env_allowlist: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    env_allowlist: list[NonEmptyString]


# SandboxPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class SandboxPolicy(StrictModel):
    # write_roots: list[Path] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    write_roots: list[Path]
    # read_roots: list[Path] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    read_roots: list[Path]
    # roots: dict[str, Path] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    roots: dict[str, Path]
    # deny_paths: list[str] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    deny_paths: list[str]
    # follow_reparse_points: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    follow_reparse_points: bool
    # deny_unc_paths: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_unc_paths: bool
    # deny_device_paths: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_device_paths: bool
    # forbidden_write_extensions: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    forbidden_write_extensions: list[NonEmptyString]
    # allowed_write_extensions: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    allowed_write_extensions: list[NonEmptyString]


# NetworkPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class NetworkPolicy(StrictModel):
    # allowed_schemes: list[Literal['http', 'https']] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    allowed_schemes: list[Literal["http", "https"]]
    # deny_loopback: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_loopback: bool
    # deny_private_ranges: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_private_ranges: bool
    # deny_credentials_in_url: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    deny_credentials_in_url: bool
    # deny_mixed_script_idn: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_mixed_script_idn: bool
    # url_allowlist: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    url_allowlist: list[NonEmptyString]


# SkillRegistration: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class SkillRegistration(StrictModel):
    # skill_name: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    skill_name: NonEmptyString
    # path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    path: Path
    # sha256: Annotated[str, Field(pattern='^[0-9a-fA-F]{64}$')] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이 대입되지는
    # 않습니다.
    sha256: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
    # capabilities: list[Capability] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    capabilities: list[Capability]


# ToolDefinition: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ToolDefinition(StrictModel):
    # name: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: NonEmptyString
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # phase: Annotated[int, Field(ge=0, le=8)] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    phase: Annotated[int, Field(ge=0, le=8)]
    # risk: Risk 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    risk: Risk
    # capabilities: list[Capability] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    capabilities: list[Capability]
    # execution_mode: ExecutionMode 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    execution_mode: ExecutionMode
    # idempotent: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    idempotent: bool
    # untrusted_output: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    untrusted_output: bool
    # timeout_s: PositiveFloat 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    timeout_s: PositiveFloat
    # description: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    description: NonEmptyString
    # risk_escalation을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    risk_escalation: dict[str, Risk] | None = None
    # app_map을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    app_map: dict[str, Path] | None = None
    # dynamic_discovery_enabled을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    dynamic_discovery_enabled: bool = False
    # saved_permissions_enabled을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    saved_permissions_enabled: bool = True
    # catalog_ttl_s에 숫자 등 고정된 값을 대입합니다.
    catalog_ttl_s: PositiveFloat = 300
    # catalog_max_entries에 숫자 등 고정된 값을 대입합니다.
    catalog_max_entries: Annotated[int, Field(ge=1, le=2000)] = 2000
    # allow_args을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    allow_args: bool | None = None
    # allowed_roots을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    allowed_roots: list[str] | None = None
    # max_content_bytes을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    max_content_bytes: PositiveInt | None = None
    # require_manifest을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    require_manifest: bool | None = None
    # require_hash_match을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    require_hash_match: bool | None = None
    # require_text_channel을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    require_text_channel: bool | None = None
    # registry을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    registry: list[SkillRegistration] | None = None

    # execution_contract_is_safe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def execution_contract_is_safe(self) -> Self:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.name == "open_app" and (
            self.execution_mode != "detached_allowlisted"
            or not (self.app_map or self.dynamic_discovery_enabled)
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("open_app은 detached_allowlisted와 app_map이 필요합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.name == 'close_app' and (not
        # self.app_map).
        if self.name == "close_app" and not self.app_map:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("close_app은 app_map이 필요합니다")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.name == "run_skill" and self.execution_mode != "managed_process":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("run_skill은 managed_process여야 합니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# ForbiddenAction: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ForbiddenAction(StrictModel):
    # id: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    id: NonEmptyString
    # reason: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    reason: NonEmptyString


# ToolPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: VersionedModel.
class ToolPolicy(VersionedModel):
    # default: Literal['deny'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    default: Literal["deny"]
    # approval: ApprovalPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    approval: ApprovalPolicy
    # limits: ToolLimits 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    limits: ToolLimits
    # sandbox: SandboxPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sandbox: SandboxPolicy
    # network: NetworkPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    network: NetworkPolicy
    # tools: list[ToolDefinition] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    tools: list[ToolDefinition]
    # forbidden: list[ForbiddenAction] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    forbidden: list[ForbiddenAction]

    # names_are_unique(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def names_are_unique(self) -> Self:
        # 오른쪽 식을 계산한 값을 tool_names에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        tool_names = [tool.name for tool in self.tools]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(tool_names) !=
        # len(set(tool_names)).
        if len(tool_names) != len(set(tool_names)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("도구 이름은 중복될 수 없습니다")
        # 오른쪽 식을 계산한 값을 forbidden_ids에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        forbidden_ids = [item.id for item in self.forbidden]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(forbidden_ids) !=
        # len(set(forbidden_ids)).
        if len(forbidden_ids) != len(set(forbidden_ids)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("금지 동작 ID는 중복될 수 없습니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# ApiServices: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ApiServices(StrictModel):
    # llm: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    llm: bool
    # search_query: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    search_query: bool
    # online_tts: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    online_tts: bool


# TransmissionAllow: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class TransmissionAllow(StrictModel):
    # memory_kinds: list[Literal['fact', 'correction', 'summary']] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이
    # 대입되지는 않습니다.
    memory_kinds: list[Literal["fact", "correction", "summary"]]
    # allow_candidates: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    allow_candidates: bool
    # max_sensitivity: Literal['normal', 'sensitive'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    max_sensitivity: Literal["normal", "sensitive"]
    # current_turn: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    current_turn: bool
    # history: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    history: bool


# DocumentClassRule: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class DocumentClassRule(StrictModel):
    # match: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    match: NonEmptyString
    # Field()의 반환값을 classification에 대입합니다.
    classification: Literal["local_only", "api_allowed"] = Field(alias="class")


# DocumentPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class DocumentPolicy(StrictModel):
    # default_class: Literal['local_only', 'api_allowed'] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    default_class: Literal["local_only", "api_allowed"]
    # class_rules: list[DocumentClassRule] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    class_rules: list[DocumentClassRule]
    # allow_local_only_excerpt: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    allow_local_only_excerpt: bool


# ApiTransmissionPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ApiTransmissionPolicy(StrictModel):
    # default: Literal['deny'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    default: Literal["deny"]
    # services: ApiServices 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    services: ApiServices
    # allow: TransmissionAllow 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    allow: TransmissionAllow
    # documents: DocumentPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    documents: DocumentPolicy
    # on_block: Literal['ask_user', 'deny', 'local_only'] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    on_block: Literal["ask_user", "deny", "local_only"]
    # never_send_actions: list[Literal['block']] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    never_send_actions: list[Literal["block"]]


# DetectorPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class DetectorPolicy(StrictModel):
    # id: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    id: NonEmptyString
    # label: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    label: NonEmptyString
    # pattern: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pattern: NonEmptyString
    # action: Literal['mask', 'block'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    action: Literal["mask", "block"]
    # kind: SensitiveKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    kind: SensitiveKind

    # pattern_compiles(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # cls는 이 메서드를 호출한 클래스입니다.
    # 입력: pattern.
    # 반환 타입 힌트: 문자열(str).
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    # @classmethod: 객체 대신 클래스를 첫 인자로 받습니다.
    @field_validator("pattern")
    @classmethod
    def pattern_compiles(cls, pattern: str) -> str:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # re.compile()을 호출해 작업을 수행합니다.
            re.compile(pattern)
        # re.error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except re.error as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("detector 정규식이 올바르지 않습니다") from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return pattern


# MaskPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class MaskPolicy(StrictModel):
    # replacement: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    replacement: NonEmptyString
    # keep_tail: dict[str, NonNegativeInt] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    keep_tail: dict[str, NonNegativeInt]


# ApiOutputPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class ApiOutputPolicy(StrictModel):
    # apply_detectors: Literal['all'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    apply_detectors: Literal["all"]
    # on_block: Literal['inherit'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    on_block: Literal["inherit"]
    # purposes: list[Literal['llm', 'search_query', 'online_tts']] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이
    # 대입되지는 않습니다.
    purposes: list[Literal["llm", "search_query", "online_tts"]]


# LogOutputPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class LogOutputPolicy(StrictModel):
    # apply_detectors: Literal['all'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    apply_detectors: Literal["all"]
    # exempt_fields: list[NonEmptyString] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    exempt_fields: list[NonEmptyString]
    # mask_all_secret_kinds: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    mask_all_secret_kinds: bool


# TTSOutputPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class TTSOutputPolicy(StrictModel):
    # apply_detectors: Literal['all'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    apply_detectors: Literal["all"]
    # refuse_kinds: list[SensitiveKind] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    refuse_kinds: list[SensitiveKind]
    # mask_kinds: list[SensitiveKind] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    mask_kinds: list[SensitiveKind]
    # max_chars: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_chars: PositiveInt
    # fallback_text: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    fallback_text: NonEmptyString


# MemoryWriteOutputPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class MemoryWriteOutputPolicy(StrictModel):
    # apply_detectors: Literal['all'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    apply_detectors: Literal["all"]
    # refuse_kinds: list[SensitiveKind] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    refuse_kinds: list[SensitiveKind]
    # mark_sensitive_kinds: list[SensitiveKind] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    mark_sensitive_kinds: list[SensitiveKind]


# OutputPolicies: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class OutputPolicies(StrictModel):
    # api: ApiOutputPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    api: ApiOutputPolicy
    # logs: LogOutputPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    logs: LogOutputPolicy
    # tts: TTSOutputPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tts: TTSOutputPolicy
    # memory_write: MemoryWriteOutputPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    memory_write: MemoryWriteOutputPolicy


# RetentionPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class RetentionPolicy(StrictModel):
    # raw_days: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    raw_days: PositiveInt
    # raw_on_expire: Literal['delete', 'compress'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    raw_on_expire: Literal["delete", "compress"]
    # events_days: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    events_days: PositiveInt
    # audit_days: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    audit_days: PositiveInt
    # metrics_days: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    metrics_days: PositiveInt
    # run_on_startup: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    run_on_startup: bool


# DeletionPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class DeletionPolicy(StrictModel):
    # leave_tombstone: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    leave_tombstone: bool
    # purge_from_backups: Literal['on_next_full_backup'] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    purge_from_backups: Literal["on_next_full_backup"]


# BackupPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StrictModel.
class BackupPolicy(StrictModel):
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # staging_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    staging_dir: Path
    # target: NonEmptyString 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    target: NonEmptyString
    # encryption: Literal['aes256', 'age'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    encryption: Literal["aes256", "age"]
    # passphrase_source: Literal['keyring'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    passphrase_source: Literal["keyring"]
    # schedule: Literal['daily', 'weekly', 'monthly'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    schedule: Literal["daily", "weekly", "monthly"]
    # keep_copies: PositiveInt 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    keep_copies: PositiveInt
    # restore_test_interval: Literal['monthly'] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    restore_test_interval: Literal["monthly"]
    # include: list[Path] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    include: list[Path]
    # exclude: list[Path] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    exclude: list[Path]


# PrivacyPolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: VersionedModel.
class PrivacyPolicy(VersionedModel):
    # api_transmission: ApiTransmissionPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    api_transmission: ApiTransmissionPolicy
    # detectors: list[DetectorPolicy] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    detectors: list[DetectorPolicy]
    # mask: MaskPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    mask: MaskPolicy
    # outputs: OutputPolicies 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    outputs: OutputPolicies
    # retention: RetentionPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    retention: RetentionPolicy
    # deletion: DeletionPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    deletion: DeletionPolicy
    # backup: BackupPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    backup: BackupPolicy

    # required_privacy_guards_exist(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Self.
    # @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
    @model_validator(mode="after")
    def required_privacy_guards_exist(self) -> Self:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not any(detector.kind == "secret" for detector in self.detectors):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("secret 종류 detector가 하나 이상 필요합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
        # self.outputs.memory_write.refuse_kinds.
        if not self.outputs.memory_write.refuse_kinds:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("memory_write.refuse_kinds는 비어 있을 수 없습니다")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self


# Policies: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Policies:
    # tools: ToolPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tools: ToolPolicy
    # privacy: PrivacyPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    privacy: PrivacyPolicy


# LoadedConfig: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class LoadedConfig:
    # settings: Settings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    settings: Settings
    # policies: Policies 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    policies: Policies
    # config_hash: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    config_hash: str
