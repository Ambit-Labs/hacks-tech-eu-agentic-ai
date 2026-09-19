"""Newham: the label decides the month and the format, the slug decides nothing."""

from __future__ import annotations

import logging

import httpx

from spend_indexer.boroughs.newham import Newham, clean_label

#: Ten links trimmed from the live page on 2026-09-19, keeping every shape
#: that makes the slug untrustworthy.
LANDING = """
<html><body>
  <a href="/downloads/file/11423/payments-to-suppliers-august-2026-excel-">Payments to suppliers August 2026 (Excel)</a>
  <a href="/downloads/file/11422/payments-to-suppliers-august-2026-csv-">Payments to suppliers August 2026 (CSV)</a>
  <a href="/downloads/file/11421/staff-purchase-card-expenses-august-2026-csv-">Staff Purchase Card Expenses August 2026 (CSV)</a>
  <a href="/downloads/file/11325/payments-to-suppliers-july-2026-csv-">Payments to suppliers July 2026 (CSV)</a>
  <a href="/downloads/file/1289/paymentstosuppliersfebruary-csv-">Payments to suppliers February 2020 (CSV)</a>
  <a href="/downloads/file/421/paymentstosuppliersdecember2019-csv-">Payments to suppliers ​December 2019 (CSV)</a>
  <a href="/downloads/file/376/paymentstosuppliersjuly2018">Payments to suppliers June 2018 (CSV)</a>
  <a href="/downloads/file/398/paymentstosuppliersfebruary2019">Payments to suppliers February 2019 (Excel)</a>
  <a href="/downloads/file/398/paymentstosuppliersfebruary2019">Payments to suppliers February 2019 (CSV)</a>
  <a href="/downloads/file/10756/contract-register-for-council-s-website-13042026">View our contract register (Excel)</a>
  <a href="/downloads/file/8935/invoice-payment-performance-data">Invoice Payment Performance Data (PDF)</a>
  <a href="/downloads/file/9999/payments-to-suppliers-latest-csv-">Payments to suppliers (CSV)</a>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


def test_discovery_maps_a_month_to_an_id(client_for):
    files = Newham().discover(client_for(landing_handler), None, None)
    assert [f.period for f in files] == [
        "2018-06",
        "2019-02",
        "2019-12",
        "2020-02",
        "2026-07",
        "2026-08",
    ]
    assert all(f.format == "csv" for f in files)
    assert all(f.borough == "newham" for f in files)


def test_the_slug_is_not_trusted_for_the_month(client_for):
    """``/downloads/file/376/paymentstosuppliersjuly2018`` is the June file.

    Reading the month off the slug here would put June's payments under July
    and leave June looking unpublished.
    """
    files = {
        f.period: f.url
        for f in Newham().discover(client_for(landing_handler), None, None)
    }
    assert files["2018-06"].endswith("/376/paymentstosuppliersjuly2018")
    assert "2018-07" not in files


def test_a_slug_with_no_year_still_gets_one_from_the_label(client_for):
    files = {
        f.period: f.url
        for f in Newham().discover(client_for(landing_handler), None, None)
    }
    assert files["2020-02"].endswith("/1289/paymentstosuppliersfebruary-csv-")


def test_the_excel_twin_is_not_taken(client_for):
    """Every month is published twice. Taking both would double every period."""
    files = {
        f.period: f.url
        for f in Newham().discover(client_for(landing_handler), None, None)
    }
    assert files["2026-08"].endswith("/11422/payments-to-suppliers-august-2026-csv-")
    assert not any("excel" in url for url in files.values())


def test_a_month_whose_two_links_share_one_id_is_still_found(client_for):
    """February 2019's CSV and Excel links point at the same download id.

    The Excel label comes first in the page, so keeping only the first anchor
    for a URL leaves that month looking like a spreadsheet twin and drops it.
    """
    files = {
        f.period: f.url
        for f in Newham().discover(client_for(landing_handler), None, None)
    }
    assert files["2019-02"].endswith("/398/paymentstosuppliersfebruary2019")


def test_the_purchase_card_file_is_a_different_dataset(client_for):
    files = Newham().discover(client_for(landing_handler), None, None)
    assert not any("purchase-card" in f.url for f in files)


def test_the_register_and_the_performance_pdf_are_not_months(client_for):
    files = Newham().discover(client_for(landing_handler), None, None)
    assert all("/downloads/file/" in f.url for f in files)
    assert not any("contract-register" in f.url for f in files)
    assert not any("invoice-payment" in f.url for f in files)


def test_a_zero_width_space_does_not_hide_a_month(client_for):
    """The labels are full of them, and they are not whitespace."""
    assert clean_label("Payments to suppliers ​December 2019 (CSV)") == (
        "Payments to suppliers December 2019 (CSV)"
    )
    periods = {
        f.period for f in Newham().discover(client_for(landing_handler), None, None)
    }
    assert "2019-12" in periods


def test_an_undated_link_is_counted_not_guessed_at(client_for, caplog):
    with caplog.at_level(logging.WARNING, logger="spend_indexer.boroughs.newham"):
        Newham().discover(client_for(landing_handler), None, None)
    assert "skipped 1 supplier payment link(s)" in caplog.text


def test_discover_honours_since_and_until(client_for):
    files = Newham().discover(client_for(landing_handler), "2019-01", "2020-12")
    assert [f.period for f in files] == ["2019-02", "2019-12", "2020-02"]


def test_the_filename_stays_the_publishers_own(client_for):
    files = Newham().discover(client_for(landing_handler), "2026-08", "2026-08")
    assert files[0].filename == "payments-to-suppliers-august-2026-csv-"
