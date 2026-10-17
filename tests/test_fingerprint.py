from fpvcut.core.fingerprint import fingerprint


def test_same_content_same_fingerprint(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "sub_b.mp4"
    a.write_bytes(b"x" * 1000)
    b.write_bytes(b"x" * 1000)
    assert fingerprint(a) == fingerprint(b)


def test_large_file_uses_head_middle_tail(tmp_path):
    chunk = 16
    data = bytearray(b"\0" * (chunk * 10))
    f = tmp_path / "big.mp4"
    f.write_bytes(data)
    base = fingerprint(f, chunk_size=chunk)

    data[chunk * 5] = 1  # liegt im mittleren Block
    f.write_bytes(data)
    assert fingerprint(f, chunk_size=chunk) != base

    data[chunk * 5] = 0
    data[chunk * 2] = 1  # liegt zwischen den Blöcken, wird bewusst nicht gelesen
    f.write_bytes(data)
    assert fingerprint(f, chunk_size=chunk) == base


def test_size_is_part_of_fingerprint(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"\0" * 100)
    b.write_bytes(b"\0" * 101)
    assert fingerprint(a) != fingerprint(b)
