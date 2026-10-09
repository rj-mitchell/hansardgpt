"""Streaming parse keeps memory bounded regardless of file size."""

import subprocess
import sys
import textwrap


def _write_big_file(path, n_speeches: int) -> int:
    para = "This is a long contribution about railway delays and agricultural zoning. " * 20
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<publicwhip scraperversion="a" latest="yes">\n')
        fh.write('<major-heading id="uk.org.publicwhip/debate/2025-01-01a.1.0" nospeaker="true">Big</major-heading>\n')
        for i in range(n_speeches):
            fh.write(f'<speech id="uk.org.publicwhip/debate/2025-01-01a.{i}.1" speakername="X" '
                     f'person_id="uk.org.publicwhip/person/10001" colnum="{i}" time="12:00:00" url="">'
                     f'<p>{para}</p><p>{para}</p></speech>\n')
        fh.write("</publicwhip>\n")
    return path.stat().st_size


def test_parse_memory_is_bounded(tmp_path):
    big = tmp_path / "debates" / "debates2025-01-01a.xml"
    big.parent.mkdir()
    size = _write_big_file(big, 80_000)
    assert size > 250_000_000
    script = textwrap.dedent(f"""
        import resource
        from hansard.parse.xml_stream import parse_file
        n = 0
        for row in parse_file({str(big)!r}, "debates"):
            n += 1
        print(n, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
    """)
    out = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True).stdout.split()
    n, peak_mb = int(out[0]), int(out[1])
    assert n == 80_000
    # A DOM parse of a 250 MB file needs well over 1 GB; streaming stays small.
    assert peak_mb < 200, f"peak RSS {peak_mb} MB for a {size // 1_000_000} MB file"
