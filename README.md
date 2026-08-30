# Pantry

Pantry finds and stores food-product nutrition. The local store is permanent;
shop prices and availability are live search results and are never cached or
written to a product record.

```sh
pantry --json search "greek yoghurt"
pantry --json search tofu --source umall
pantry --json search "bega high protein cheese" --source coles
pantry add off:9323536800014
pantry add coles:https://www.coles.com.au/product/bega-cheese-tasty-protein-grated-250g-7699284
pantry add woolworths:769526
pantry add usda:2476857
pantry --json lookup coles 7699284
pantry delete manual sourdough
```

Local search reads the shipped shards and everything previously added. If it
does not identify the product, `--source` makes a live request to one shop and
returns current offers with `price`, `currency`, `pack_grams`,
`price_per_100g`, `available`, `url`, and a `ref`.

No shop's search carries a nutrition panel, so live results have `null` macros
and a `ref` naming where the panel is. Adding that ref fetches and stores a
separate nutrition record; price and availability stay live-result fields and
are never copied into it.

- `--source coles` is a plain request, about 0.5s. The results page is
  server-rendered, so nothing here needs a browser. It spends one of the four
  or five page loads Coles serves in a burst, so one query is one request. The
  result's ref is `coles:<url>`.
- `--source umall` is a plain request, about 0.6s. Where a product publishes
  an external barcode the result's ref is `off:<barcode>`.
- `--source woolworths` needs a browser and opens a visible window: the
  results page carries no products, and the request behind it is refused for
  anything that is not a browser, headless included. Install it with
  `pantry[browser]`. About 4s to start, then 2-6s a query in the same run.
  The result's ref is `woolworths:<stockcode>`, and its `barcode` is the GTIN
  the page prints.

Coles and Woolworths results keep the shop's own order and carry no `match`.
Their relevance engines know their catalogues and their shoppers' words —
asked for "shredded cheese" they answer with the grated ones — and rescoring
that on shared words dropped right answers and marked others weak.

Umall is the exception, and it is ranked here. Its endpoint is a suggest
index, not a relevance engine: measured, "shredded cheese" returns one cheese
followed by taro strips, lychees and scallops. So those results are ranked and
filtered like the store's, and they do carry a `match`.

## Records and matching

Every nutrient describes the record's `grams`, always present and 100 unless
`--grams N` on `search` or `lookup` asks for another weight. `pack_grams` is a
live offer's package size and never changes that nutrition basis. A per-100 mL
panel is read as per 100 g and says so in `basis_note`.

An item is a flat record in the shared
[item format](https://github.com/mealtime-tools/nutrients/blob/main/FORMAT.md).
Energy is `kcal`; every other nutrient is grams. Kilojoules are converted when
a panel is read, so no stored record has a `kj` field. Unknown nutrients are
`null`; zero is returned only when the source explicitly reported zero.

A ranked result carries `match` — every store result, and every Umall result:

- `score` is 0 to 1 and states how much of the query the name accounted for.
- `tier` is the source kind: `verified`, `composition`, `crowdsourced`,
  `retail`, or `unknown` for a price-only shop result.

Below 0.7 the human output marks a result `~weak`. That is the cue to try a
live shop rather than silently accepting the local answer. A cooked or
water-diluted panel never outranks a dry record. Regional spellings are one
food, not two: `shredded`/`grated`, `prawn`/`shrimp`, `yoghurt`/`yogurt`.

`--sort protein-per-kcal` can reorder nutrient-bearing results. A result that
lacks a required figure sorts last rather than being treated as zero.

## Adding and maintaining records

`pantry add REF` accepts these forms:

- `coles:<product-url>`
- `woolworths:<stockcode>`
- `off:<barcode>`
- `usda:<fdcId>`

Bare Coles and Woolworths product URLs remain accepted. A held record is not
fetched again unless `--refresh` is explicit. Retailer requests are limited
and paced; a block stops the run, with no retry, proxy rotation, or CAPTCHA
handling.

Manual input is one flat JSON object. Its figures are restated to 100 g before
storage:

```sh
printf '%s\n' '{"grams":90,"kcal":335,"protein":45.6,"fat":7.9,"carbs":4.9}' |
  pantry add --input - --id sourdough --name Sourdough
```

`pantry lookup SOURCE ID` reads one exact local record without a network
request. `pantry delete SOURCE ID` removes only a record from the user's own
store. Shipped shard rows cannot be deleted; removing a user correction makes
the shipped row it shadowed visible again.

No command writes package data. Acquired records go to
`$XDG_CONFIG_HOME/pantry` or `~/.config/pantry`.

## Development

```sh
uv run pytest -q
uv run --project importers/afcd pytest -q importers/afcd/tests
readability check src --fix
```
