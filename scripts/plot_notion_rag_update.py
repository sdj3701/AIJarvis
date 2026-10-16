"""Reproduce portfolio charts from the 2026-10-14 service retrieval report."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/evaluations/rag-current-20261014/retrieval-final/service_report.json"
OUT = ROOT / "artifacts/evaluations/notion-jarvis-20261014"
OUT.mkdir(parents=True, exist_ok=True)
report = json.loads(SOURCE.read_text(encoding="utf-8"))
assert report["queries"] == 200 and report["repeats"] == 3
assert report["embedding_identity"].startswith("embeddinggemma:")
rows = {(r["pipeline"], r["query_type"]): r for r in report["summaries"]}
pipelines = ("hybrid_rrf", "hybrid_rerank")
names = ("Hybrid RRF", "Hybrid RRF + Cross-Encoder")
colors = ("#3176CB", "#008777")
plt.rcParams.update({
    "font.family": "Malgun Gothic", "font.size": 12, "axes.unicode_minus": False,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#BAC6D3", "text.color": "#182B42", "axes.labelcolor": "#182B42",
    "xtick.color": "#405269", "ytick.color": "#405269",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def plot(filename, title, subtitle, labels, values, ylabel, ylim, unit, footer):
    fig, ax = plt.subplots(figsize=(11.5, 6.6))
    fig.subplots_adjust(left=.09, right=.97, top=.75, bottom=.22)
    fig.text(.09, .93, title, fontsize=22, weight="bold")
    fig.text(.09, .866, subtitle, fontsize=11, color="#58677A")
    x = np.arange(len(labels))
    for i, (name, color, data) in enumerate(zip(names, colors, values, strict=True)):
        bars = ax.bar(x + (i-.5)*.32, data, width=.30, label=name, color=color, zorder=3)
        ax.bar_label(bars, labels=[f"{v:.1f}{unit}" for v in data], padding=7, fontsize=12)
    ax.set_xticks(x, labels)
    ax.set_ylabel(ylabel, labelpad=12)
    ax.set_ylim(*ylim)
    ax.grid(axis="y", color="#E6ECF2", zorder=0)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.18), ncol=2, frameon=False, fontsize=11)
    fig.text(.09, .10, footer, fontsize=10, color="#58677A", linespacing=1.6)
    fig.savefig(OUT / filename, dpi=180)
    plt.close(fig)


plot("retrieval_quality.png", "학습된 임베딩 기반 문서 검색 품질",
     "2026.10.14 측정 · EmbeddingGemma 768차원 + sqlite-vec · 문서 20개 / 질문 200개",
     ["Recall@1", "Recall@5", "MRR@5 × 100"],  # noqa: RUF001
     [[rows[p, "all"][m]*100 for m in ("recall_at_1", "recall_at_5", "mrr_at_5")]
      for p in pipelines], "지표 값 × 100 (높을수록 좋음)", (0, 110), "",  # noqa: RUF001
     "동일한 실제 앱 검색 경로에서 재정렬 설정을 비교했습니다. 두 경로의 후보 수 설정도 다릅니다.\n"
     "검색 품질 평가이며, 최종 답변 정확도나 과거 대화 검색 정확도를 측정한 결과는 아닙니다.")
plot("retrieval_by_question_type.png", "재정렬 효과는 질문 유형에 따라 다릅니다",
     "2026.10.14 측정 · 정답 문서가 첫 번째에 나오는 비율 (Recall@1)",
     ["키워드 중심\n67개", "의미 중심\n67개", "혼합형\n66개"],
     [[rows[p, kind]["recall_at_1"]*100 for kind in ("keyword", "semantic", "hybrid")]
      for p in pipelines], "Recall@1 (%)", (0, 115), "%",
     "의미 중심: 74.6% → 85.1% / 키워드 중심: 86.6% → 83.6%\n"
     "문서 20개에서 만든 소규모 데모 질문입니다. 실제 사용자 질문 전체로 일반화하지 않습니다.")
plot("retrieval_latency.png", "검색 품질 개선에 추가 지연이 발생했습니다",
     "2026.10.14 측정 · 200개 질문 × 경로별 3회 · 단일 PC 순차 실행",  # noqa: RUF001
     ["P50 검색 시간", "P95 검색 시간"],
     [[rows[p, "all"][m] for m in ("latency_p50_ms", "latency_p95_ms")]
      for p in pipelines], "검색 시간 (ms, 낮을수록 좋음)", (0, 330), "",
     "질문 임베딩·문서 동기화·검색·RRF·재정렬(사용 시)을 포함합니다.\n"
     "초기 색인과 워밍업, LLM 답변 생성은 제외했습니다. "
     "구버전 해싱 검색 시간과 직접 비교하지 않습니다.")

(OUT / "chart_provenance.json").write_text(json.dumps({
    "source": str(SOURCE.relative_to(ROOT)),
    "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "measured_at": report["created_at"],
    "embedding_identity": report["embedding_identity"],
    "documents": report["documents"], "queries": report["queries"], "repeats": report["repeats"],
    "summaries": report["summaries"],
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(OUT)
