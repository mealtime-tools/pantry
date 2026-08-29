---
name: pantry
description: Search and acquire food-product nutrition from local retailer data, USDA, Open Food Facts, Coles, and Woolworths, and price it against a refreshed retailer catalogue.
---

# Pantry

Use `pantry --json search QUERY`; add `--remote` only when local data does not
identify the product. Acquire an exact product with `pantry add REF --json`,
where `REF` is a retailer URL, `usda:ID`, or `off:BARCODE`.

Nutrients describe the result's `grams`, always present and 100 unless
`--grams N` on `search` or `lookup` asks for another weight. Pipe the result to
`recipes edit --input -`, or to whatever tool logs intake; never scale by hand. No
pack or serving size is held, so supply the weight you mean. A per-100 mL panel
is reported as per 100 g and says so in `basis_note`.

`pantry add --input FILE|- --json` accepts one flat JSON object whose `grams`
is the weight its nutrients describe, 100 g by default. Pantry does not parse
prose. Energy is `kcal` and every other nutrient is grams; there is no `kj`
key, so state kilojoules as the kcal they convert to.

`pantry refresh umall --json` rebuilds the Umall catalogue: about twenty
thousand priced food rows, a minute of network, replacing whatever was there.
Umall also sells cosmetics and kitchenware; those are excluded by category and
counted as `excluded`, so the catalogue is food and the coverage figures mean
something.
`pantry search QUERY --source umall` then reads it offline. Those results add
`price`, `pack_grams`, `price_per_100g`, `price_per_100kcal`,
`price_per_g_protein`, `available` and `price_at` to the usual keys; every one
of them is `null` where the figure it needs is missing, never zero. Pack
weight is `pack_grams`, never `grams`: `grams` stays the weight the nutrients
describe. Umall states no nutrition, so a row's panel is empty until
`pantry add off:<barcode>` stores one — the row carries that reference in
`ref` when the barcode is one another database could know. Until a refresh has
run, the provider is absent from `sources` rather than an error.

`pantry backfill umall --json` stores Open Food Facts panels for the barcodes
that catalogue lists, by streaming the 1.3 GB export in one pass. Run it after
a refresh; it is the only way to answer tens of thousands of barcodes, since
the public index allows about ten searches a minute. Its report separates
barcodes absent from the export from ones present with no usable panel, and
neither is ever filled in with a guess. Coverage is thin and uneven: about one
joinable barcode in ten stores a panel, and the rate follows where the barcode
was issued — Thailand 29%, Korea 16%, Japan 8%, China 6%, fresh produce nearly
none. Treat a panel as a bonus, not the normal case.

The same pass writes what the export concluded about each ingredient list.
`pantry search --vegetarian` keeps only results it judged vegetarian or vegan;
a result whose `diet` is absent is unknown and never passes. That judgement is
rarer still — 250 of those 25,637 — so this filter answers about a handful of
products, not the catalogue. Umall's own `type` and `tags` cover far more. `--sort` takes
`protein-per-kcal`, `price-per-100g` or `price-per-g-protein`, and a result
lacking the figure a key needs sorts last rather than as a zero.

`pantry delete SOURCE ID --json` removes one record from the user's own
store. A shipped record cannot be deleted, and neither can one that was never
held: both exit 1 with `deleted: false`.

Unknown output values are `null`. An explicit zero remains zero. Never retry a
retailer block or bypass bot protection.
