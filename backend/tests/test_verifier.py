from app.services.verifier import normalized_title_similarity


def test_title_similarity_rejects_loose_crossref_match():
    assert normalized_title_similarity("medusa layout smoke", "MEDUSA") < 0.82


def test_title_similarity_accepts_minor_case_and_spacing_differences():
    assert normalized_title_similarity("Situated Knowledges", "situated   knowledges") > 0.82
