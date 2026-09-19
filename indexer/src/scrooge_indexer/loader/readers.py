"""Getting a header and a stream of rows out of whatever the council published.

Three problems, in this order: which encoding, which delimiter, and which line
is the header. None of them is announced anywhere in the file, and all three
vary inside a single borough, so each is decided per file from the bytes.

Rows are yielded one at a time and never collected. The biggest file on disk
is 23 MB and a borough is 1.3 GB, so holding a file's rows would be tolerable
and holding a borough's would not; streaming both costs nothing extra.
"""

from __future__ import annotations

import codecs
import csv
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .mappings import normalise

#: Tried in this order, as the schema doc says. cp1252 decodes all but five
#: byte values, so it is the last word rather than one more guess.
ENCODINGS = ("utf-8-sig", "cp1252")

#: Delimiters worth considering. Councils publish commas and, once, tabs.
DELIMITERS = (",", "\t", ";", "|")

#: How many parsed records to search for the header before giving up. The
#: deepest real header is the Hounslow leaked-SQL one at record 5.
HEADER_SEARCH_ROWS = 30

#: Bytes read to decide the encoding and the delimiter.
PROBE_BYTES = 1 << 20

#: csv's default field cap is 128 KB. Hounslow's leaked SQL query is a single
#: quoted field longer than that, and a file we refuse to open is a file we
#: cannot report on.
csv.field_size_limit(16 << 20)


class ReadError(Exception):
    """The file cannot be turned into rows at all. Carries the operator reason."""


class NoHeader(ReadError):
    """No header row in the first :data:`HEADER_SEARCH_ROWS` records.

    Carries those records, because what they contain is what tells a supplier
    total file apart from a genuinely headerless one, and the caller should not
    have to open the file a second time to find out.
    """

    def __init__(self, rows: list[list[object]]) -> None:
        super().__init__("no header row found")
        self.rows = rows


@dataclass
class Table:
    """One file opened: its header row, and the data rows after it."""

    header: list[str]
    rows: Iterator[list[object]]
    encoding: str
    delimiter: str
    header_row: int  # 0-based record index the header was found on
    sheet: str | None = None


def sniff_encoding(path: Path) -> str:
    """utf-8-sig when the whole file decodes as UTF-8, cp1252 otherwise.

    The whole file, not a sample: a 20 MB Lambeth quarter that is clean UTF-8
    for its first megabyte and cp1252 in a supplier name near the end would
    otherwise fail halfway through a COPY, after the transaction had started.
    """
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    with path.open("rb") as handle:
        while chunk := handle.read(PROBE_BYTES):
            try:
                decoder.decode(chunk)
            except UnicodeDecodeError:
                return "cp1252"
    try:
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8-sig"


def sniff_delimiter(sample: str) -> str:
    """The delimiter that appears most often across the first few lines.

    csv.Sniffer is tried first and overruled when it picks something that is
    not a delimiter this corpus uses. It reads a Bexley title row of commas as
    a space-delimited file often enough to be worth the second opinion.
    """
    lines = [line for line in sample.splitlines()[:20] if line.strip()]
    if not lines:
        return ","
    try:
        guess = csv.Sniffer().sniff("\n".join(lines), delimiters="".join(DELIMITERS))
        if guess.delimiter in DELIMITERS:
            return guess.delimiter
    except csv.Error:
        pass
    counts = {d: sum(line.count(d) for line in lines) for d in DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def find_header(rows: list[list[object]], expected: tuple[str, ...]) -> int | None:
    """Index of the header row: the first one carrying an expected date column.

    A second header directly underneath the first wins, which is the one thing
    the Hounslow leaked-SQL files need: their record 4 lists the column names
    with a gap where `Redaction Necessary` belongs and record 5 repeats them
    with the gap filled in.
    """
    wanted = set(expected)
    found = None
    for index, row in enumerate(rows):
        if wanted & {normalise(cell) for cell in row}:
            if found is not None and index != found + 1:
                break
            found = index
    return found


@contextmanager
def open_table(path: Path, expected_dates: tuple[str, ...]) -> Iterator[Table]:
    """Open one spend file and hand back its header and row stream.

    Raises :class:`ReadError` when the format has no reader here or no header
    row can be found. The caller decides whether that is a skip or a failure.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with _open_csv(path, expected_dates) as table:
            yield table
    elif suffix == ".xlsx":
        with _open_xlsx(path, expected_dates) as table:
            yield table
    elif suffix == ".ods":
        raise ReadError("no ODS reader")
    else:
        raise ReadError(f"no reader for {suffix or 'extensionless file'}")


@contextmanager
def _open_csv(path: Path, expected_dates: tuple[str, ...]) -> Iterator[Table]:
    encoding = sniff_encoding(path)
    with path.open("rb") as probe:
        head = probe.read(PROBE_BYTES)
    if head[:4] == b"\xd0\xcf\x11\xe0":
        raise ReadError("Excel 97 workbook published with a .csv extension")
    delimiter = sniff_delimiter(head.decode(encoding, errors="replace"))
    # newline="" hands csv the bare line endings, which is what lets it read
    # the three files that end their records with a carriage return alone.
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        buffered: list[list[object]] = []
        try:
            for row in reader:
                buffered.append(list(row))
                if len(buffered) >= HEADER_SEARCH_ROWS:
                    break
        except csv.Error as exc:
            raise ReadError(f"csv parse failed: {exc}") from exc
        index = find_header(buffered, expected_dates)
        if index is None:
            raise NoHeader(buffered)
        header = [str(cell) for cell in buffered[index]]
        yield Table(
            header=header,
            rows=_chain(buffered[index + 1 :], reader),
            encoding=encoding,
            delimiter=delimiter,
            header_row=index,
        )


def _chain(head: list[list[object]], reader) -> Iterator[list[object]]:
    yield from head
    try:
        for row in reader:
            yield list(row)
    except csv.Error as exc:
        raise ReadError(f"csv parse failed partway: {exc}") from exc


@contextmanager
def _open_xlsx(path: Path, expected_dates: tuple[str, ...]) -> Iterator[Table]:
    from openpyxl import load_workbook

    with warnings.catch_warnings():
        # openpyxl warns about print areas and defined names it cannot map.
        # They say nothing about the rows, which is all this reads.
        warnings.simplefilter("ignore")
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            for name in workbook.sheetnames:
                sheet = workbook[name]
                stream = sheet.iter_rows(values_only=True)
                buffered = [
                    list(row) for _, row in zip(range(HEADER_SEARCH_ROWS), stream)
                ]
                index = find_header(buffered, expected_dates)
                if index is None:
                    continue
                header = ["" if cell is None else str(cell) for cell in buffered[index]]
                yield Table(
                    header=header,
                    rows=_chain_xlsx(buffered[index + 1 :], stream),
                    encoding="xlsx",
                    delimiter="",
                    header_row=index,
                    sheet=name,
                )
                return
            raise NoHeader([])
        finally:
            workbook.close()


def _chain_xlsx(head: list[list[object]], stream) -> Iterator[list[object]]:
    yield from head
    for row in stream:
        yield list(row)
