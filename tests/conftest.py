"""
conftest.py — registers custom pytest marks so pytest doesn't warn about them.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "llm: marks tests that call the Groq LLM (skipped when GROQ_API_KEY is not set)",
    )
