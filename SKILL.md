---
name: pantry
description: Search and acquire food-product nutrition from local retailer data, USDA, Open Food Facts, Coles, and Woolworths.
---

# Pantry

Use `pantry --json search QUERY`; add `--remote` only when local data does not
identify the product. Acquire an exact product with `pantry add REF --json`,
where `REF` is a retailer URL, `usda:ID`, or `off:BARCODE`.

Nutrients describe the result's `grams`, always present and 100 unless
`--grams N` on `search` or `lookup` asks for another weight. Pipe the result to
`recipes edit --input -` or `nutrilog log --input -`; never scale by hand. No
pack or serving size is held, so supply the weight you mean. A per-100 mL panel
is reported as per 100 g and says so in `basis_note`.

`pantry add --input FILE|- --json` accepts one flat JSON object whose `grams`
is the weight its nutrients describe, 100 g by default. Pantry does not parse
prose. Energy is `kcal` and every other nutrient is grams; there is no `kj`
key, so state kilojoules as the kcal they convert to.

`pantry delete SOURCE ID --json` removes one record from the user's own
store. A shipped record cannot be deleted, and neither can one that was never
held: both exit 1 with `deleted: false`.

Unknown output values are `null`. An explicit zero remains zero. Never retry a
retailer block or bypass bot protection.
