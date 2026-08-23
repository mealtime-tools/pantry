---
name: pantry
description: Search and acquire food-product nutrition from local retailer data, USDA, Open Food Facts, Coles, and Woolworths.
---

# Pantry

Use `pantry --json search QUERY`; add `--remote` only when local data does not
identify the product. Acquire an exact product with `pantry add REF --json`,
where `REF` is a retailer URL, `usda:ID`, or `off:BARCODE`.

`pantry add --input FILE|- --json` accepts one flat JSON object. Nutrients
describe the whole item when `grams` is present, or 100 g otherwise. Pantry
does not parse prose.

Unknown output values are `null`. An explicit zero remains zero. Never retry a
retailer block or bypass bot protection. JSON items can be piped to Recipes or
Nutrilog.
