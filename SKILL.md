---
name: pantry
description: Search and acquire food-product nutrition from local data, Umall, USDA, Open Food Facts, Coles, and Woolworths.
---

# Pantry

Start with `pantry --json search QUERY`. This is local, fast, and makes no
network request. Each result carries a `match.score` from 0 to 1 and a
`match.tier`. Below 0.7, treat the answer as weak and try
`pantry --json search QUERY --source umall|woolworths`.

Live shop results carry current price, availability, pack size and URL, and no
nutrition panel. When a result has a `ref`, make the panel permanent with
`pantry add REF --json` and use the stored result. A live result without one
has no supported panel path; do not invent one.

Umall is a plain request. Woolworths needs `pantry[browser]` and opens a
visible Chrome window, so reach for it when the user wants a shelf price, not
to settle a macro question the store can already answer.

Acquire an exact product with one of:

- `pantry add coles:<product-url> --json`
- `pantry add off:<barcode> --json`
- `pantry add usda:<fdcId> --json`
- `pantry add woolworths:<stockcode> --json`

Do not retry a retailer block or bypass bot protection.

Nutrients describe the result's `grams`, always present and 100 unless
`--grams N` on `search` or `lookup` asks for another weight. `pack_grams` is
only the package size of a live offer. Never scale nutrition from
`pack_grams`. A per-100 mL panel is represented on the 100 g basis and states
that compromise in `basis_note`.

`pantry add --input FILE|- --json` accepts one flat JSON object. Its `grams`
is the basis of the supplied figures and defaults to 100. Energy is `kcal`;
all other nutrient values are grams. Pantry does not parse prose and has no
`kj` field.

Use `pantry lookup SOURCE ID --json` for an exact local read. Use
`pantry delete SOURCE ID --json` only for records in the user's store. Shipped
records cannot be deleted.

Unknown output values are `null`. An explicit zero remains zero. Never infer
missing nutrients, a cooked weight, a barcode, or a price.
