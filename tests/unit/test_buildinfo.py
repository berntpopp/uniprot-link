def test_build_info_reports_version_and_env(monkeypatch):
    from uniprot_link import __version__
    from uniprot_link.buildinfo import build_info

    monkeypatch.setenv("UNIPROT_LINK_GIT_SHA", "abc1234")
    monkeypatch.setenv("UNIPROT_LINK_BUILT_AT", "2026-06-12T00:00:00Z")
    info = build_info()
    assert info["version"] == __version__
    assert info["git_sha"] == "abc1234"
    assert info["built_at"] == "2026-06-12T00:00:00Z"

    monkeypatch.delenv("UNIPROT_LINK_GIT_SHA", raising=False)
    assert build_info()["git_sha"] == "unknown"
