# Pantry

Pantry finds and stores food-product nutrition. It searches the local Coles
and AFCD shards plus a user's own records, and can acquire one product from a
Coles or Woolworths URL, USDA FoodData Central, or Open Food Facts. It can
also hold a retailer catalogue, which is what a price comes from.

```sh
pantry --json search "greek yoghurt"
pantry --json search "greek yoghurt" --remote
pantry refresh umall
pantry --json search tofu --source umall
pantry --json lookup coles 1047
pantry --json lookup coles 1047 --grams 42 | recipes edit "Snack" --input -
pantry add https://www.coles.com.au/product/example-1047
pantry add usda:2476857
pantry add off:0123456789012
pantry delete manual sourdough
```

Nutrients describe the record's `grams`, which every record and result carries
and which is 100 unless `--grams N` asks for another weight. There is no pack
size or serving size. A per-100 mL panel is read as per 100 g and says so in
`basis_note`. An item is a flat record in the shared
[item format](https://github.com/mealtime-tools/nutrients/blob/main/FORMAT.md),
so it pipes unchanged into Recipes, or into whatever tool records what you ate.

Energy is `kcal` and every other nutrient is grams. A panel printing
kilojoules is converted where it is read, so no record holds a `kj`.

Manual input is flat JSON, restated to 100 g before it is stored:

```sh
printf '%s\n' '{"grams":90,"kcal":335,"protein":45.6,"fat":7.9,"carbs":4.9}' |
  pantry add --input - --id sourdough --name Sourdough
```

Unknown standard nutrients are `null`; zero is returned only when the source
explicitly reported zero.

`pantry delete SOURCE ID` removes a record from that store, and only from
there: a shipped shard row is refused, and deleting a correction leaves the
row it shadowed visible again.

The ignored `data/coles.jsonl` scrape is irreplaceable. No command writes to
package data. Acquired products go to `$XDG_CONFIG_HOME/pantry` or
`~/.config/pantry`.

Retailer requests are deliberately limited and paced. A block stops the run;
there is no retry, proxy rotation, or CAPTCHA handling.

## Catalogues

`pantry refresh umall` rebuilds a retailer catalogue: roughly thirty thousand
products with a barcode, pack weight, price and whether it is in stock. It
takes about a minute, always uses the network, and replaces what was there —
a price the store no longer charges is not worth merging forward.

A catalogue is not a shard. It carries no nutrition and is read only when
searched, so it never joins the fan-out over stored records. Until one exists
the provider drops out silently, exactly as an unconfigured one does.

Umall publishes no nutrition panel anywhere, so a catalogue row carries the
barcode a panel could be found by and nothing more. Where a record for that
barcode is already stored, a search joins the two and prices the result:

```sh
pantry add off:8850643003416
pantry --json search "por kwan" --source umall
```

```text
umall:8850643003416  300kcal 7p 40c 13f  $12.69 (5.64/100g)  Por Kwan Pad Thai Sauce 225g
```

A result then carries `price`, `pack_grams`, `price_per_100g`,
`price_per_100kcal`, `price_per_g_protein`, `available` and `price_at`. The
pack weight is `pack_grams` rather than `grams`, because `grams` names the
weight the nutrients describe and `--grams` restates it. Where the pack has no
stated weight — produce sold by the piece — the unit prices are `null` rather
than a division by zero, and a row with no stored panel keeps its `ref` so
`pantry add off:<barcode>` can go and get one.

About seven barcodes in ten identify the product outside the store; the rest
are codes the shop issued to itself and are never looked up, because those
digits belong to some other manufacturer's product.

## Development

```sh
uv run pytest -q
uv run --project importers/afcd pytest -q importers/afcd/tests
uv run ruff check src
uv run ruff format --check src
```
