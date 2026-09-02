from corpus_engine.ledger import open_ledger
from corpus_engine.domain import load_domain


def test_committed_log_renders_to_the_committed_snapshot(repo_root):
    v = open_ledger(domain=load_domain()).view()
    rendered = v.render()
    for name, data in rendered.items():
        on_disk = (repo_root / "data" / "ledger" / name).read_bytes().replace(b"\r\n", b"\n")
        assert data == on_disk, name
