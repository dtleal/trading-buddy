from __future__ import annotations

import pytest

from tests.fakes import FakeQARepository
from use_cases.manage_qa import (
    CreateQAEntryUseCase,
    DeleteQAEntryUseCase,
    ListQAEntriesUseCase,
    QAValidationError,
    UpdateQAEntryUseCase,
)


@pytest.mark.asyncio
async def test_create_trims_text_and_normalises_tags() -> None:
    repo = FakeQARepository()
    entry = await CreateQAEntryUseCase(repo).execute(
        question="  Operar lateralidade?  ",
        answer="  Depende da volatilidade.  ",
        tags=["Bollinger", "bollinger", " 5min ", "", "Risco"],
    )

    assert entry.question == "Operar lateralidade?"
    assert entry.answer == "Depende da volatilidade."
    # lowercased, trimmed, de-duped, blanks dropped, order preserved
    assert entry.tags == ["bollinger", "5min", "risco"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "answer"),
    [("   ", "resposta"), ("pergunta", ""), ("", "")],
)
async def test_create_rejects_empty_fields(question: str, answer: str) -> None:
    repo = FakeQARepository()
    with pytest.raises(QAValidationError):
        await CreateQAEntryUseCase(repo).execute(question=question, answer=answer, tags=[])


@pytest.mark.asyncio
async def test_list_returns_most_recently_updated_first() -> None:
    repo = FakeQARepository()
    create = CreateQAEntryUseCase(repo)
    first = await create.execute(question="Q1", answer="A1", tags=[])
    second = await create.execute(question="Q2", answer="A2", tags=[])

    # Touch the older entry so it jumps to the top.
    await UpdateQAEntryUseCase(repo).execute(first.id, question="Q1 editada", answer="A1", tags=[])

    listed = await ListQAEntriesUseCase(repo).execute()
    assert [e.id for e in listed] == [first.id, second.id]
    assert listed[0].question == "Q1 editada"


@pytest.mark.asyncio
async def test_update_missing_entry_returns_none() -> None:
    repo = FakeQARepository()
    result = await UpdateQAEntryUseCase(repo).execute(999, question="Q", answer="A", tags=[])
    assert result is None


@pytest.mark.asyncio
async def test_update_bumps_updated_at() -> None:
    repo = FakeQARepository()
    created = await CreateQAEntryUseCase(repo).execute(question="Q", answer="A", tags=[])
    updated = await UpdateQAEntryUseCase(repo).execute(
        created.id, question="Q", answer="A2", tags=[]
    )
    assert updated is not None
    assert updated.updated_at > created.updated_at
    assert updated.created_at == created.created_at


@pytest.mark.asyncio
async def test_delete_returns_true_then_false() -> None:
    repo = FakeQARepository()
    created = await CreateQAEntryUseCase(repo).execute(question="Q", answer="A", tags=[])
    delete = DeleteQAEntryUseCase(repo)

    assert await delete.execute(created.id) is True
    assert await delete.execute(created.id) is False
    assert await ListQAEntriesUseCase(repo).execute() == []
