---
name: pantry
description: Search and acquire food-product nutrition from local data, Coles, Woolworths, Umall, USDA, and Open Food Facts.
---

# Pantry

Start with `pantry --json search QUERY`. This is local, fast, and makes no
network request. Each store result carries a `match.score` from 0 to 1 and a
`match.tier`. Below 0.7, treat the answer as weak and try
`pantry --json search QUERY --source coles|umall|woolworths`.

Live shop results carry current price, availability, pack size and `url`, and
no nutrition panel. When a result has a `ref`, try to make the panel permanent
with `pantry add REF --json` and use the stored result. A live result without
one has no supported panel path; do not invent one.

A `ref` is a lead, not a promise. `coles:` and `woolworths:` refs address the
shop's own page and resolve whenever the shop does. A `barcode:<barcode>` ref
names a code the retailer printed, which Open Food Facts often does not hold —
of ten such refs from one Umall search, nine were unknown there. Expect that,
report the product as having no panel, and do not type one in to fill the gap.

Coles and Umall are plain requests, under a second. Prefer Coles for an
ordinary supermarket product: Umall stocks a different catalogue and answers
common queries with unrelated rows. Woolworths needs `pantry[browser]` and
opens a visible Chrome window, so reach for it when the user wants that shop's
shelf price, not to settle a macro question the store can already answer.

Coles and Woolworths results have no `match` — the shop's own order is the
ranking, and it resolves words the store cannot, so present them in the order
given and do not re-sort them. Umall results do carry a `match`.

Acquire an exact product with one of:

- `pantry add coles:<product-url> --json`
- `pantry add barcode:<barcode> --json`
- `pantry add usda:<fdcId> --json`
- `pantry add woolworths:<stockcode> --json`

A search result's `ref` is already in one of these forms; pass it through
rather than rebuilding it. Coles allows about four or five page loads in a
burst, and a Coles search spends one of them.

Do not retry a retailer block or bypass bot protection. A refused run is the
answer.

When a shop is blocked, do **not** read its page with another tool and type
the panel into `pantry add --input` under that shop's id or url. A retailer
panel comes from `pantry add` or it does not get stored. Say the shop is
blocked and stop; a record that is wrong is worse than one that is missing.
`--input` is for figures the user gives you, or a label in front of them.

Any record stored through `--input` carries `entered: true` and prints
`~entered`. Treat those figures as unverified: do not present them as the
shop's published panel, and do not build on them without saying so.

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

Where a record has a `barcode`, it is the GTIN the source printed and is how
two sources are joined to the same product. Never derive one from an id.

A join is an identity claim, not corroboration. One live GTIN returns 272 kcal
and 34 g protein from Woolworths and 427 kcal and 28 g from Open Food Facts.
Where two panels disagree, prefer the retailer's and say the figures differ;
never average them. Local search already ranks it that way.
