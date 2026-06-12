"""Unit tests for SPARQL result shaping."""

from __future__ import annotations

from tests.conftest import make_select_json
from uniprot_link.services import shaping as S


def test_rows_coerces_types() -> None:
    body = make_select_json(["n", "flag", "uri"], [{"n": 5, "flag": True, "uri": "http://x/y"}])
    out = S.rows(body)
    assert out == [{"n": 5, "flag": True, "uri": "http://x/y"}]


def test_accession_from_uri() -> None:
    assert S.accession_from_uri("http://purl.uniprot.org/uniprot/P05067") == "P05067"
    assert S.accession_from_uri("http://purl.uniprot.org/isoforms/P05067-1") == "P05067-1"


def test_fold_curie() -> None:
    assert S.fold_curie("http://purl.uniprot.org/core/Protein") == "up:Protein"


def test_shape_find_proteins() -> None:
    body = make_select_json(
        ["protein", "mnemonic", "name", "reviewed", "organism", "taxid"],
        [
            {
                "protein": "http://purl.uniprot.org/uniprot/P38398",
                "mnemonic": "BRCA1_HUMAN",
                "name": "Breast cancer type 1 susceptibility protein",
                "reviewed": True,
                "organism": "Homo sapiens",
                "taxid": "http://purl.uniprot.org/taxonomy/9606",
            }
        ],
    )
    out = S.shape_find_proteins(body)
    assert out[0]["accession"] == "P38398"
    assert out[0]["reviewed"] is True
    assert out[0]["taxon_id"] == "9606"


def test_shape_sequences_marks_canonical() -> None:
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-3",
                "length": 365,
                "mass": 40000,
                "value": "MMM",
            },
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MLP",
            },
        ],
    )
    out = S.shape_sequences(body)
    assert out[0]["canonical"] is True
    assert out[0]["isoform"] == "P05067-1"


def test_shape_features_round_trips_type_to_filter_key() -> None:
    body = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
                "begin": 1642,
                "end": 1736,
                "comment": "BRCT 1",
            }
        ],
    )
    out = S.shape_features(body)
    assert out[0]["type"] == "domain"  # round-trips to the filter key
    assert out[0]["begin"] == 1642


def test_shape_variants_merges_diseases() -> None:
    body = make_select_json(
        ["begin", "end", "substitution", "comment", "disease"],
        [
            {
                "begin": 10,
                "end": 10,
                "substitution": "K",
                "comment": "In BC.",
                "disease": "Breast cancer",
            },
            {
                "begin": 10,
                "end": 10,
                "substitution": "K",
                "comment": "In BC.",
                "disease": "Ovarian cancer",
            },
            {"begin": 4, "end": 4, "substitution": "F", "comment": "Uncertain.", "disease": ""},
        ],
    )
    out = S.shape_variants(body)
    assert out[0]["begin"] == 10  # disease-associated variants sort first
    merged = next(v for v in out if v["begin"] == 10)
    assert set(merged["diseases"]) == {"Breast cancer", "Ovarian cancer"}
    assert any(v["begin"] == 4 and not v["diseases"] for v in out)


def test_shape_variants_merges_diseases_via_skos_related() -> None:
    body = make_select_json(
        ["begin", "end", "substitution", "comment", "disease", "dbsnp"],
        [
            {
                "begin": 10,
                "end": 10,
                "substitution": "K",
                "comment": "In BC and BROVCA1.",
                "disease": "Breast-ovarian cancer, familial, 1",
                "dbsnp": "http://purl.uniprot.org/dbsnp/rs80357017",
            },
            {
                "begin": 10,
                "end": 10,
                "substitution": "K",
                "comment": "In BC and BROVCA1.",
                "disease": "Breast cancer",
                "dbsnp": "http://purl.uniprot.org/dbsnp/rs80357017",
            },
        ],
    )
    out = S.shape_variants(body)
    assert len(out) == 1
    assert sorted(out[0]["diseases"]) == ["Breast cancer", "Breast-ovarian cancer, familial, 1"]
    assert out[0]["dbsnp"] == "rs80357017"


def test_shape_cross_references_groups() -> None:
    body = make_select_json(
        ["db", "database", "xref"],
        [
            {
                "db": "http://purl.uniprot.org/database/PDB",
                "database": "PDB",
                "xref": "http://x/7JXN",
            },
            {
                "db": "http://purl.uniprot.org/database/PDB",
                "database": "PDB",
                "xref": "http://x/1AAP",
            },
        ],
    )
    out = S.shape_cross_references(body)
    assert len(out["PDB"]) == 2


