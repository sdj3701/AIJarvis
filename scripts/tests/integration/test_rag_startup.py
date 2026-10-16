from io import StringIO
from pathlib import Path

import pytest

from app.llm.fake import FakeLLMClient
from app.rag.indexer import DocumentIndexer
from app.wiring import run_application

pytestmark = pytest.mark.phase3


def test_answer_model_is_ready_before_embedding_index_sync(config_dir: Path, monkeypatch):
    order = []

    class ReadyLLM(FakeLLMClient):
        def verify_model(self):
            order.append("ready")

    original = DocumentIndexer.sync

    def sync(self, **kwargs):
        assert order == ["ready"]
        order.append("index")
        return original(self, **kwargs)

    monkeypatch.setattr(DocumentIndexer, "sync", sync)
    llm = ReadyLLM().reply("안녕하세요.").reply(
        '{"schema_version":1,"summary":"테스트", "fact_candidates":[],"corrections":[]}'
    )
    code = run_application(config_dir=config_dir, llm=llm, once="안녕",
                           input_stream=StringIO(), output_stream=StringIO(),
                           error_stream=StringIO())
    assert code == 0
    assert order == ["ready", "index"]
