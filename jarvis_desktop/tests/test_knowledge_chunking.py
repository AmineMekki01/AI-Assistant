from app.knowledge.chunking import chunk_markdown, chunk_text


def test_chunk_markdown_keeps_heading_context_and_stable_indexes():
    text = """# Project Atlas

## Operations

The launch owner is Amine. """ + ("This is an operational detail. " * 40)

    chunks = chunk_markdown(text, chunk_size=350, overlap=60)

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.heading_path == ("Project Atlas", "Operations") for chunk in chunks)
    assert all(chunk.text.startswith("Project Atlas > Operations") for chunk in chunks)


def test_chunk_text_handles_blank_and_short_plain_text():
    assert chunk_text("") == []
    assert chunk_text("one two") == ["one two"]
