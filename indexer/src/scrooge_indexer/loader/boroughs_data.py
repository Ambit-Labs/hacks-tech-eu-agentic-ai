"""The 33 London authorities: slug, legal name, ONS code, population.

Population is the ONS mid-2025 estimate, fetched on 2026-09-19 from the NOMIS
API and checked cell for cell against the ONS release spreadsheet. Both routes
returned identical figures for all 33 and their sum, 9,122,909, equals the ONS
figure for the London region E12000007.

Source:  https://www.nomisweb.co.uk/api/v01/dataset/NM_2002_1.data.csv
         ?geography=TYPE424&date=latest&gender=0&c_age=200&measures=20100
Dataset: NOMIS NM_2002_1, "Population estimates - local authority based by
         single year of age" (ONS, table updated 2026-07-29)
Checked: "Estimates of the population for England and Wales",
         edition "Mid-2025: 2023 local authority boundaries", released
         2026-07-29, table MYE2 Persons, column "All ages".
Year:    mid-2025 (30 June 2025 reference date)

The slug is the directory name under data/raw for the 15 boroughs that publish
spend files here, and the same style for the other 18, so adding one later is
a module in `boroughs/` and nothing in this table. The name is the authority's
legal corporate title, which ONS does not publish: ONS writes bare names, and
these carry the borough, royal borough and city styles the councils use
themselves.
"""

from __future__ import annotations

#: slug, legal name, ONS code, mid-2025 population.
LONDON_BOROUGHS: tuple[tuple[str, str, str, int], ...] = (
    (
        "barking-and-dagenham",
        "London Borough of Barking and Dagenham",
        "E09000002",
        238295,
    ),
    ("barnet", "London Borough of Barnet", "E09000003", 408087),
    ("bexley", "London Borough of Bexley", "E09000004", 257103),
    ("brent", "London Borough of Brent", "E09000005", 352201),
    ("bromley", "London Borough of Bromley", "E09000006", 336048),
    ("camden", "London Borough of Camden", "E09000007", 216658),
    ("city-of-london", "City of London", "E09000001", 15631),
    ("croydon", "London Borough of Croydon", "E09000008", 410085),
    ("ealing", "London Borough of Ealing", "E09000009", 387072),
    ("enfield", "London Borough of Enfield", "E09000010", 329400),
    ("greenwich", "Royal Borough of Greenwich", "E09000011", 301225),
    ("hackney", "London Borough of Hackney", "E09000012", 266241),
    (
        "hammersmith-and-fulham",
        "London Borough of Hammersmith and Fulham",
        "E09000013",
        190216,
    ),
    ("haringey", "London Borough of Haringey", "E09000014", 266218),
    ("harrow", "London Borough of Harrow", "E09000015", 272612),
    ("havering", "London Borough of Havering", "E09000016", 280787),
    ("hillingdon", "London Borough of Hillingdon", "E09000017", 326671),
    ("hounslow", "London Borough of Hounslow", "E09000018", 299486),
    ("islington", "London Borough of Islington", "E09000019", 224551),
    (
        "kensington-and-chelsea",
        "Royal Borough of Kensington and Chelsea",
        "E09000020",
        145734,
    ),
    ("kingston", "Royal Borough of Kingston upon Thames", "E09000021", 172761),
    ("lambeth", "London Borough of Lambeth", "E09000022", 314298),
    ("lewisham", "London Borough of Lewisham", "E09000023", 301037),
    ("merton", "London Borough of Merton", "E09000024", 218891),
    ("newham", "London Borough of Newham", "E09000025", 376542),
    ("redbridge", "London Borough of Redbridge", "E09000026", 321829),
    ("richmond", "London Borough of Richmond upon Thames", "E09000027", 196713),
    ("southwark", "London Borough of Southwark", "E09000028", 312366),
    ("sutton", "London Borough of Sutton", "E09000029", 213972),
    ("tower-hamlets", "London Borough of Tower Hamlets", "E09000030", 334240),
    ("waltham-forest", "London Borough of Waltham Forest", "E09000031", 283713),
    ("wandsworth", "London Borough of Wandsworth", "E09000032", 339859),
    ("westminster", "City of Westminster", "E09000033", 212367),
)
