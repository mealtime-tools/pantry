# Pantry

Pantry finds and stores food-product nutrition. It searches the local Coles
and AFCD shards plus a user's own records, and can acquire one product from a
Coles or Woolworths URL, USDA FoodData Central, or Open Food Facts.

```sh
pantry --json search "greek yoghurt"
pantry --json search "greek yoghurt" --remote
pantry --json lookup coles 1047
pantry --json lookup coles 1047 --grams 42 | nutrilog log --input -
pantry add https://www.coles.com.au/product/example-1047
pantry add usda:2476857
pantry add off:0123456789012
pantry delete manual sourdough
```

Nutrients describe the record's `grams`, which every record and result carries
and which is 100 unless `--grams N` asks for another weight. There is no pack
size or serving size. A per-100 mL panel is read as per 100 g and says so in
`basis_note`. Items pipe to Recipes or Nutrilog unchanged.

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

## Development

```sh
uv run pytest -q
uv run --project importers/afcd pytest -q importers/afcd/tests
uv run ruff check src
uv run ruff format --check src
```