def test_shape_cross_references_short_vs_full_ids() -> None:
    body = make_select_json(
        ["db", "database", "xref"],
        [
            {
                "db": "http://purl.uniprot.org/database/PDB",
                "database": "PDB",
                "xref": "http://rdf.wwpdb.org/pdb/1AAP",
            }
        ],
    )
    assert S.shape_cross_references(body, short=True)["PDB"] == ["1AAP"]
    assert S.shape_cross_references(body, short=False)["PDB"] == ["http://rdf.wwpdb.org/pdb/1AAP"]


def test_shape_go_terms_groups_by_aspect() -> None:
    body = make_select_json(
        ["go", "label", "aspect"],
        [
            {
                "go": "http://purl.obolibrary.org/obo/GO_0008344",
                "label": "behaviour",
                "aspect": "http://purl.obolibrary.org/obo/GO_0008150",
            }
        ],
    )
    out = S.shape_go_terms(body)
    assert out["biological_process"][0]["id"] == "GO:0008344"


def test_shape_go_terms_buckets_by_root_aspect() -> None:
    body = make_select_json(
        ["go", "label", "aspect"],
        [
            {
                "go": "http://purl.obolibrary.org/obo/GO_0003677",
                "label": "DNA binding",
                "aspect": "http://purl.obolibrary.org/obo/GO_0003674",
            },
            {
                "go": "http://purl.obolibrary.org/obo/GO_0005634",
                "label": "nucleus",
                "aspect": "http://purl.obolibrary.org/obo/GO_0005575",
            },
        ],
    )
    grouped = S.shape_go_terms(body)
    assert grouped["molecular_function"][0]["id"] == "GO:0003677"
    assert "cellular_component" in grouped
    assert "unknown" not in grouped


def test_shape_go_terms_unknown_when_no_root_aspect() -> None:
    body = make_select_json(
        ["go", "label"],
        [{"go": "http://purl.obolibrary.org/obo/GO_9999999", "label": "obsolete term"}],
    )
    grouped = S.shape_go_terms(body)
    assert grouped["unknown"][0]["id"] == "GO:9999999"


def test_shape_taxon_core() -> None:
    body = make_select_json(
        ["scientificName", "commonName", "rank"],
        [
            {
                "scientificName": "Homo sapiens",
                "commonName": "Human",
                "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Species",
            }
        ],
    )
    out = S.shape_taxon_core(body)
    assert out is not None
    assert out["scientific_name"] == "Homo sapiens"
    assert out["rank"] == "Species"


def test_shape_ancestors_orders_species_to_root_and_picks_direct_parent() -> None:
    ancestor_rows = [
        {
            "ancestor": "http://purl.uniprot.org/taxonomy/9605",
            "name": "Homo",
            "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Genus",
            "depth": 0,
        },
        {
            "ancestor": "http://purl.uniprot.org/taxonomy/9604",
            "name": "Hominidae",
            "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Family",
            "depth": 2,
        },
        {
            "ancestor": "http://purl.uniprot.org/taxonomy/207598",
            "name": "Homininae",
            "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Subfamily",
            "depth": 1,
        },
    ]
    body = make_select_json(["ancestor", "name", "rank", "depth"], ancestor_rows)
    parent, lineage = S.shape_ancestors(body)
    assert parent == {"taxon_id": "9605", "scientific_name": "Homo", "rank": "Genus"}
    assert [a["scientific_name"] for a in lineage] == ["Homo", "Homininae", "Hominidae"]


def test_shape_ancestors_root_taxon_has_no_parent() -> None:
    empty = make_select_json(["ancestor", "name", "rank", "depth"], [])
    assert S.shape_ancestors(empty) == (None, [])


def test_shape_variants_adds_wildtype_and_notation():
    from tests.conftest import make_select_json
    from uniprot_link.services.shaping import shape_variants

    body = make_select_json(
        ["begin", "end", "substitution", "wildType", "comment", "disease", "dbsnp"],
        [
            {
                "begin": 176,
                "end": 176,
                "substitution": "F",
                "wildType": "L",
                "comment": "In MCSZ.",
                "disease": "Microcephaly, seizures, and developmental delay",
                "dbsnp": "http://purl.uniprot.org/dbsnp/rs267606957",
            },
            {
                "begin": 408,
                "end": 408,
                "substitution": "",
                "wildType": "T",
                "comment": "In AOA4.",
                "disease": "Ataxia-oculomotor apraxia 4",
            },
        ],
    )
    out = {v["begin"]: v for v in shape_variants(body)}
    assert out[176]["wild_type"] == "L"
    assert out[176]["variant_type"] == "substitution"
    assert out[176]["notation"] == "L176F"
    assert out[176]["substitution"] == "F"
    assert out[408]["wild_type"] == "T"
    assert out[408]["variant_type"] == "other"
    assert "notation" not in out[408]
    # C6: an empty substitution is omitted, never emitted as "" (which reads as
    # "substitutes to nothing").
    assert "substitution" not in out[408]


