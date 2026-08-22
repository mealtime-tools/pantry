---
name: pantry
description: Search and acquire food-product nutrition from local retailer data, USDA, Open Food Facts, Coles, and Woolworths.
---

# Pantry

Use `pantry --json search QUERY` locally. Add `--remote` only when local data
does not identify the product. Acquire an exact result with `pantry add URL`,
`pantry add usda:ID`, or `pantry add off:BARCODE`.

Manual records use `pantry add --input FILE|-`. Put whole-item nutrient values
and optional `grams` in one flat object. Without a weight, values are
treated as per 100 g. Pantry does not parse prose.

Unknown output values are `null`. An explicit zero remains zero. Never retry a
retailer block or attempt to defeat bot protection.

JSON items may be piped directly to Recipes or Nutrilog.
