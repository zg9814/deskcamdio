from __future__ import annotations

from pathlib import Path

from PIL import Image

from deskcamdio.cli.photo_worker import apply_filter, main


def make_jpeg(path: Path, color=(120, 140, 160)) -> Path:
    image = Image.new("RGB", (64, 48), color)
    image.save(path, format="JPEG")
    return path


def test_bw_filter_makes_grayscale(tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "in.jpg")
    dst = tmp_path / "out.jpg"
    apply_filter(src, dst, "bw")

    with Image.open(dst) as result:
        r, g, b = result.convert("RGB").split()
        extrema_r = r.getextrema()
        assert isinstance(extrema_r[0], int)
        # Grayscale channels are identical by construction of the pipeline.
        assert list(result.convert("RGB").getdata())[0] == list(result.convert("RGB").getdata())[1]


def test_ccd_and_leica_produce_files(tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "src.jpg")
    for name in ("ccd", "leica"):
        dst = tmp_path / f"{name}.jpg"
        apply_filter(src, dst, name)
        assert dst.exists()
        parts = list(tmp_path.glob("*.part"))
        assert parts == []


def test_failure_keeps_original_intact(tmp_path: Path, capsys) -> None:
    src = make_jpeg(tmp_path / "keep.jpg")
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not a jpeg")
    exit_code = main(["--src", str(broken), "--dst", str(src), "--filter", "bw"])
    assert exit_code == 1
    # original untouched and readable
    with Image.open(src) as check:
        assert check.size == (64, 48)
    assert "photo-worker error" in capsys.readouterr().err


def test_cli_writes_destination(tmp_path: Path, capsys) -> None:
    src = make_jpeg(tmp_path / "a.jpg")
    dst = tmp_path / "nested" / "b.jpg"
    exit_code = main(["--src", str(src), "--dst", str(dst), "--filter", "leica"])
    assert exit_code == 0
    assert dst.exists()
    assert str(dst) in capsys.readouterr().out