def test_apply_response_mode_projects_protein_payload() -> None:
    from uniprot_link.services.shaping import apply_response_mode

    full = {
        "accession": "P38398",
        "mnemonic": "BRCA1_HUMAN",
        "function": "long text...",
        "short_name": "BRCA1",
        "common_name": "Human",
        "created": "1994-10-01",
        "modified": "2024-01-01",
    }
    minimal = apply_response_mode(full, "minimal", kind="protein")
    assert "function" not in minimal and minimal["accession"] == "P38398"
    compact = apply_response_mode(full, "compact", kind="protein")
    assert "created" not in compact and "function" in compact
    assert apply_response_mode(full, "full", kind="protein") == full
    assert apply_response_mode(full, "standard", kind="protein") == full
    # projection must not mutate the caller's payload (it may be cached upstream)
    assert "function" in full and "created" in full


def test_shape_taxon_resolutions_includes_rank() -> None:
    body = make_select_json(
        ["taxon", "scientificName", "commonName", "rank"],
        [
            {
                "taxon": "http://purl.uniprot.org/taxonomy/9606",
                "scientificName": "Homo sapiens",
                "commonName": "Human",
                "rank": "http://purl.uniprot.org/core/Species",
            }
        ],
    )
    out = S.shape_taxon_resolutions(body)
    assert out[0]["taxon_id"] == "9606"
    assert out[0]["rank"] == "Species"


def test_shape_features_emits_only_filterable_types() -> None:
    from uniprot_link.services.constants import FEATURE_TYPES

    body = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Natural_Variant_Annotation",
                "begin": 176,
                "end": 176,
                "comment": "In MCSZ.",
            },
            {
                "type": "http://purl.uniprot.org/core/Alternative_Sequence_Annotation",
                "begin": 1,
                "end": 50,
                "comment": "In isoform 2.",
            },
            {
                "type": "http://purl.uniprot.org/core/Sequence_Conflict_Annotation",
                "begin": 6,
                "end": 6,
                "comment": "",
            },
        ],
    )
    out = S.shape_features(body)
    for f in out:
        assert f["type"] in FEATURE_TYPES, f"{f['type']} not filterable"
    assert {f["type"] for f in out} == {
        "natural_variant",
        "alternative_sequence",
        "sequence_conflict",
    }


def test_shape_features_flags_unmapped_class() -> None:
    body = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Totally_New_Annotation",
                "begin": 1,
                "end": 2,
                "comment": "",
            }
        ],
    )
    out = S.shape_features(body)
    assert out[0]["type"].startswith("_unmapped:")


def test_shape_diseases_splits_involvement_and_definition() -> None:
    body = make_select_json(
        ["disease", "diseaseLabel", "comment", "definition", "mnemonic", "mim"],
        [
            {
                "disease": "http://purl.uniprot.org/diseases/4356",
                "diseaseLabel": "Ataxia-oculomotor apraxia 4",
                "comment": "The disease is caused by variants affecting the gene...",
                "definition": "An autosomal recessive disease characterized by ...",
                "mnemonic": "AOA4",
                "mim": "http://purl.uniprot.org/mim/616267",
            }
        ],
    )
    out = S.shape_diseases(body)
    assert out[0]["involvement"].startswith("The disease is caused")
    assert out[0]["definition"].startswith("An autosomal recessive")
    assert out[0]["mnemonic"] == "AOA4"
    assert out[0]["mim"] == "616267"
    assert out[0]["disease"] == "Ataxia-oculomotor apraxia 4"


