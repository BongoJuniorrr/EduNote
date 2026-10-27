from src.services.edu_studio.document_parser import (
    ParsedMaterial,
    combine_materials_text,
    parse_uploaded_material,
)


def test_parse_uploaded_material_text_file():
    raw = b"Lesson objective: understand fractions.\nExample activity: card sorting."
    parsed = parse_uploaded_material("lesson.txt", raw, "text/plain")

    assert parsed.filename == "lesson.txt"
    assert "understand fractions" in parsed.content
    assert parsed.warnings == []


def test_parse_uploaded_material_csv_file():
    raw = (
        "Topic,Difficulty,Count\n"
        "Fractions,Understand,4\n"
        "Fractions,Apply,2\n"
    ).encode("utf-8")
    parsed = parse_uploaded_material("matrix.csv", raw, "text/csv")

    assert "Topic | Difficulty | Count" in parsed.content
    assert "Fractions | Understand | 4" in parsed.content


def test_combine_materials_text_merges_user_input_and_materials():
    materials = [
        ParsedMaterial(filename="A.txt", content="Alpha"),
        ParsedMaterial(filename="B.txt", content="Beta"),
    ]
    combined = combine_materials_text("Teacher requirements", materials)

    assert "## User Input" in combined
    assert "Teacher requirements" in combined
    assert "## Material: A.txt" in combined
    assert "Alpha" in combined
    assert "## Material: B.txt" in combined
    assert "Beta" in combined
