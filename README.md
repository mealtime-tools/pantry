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

`pantry refresh umall` rebuilds a retailer catalogue: roughly twenty thousand
food products with a barcode, pack weight, price and whether it is in stock.
Umall is a general store, so about nine thousand further listings — nappies,
face cream, kitchenware, laundry — are left out by category. None of them can
ever carry a nutrition panel, and holding them makes every coverage figure
describe a denominator that is a quarter shopfitting. A category the store
adds later counts as food until it is named, so nothing is silently lost. It
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

## Backfill

`pantry backfill umall` gives those barcodes their panels, from one of two
Open Food Facts exports. Either way it is a bulk read rather than a lookup
loop: the public index allows about ten searches a minute, so asking for
seventeen thousand barcodes one at a time would take days.

`--from parquet`, the default, downloads the whole database once — about
7.8 GB — into `$XDG_CACHE_HOME/pantry/open-food-facts` and queries it with
DuckDB. It is the better source for two reasons beyond size. Names are kept
per language, so a product sold here under only a Japanese name still stores;
the CSV leaves `product_name` empty for those and the record is lost. And the
ingredient analysis arrives as a list of tags rather than one joined string,
so matching `en:vegan` cannot accidentally match `en:vegan-status-unknown`.

The file is not queried where it sits. Hugging Face rate-limits the hundreds
of small range requests a remote parquet read makes and refuses the read
partway through, so it is fetched in one sequential download and kept. A
second backfill, or any other question, then costs nothing. Delete the file
to reclaim the space; it is a cache.

`--from csv` streams the 1.3 GB English export instead, writing nothing to
disk. Use it when the space matters more than the coverage.

Coverage is thin, and the report says so rather than hiding it. Measured
against the live food catalogue: 17,973 joinable barcodes, of which 3,518 hold
a usable panel — about one in five.

Most of that came from choosing the parquet over the CSV, and not in the way
expected. The two agree closely on which barcodes exist — 4,304 against 4,043
— but the CSV reports no nutrition at all for 2,255 of its matches where the
parquet has a panel for most of them. Its flattened `*_100g` columns are far
sparser than the nutriments the database actually holds, so `--from csv`
stores 1,735 panels where `--from parquet` stores 3,443.

The gaps are not random. Coverage tracks where the barcode was issued, because
Open Food Facts is thinnest on the Asian market this shop sells: Thailand 29%,
Korea 16%, Japan 8%, China 6% — and China is over half the catalogue. Fresh
produce is nearer zero, since it carries codes the shop issued to itself that
no other database knows. It distinguishes the two ways a barcode can fail — absent from
the export, or present with no usable panel — because the export is
community-maintained and carries rows stating things like 6380 kcal per 100 g.
Those are dropped, never stored, and never allowed to end the download.

The same pass records what the export concluded from each ingredient list,
into `openfoodfacts.diet.json` beside the records. That is neither a nutrient
nor a retailer's fact, so it is neither in a record nor in a catalogue: the
same barcode means the same thing whoever sells it. `--vegetarian` filters on
it, and passes only a row the export judged — unknown is never a pass.

```sh
pantry refresh umall
pantry backfill umall
pantry --json search tofu --source umall --vegetarian --sort protein-per-kcal
```

`--sort` takes `protein-per-kcal`, `price-per-100g` or `price-per-g-protein`.
A result missing the figure a key needs sorts last rather than as a zero:
nothing known is not the same as none of it.

## Development

```sh
uv run pytest -q
uv run --project importers/afcd pytest -q importers/afcd/tests
uv run ruff check src
uv run ruff format --check src
```
