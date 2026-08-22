# Pantry

Pantry finds and stores food-product nutrition. It searches the local Coles
and AFCD shards plus a user's own records, and can acquire one product from a
Coles or Woolworths URL, USDA FoodData Central, or Open Food Facts.

```sh
pantry --json search "greek yoghurt"
pantry --json search "greek yoghurt" --remote
pantry --json lookup coles 1047
pantry add https://www.coles.com.au/product/example-1047
pantry add usda:2476857
pantry add off:0123456789012
```

Manual input is flat JSON. Nutrients describe the whole item when `grams` is
present; without it they describe 100 g:

```sh
printf '%s\n' '{"grams":90,"kcal":335,"protein":45.6,"fat":7.9,"carbs":4.9}' |
  pantry add --input - --id sourdough --name Sourdough
```

Unknown standard nutrients are `null`; zero is returned only when the source
explicitly reported zero. JSON items can be piped directly to Recipes or
Nutrilog.

The ignored `data/coles.jsonl` scrape is irreplaceable. No command writes to
package data. Acquired products go to `$XDG_CONFIG_HOME/pantry` or
`~/.config/pantry`.

Retailer requests are deliberately limited and paced. A block stops the run;
there is no retry, proxy rotation, or CAPTCHA handling.

## Development

```sh
uv run pytest -q
uv run ruff check src
```
