"""Índice de guías: partición con ubicación, vínculo por URL y búsqueda BM25 (datos sintéticos)."""
import pandas as pd

from tools import guides as G

GUIDE = """# Sources and attribution

Tree inventory A: https://data.example.org/dataset/tree-a ; licence: https://creativecommons.org/licenses/by/4.0/ .

Both catalogue pages specify CC BY 4.0. Metadata resource/update dates are not per-tree observation dates.

The supplied JSON files assemble complete selected resources. The exports contain tabular records; no coordinates have been invented.
"""

TXT_GUIDE = """Use the frozen sources. Round distances to two decimals.

Scope and provenance
The drawing views are bounded subsets of 200 features. Do not extrapolate a view to the city.
"""


def test_split_units_numbers_paragraphs_and_skips_headings():
    u = G.split_units(GUIDE, "SRC_g", "SourceGuide.md")
    dates = [x for x in u if "observation dates" in x["text"]][0]
    assert dates["para"] == 2 and dates["text"].startswith("Metadata resource")
    coords = [x for x in u if "coordinates" in x["text"]][0]
    assert coords["para"] == 3
    assert not any(x["text"].startswith("#") for x in u)


def test_plain_text_heading_line_is_dropped():
    u = G.split_units(TXT_GUIDE, "SRC_z", "ReadingGuide.txt")
    bounded = [x for x in u if "bounded subsets" in x["text"]][0]
    assert bounded["para"] == 2 and not bounded["text"].startswith("Scope")


def test_bm25_finds_the_right_sentence_within_allowed_guides():
    units = G.split_units(GUIDE, "SRC_g", "SourceGuide.md") + G.split_units(TXT_GUIDE, "SRC_z", "ReadingGuide.txt")
    idx = G.GuideIndex(units)
    top = idx.search("Could the portal's file-update date stand in for an observation date?", {"SRC_g"}, k=3)
    assert top and "observation dates" in top[0]["text"]
    top2 = idx.search("Can I report the summed area of the view as the whole city?", {"SRC_z"}, k=1)
    assert "extrapolate" in top2[0]["text"] or "bounded" in top2[0]["text"]
    assert idx.search("observation date", {"SRC_other"}) == []


def test_link_guides_ignores_licence_urls():
    man = pd.DataFrame({
        "File": ["sources/SRC_g__SourceGuide.md", "sources/SRC_a__A.json", "sources/SRC_b__B.csv"],
        "Publisher": ["Challenge organisers", "City A", "City B"],
        "Source_URL": ["https://data.example.org/dataset/tree-a | https://creativecommons.org/licenses/by/4.0/",
                       "https://data.example.org/dataset/tree-a", "https://other.example.org/b"],
        "Attribution": ["", "", "https://creativecommons.org/licenses/by/4.0/"],
    }, index=["SRC_g", "SRC_a", "SRC_b"])
    assert G.guide_ids(man) == ["SRC_g"]
    assert G.link_guides(man) == {"SRC_g": {"SRC_a"}}


def test_metadata_notes_are_citable_sources():
    man = pd.DataFrame({
        "File": ["sources/SRC_m__DCC_metadata.json", "sources/SRC_d__DCC.json", "sources/SRC_g__SourceGuide.md"],
        "Publisher": ["Dublin City Council", "Dublin City Council", "Challenge organisers"],
        "Source_URL": ["https://data.example.org/tree-dcc"] * 3, "Attribution": [""] * 3,
    }, index=["SRC_m", "SRC_d", "SRC_g"])
    assert G.meta_ids(man) == ["SRC_m"] and set(G.note_ids(man)) == {"SRC_g", "SRC_m"}
    assert G.link_guides(man)["SRC_m"] == {"SRC_d", "SRC_g"}
    txt = G.meta_text({"result": {"notes": "Partial representation of trees.\r\n\r\nInformation purposes only."}})
    u = G.split_units(txt, "SRC_m", "DCC_metadata.json notes")
    assert [x["para"] for x in u] == [1, 2] and u[0]["text"].startswith("Partial")
