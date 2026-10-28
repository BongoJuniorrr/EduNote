def pytest_addoption(parser):
    parser.addoption(
        "--pipeline", action="store", default="llamaindex",
        help="RAG backend for explicitly selected external integration tests",
    )