def test_shape_go_terms_includes_and_merges_evidence() -> None:
    # Two rows for the same GO term with different ECO codes -> merged, deduped.
    body = make_select_json(
        ["go", "label", "aspect", "eco"],
        [
            {
                "go": "http://purl.obolibrary.org/obo/GO_0006303",
                "label": "double-strand break repair via NHEJ",
                "aspect": "http://purl.obolibrary.org/obo/GO_0008150",
                "eco": "http://purl.obolibrary.org/obo/ECO_0000314",
            },
            {
                "go": "http://purl.obolibrary.org/obo/GO_0006303",
                "label": "double-strand break repair via NHEJ",
                "aspect": "http://purl.obolibrary.org/obo/GO_0008150",
                "eco": "http://purl.obolibrary.org/obo/ECO_0000501",
            },
            {
                "go": "http://purl.obolibrary.org/obo/GO_0005634",
                "label": "nucleus",
                "aspect": "http://purl.obolibrary.org/obo/GO_0005575",
                "eco": "",
            },
        ],
    )
    out = S.shape_go_terms(body)
    bp = out["biological_process"]
    assert len(bp) == 1  # the two evidence rows merged into one term
    term = bp[0]
    assert term["id"] == "GO:0006303"
    assert set(term["evidence"]) == {"ECO:0000314", "ECO:0000501"}
    assert "IDA" in term["evidence_codes"] and "IEA" in term["evidence_codes"]
    # a term with no evidence omits the evidence keys
    cc = out["cellular_component"][0]
    assert cc["id"] == "GO:0005634"
    assert "evidence" not in cc


def test_shape_example_list_dedupes_ids_and_ranks_native_first() -> None:
    native = "https://sparql.uniprot.org/.well-known/sparql-examples/26"
    federated = "https://sparql.rhea-db.org/.well-known/sparql-examples/114"
    body = make_select_json(
        ["ex", "desc", "qtype", "keywords"],
        [
            # federated (Rhea) example, listed first by the SPARQL ORDER BY ?ex
            {"ex": federated, "desc": "rhea ex", "qtype": "", "keywords": ""},
            # the native example appears twice (two rdfs:comment values)
            {"ex": native, "desc": "native ex", "qtype": "", "keywords": "domain"},
            {"ex": native, "desc": "native ex (alt)", "qtype": "", "keywords": "domain"},
        ],
    )
    out = S.shape_example_list(body)
    ids = [e["example_id"] for e in out]
    assert ids.count(native) == 1  # deduped by example_id
    assert ids[0] == native  # native ranks above the federated Rhea example
    assert out[0].get("federated") is None  # native carries no federated flag
    assert out[-1]["federated"] is True  # the Rhea example is flagged federated


def test_average_mass_matches_uniprot_canonical() -> None:
    from uniprot_link.services.shaping import average_mass

    # PNKP canonical isoform Q96T60-1: UniProt reports 57076 Da for this 521-aa
    # sequence. This locks the residue mass table against drift.
    q96t60_1 = (
        "MGEVEAPGRLWLESPPGGAPPIFLPSDGQALVLGRGPLTQVTDRKCSRTQVELVADPETRTVAVKQLGVNPST"
        "TGTQELKPGLEGSLGVGDTLYLVNGLHPLTLRWEETRTPESQPDTPPGTPLVSQDEKRDAELPKKRMRKSNPG"
        "WENLEKLLVFTAAGVKPQGKVAGFDLDGTLITTRSGKVFPTGPSDWRILYPEIPRKLRELEAEGYKLVIFTNQ"
        "MSIGRGKLPAEEFKAKVEAVVEKLGVPFQVLVATHAGLYRKPVTGMWDHLQEQANDGTPISIGDSIFVGDAAG"
        "RPANWAPGRKKKDFSCADRLFALNLGLPFATPEEFFLKWPAAGFELPAFDPRTVSRSGPLCLPESRALLSASP"
        "EVVVAVGFPGAGKSTFLKKHLVSAGYVHVNRDTLGSWQRCVTTCETALKQGKRVAIDNTNPDAASRARYVQCA"
        "RAAGVPCRCFLFTATLEQARHNNRFREMTDSSHIPVSDMVMYGYRKQFEAPTLAEGFSAILEIPFRLWVEPRL"
        "GRLYCQFSEG"
    )
    assert len(q96t60_1) == 521
    mass = average_mass(q96t60_1)
    assert mass is not None
    assert abs(mass - 57076) <= 2


def test_isoform_mass_is_computed_when_absent() -> None:
    from tests.conftest import make_select_json
    from uniprot_link.services.shaping import shape_sequences

    body = make_select_json(
        ["isoform", "length", "value"],
        [{"isoform": "http://purl.uniprot.org/isoforms/Q96T60-2", "length": 5, "value": "ACDEF"}],
    )
    iso = shape_sequences(body)[0]
    assert isinstance(iso["mass_da"], int)
    assert iso["mass_da"] > 0
    assert iso["mass_computed"] is True


def test_canonical_mass_is_not_marked_computed() -> None:
    from tests.conftest import make_select_json
    from uniprot_link.services.shaping import shape_sequences

    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 8,
                "mass": 86943,
                "value": "MLPCANON",
            }
        ],
    )
    canonical = shape_sequences(body)[0]
    assert canonical["mass_da"] == 86943
    assert "mass_computed" not in canonical
