---
name: pantry
description: Search local food product records or Open Food Facts by product text, look one up by exact identity, add a product from a retailer page, a USDA fdcId, a barcode or a pasted label. Use for source-owned per-100-g product nutrition, not recipe arithmetic or meal logging.
---

# Pantry

Use the installed `pantry` CLI for food-product data. Every nutrient in every
record is **grams per 100 g** — one rule, no exceptions; scale by
`grams / 100` at the point of display. An absent nutrient is unknown, never
zero.

Per 100 g **as sold**, unless the record carries `basis`. `basis` is `as_sold`
or `as_prepared`, and absent — almost every record — means `as_sold`. An
`as_prepared` panel was printed for the made-up food, so `grams / 100`
against a weight the user handles is wrong by whatever the preparation adds:
47x for a stock cube dissolved in 500 mL of water. Never scale such a record
by a dry weight. Read `basis_note`, which carries the conversion in free text
("per 100 mL prepared; 1 cube (10.5 g) makes 500 mL"), do the arithmetic from
that, and say which basis you used. Both keys appear in `search` and `lookup`
output only when the record carries them.

Identity is the pair `(source, id)`. Sources are `coles`, `woolworths`, `afcd`,
`usda`, `openfoodfacts`, `manual`. Ids are source-native
strings compared exactly — leading zeros are significant, and no id carries a
source prefix. Keep both halves of any result you intend to reuse.

Three verbs: `search`, `lookup`, `add`.

`--json` makes stdout exactly one JSON object and is accepted before or after
the subcommand. It applies to all three. Never parse the human output.

## Providers

| name | does | credential |
| --- | --- | --- |
| `local` | search the frozen shards and your own | none, never a request |
| `openfoodfacts` | search the public index, `add off:<barcode>` | none |
| `usda` | `add usda:<fdcId>` | `$USDA_API_KEY`, `.env`, or `--api-key` |
| `retailer` | `add <coles/woolworths url>` | none |

Keys are read from the environment and never printed. A provider with no
credential is **skipped silently** — unconfigured is not a failure, and it is a
different outcome from unreachable, which is exit 2.

## Exit codes

| code | meaning |
| --- | --- |
| 0 | success, including a search that found nothing |
| 1 | usage error: bad flags, unparseable input, refused declaration, missing credential, spent budget |
| 2 | remote error: network, API, or a site refusal (never retried) |
| 3 | assertion failure |
| 4 | data-quality warning escalated by `--strict` |

Pantry returns 0, 1 and 2; 3 and 4 are reserved by the shared convention. An
exhausted page budget is 1: a refusal you can lift with `--budget`, not a
remote failure.

Every `--json` response is one object carrying a single `ok` key:

```json
{"ok": true,  "data":  {...}}
{"ok": false, "error": {"message": "..."}}
```

Branch on `ok`, including for a malformed flag, which is reported in the same
shape. `ok` says the response carries data rather than an error; it is not a
mirror of the exit code. A `lookup` miss is `ok:true` with `found:false` and
exit 1, because "not held" is an answer.

## Search

```sh
pantry --json search "greek yogurt" --limit 10
```

`data` is `{"query":...,"sources":["local"],"results":[...]}`, exit 0 even when
`results` is empty. **Local only by default**: a network call has a cost you
should opt into, so remote providers answer only under `--remote`. `--source
NAME` restricts to one provider and repeats; `--limit` applies per provider;
`sources` names the providers that answered, so a silently skipped one is
visible. Do this before anything remote, every time.

Each result is `{"id","name","title","nutrients":{...},"serving":{"size",
"unit"},"url","source"}`, plus `basis` and `basis_note` when the record carries
them. `nutrients` always carries `kcal`, `protein`, `fat` and `carbohydrates`,
missing ones as 0. Every other nutrient — `dietary_fiber`, `sodium`, `sugar`,
`saturated_fat` and the rest of the shared vocabulary — appears only when the
record holds it, because a defaulted 0 would read as a product free of that
nutrient rather than one that never stated it. Check for the key before
reading it. Stored keys are the canonical names, which are the Google Health
API's lowercased, so read `carbohydrates` and `dietary_fiber` and not `carbs`
or `fiber`; what you *write* may use any spelling a label does. `serving` may
be `{}`, and `url` is absent when the record has none. This is a search-result shape, not a stored record.

## Exact lookup

```sh
pantry --json lookup coles 1047
```

Found: exit 0, `data` is
`{"found":true,"source":"coles","id":"1047","product":{...}}` where `product`
is the stored record. Miss: exit **1**, `data` is
`{"found":false,...,"product":null}` with `ok` still true. **This command never
touches the network.** Never use a bare id, and never add remotely to answer a
lookup.

## Discovery, when nothing is held

```sh
pantry --json search "brand cultured soy block" --remote --source openfoodfacts
```

Community data: **candidates**, not proof of current retailer availability.
Results are tagged `"source":"openfoodfacts"`. A search result is not held, so
`lookup` finds it only after `add off:<barcode>` keeps it. Query rules, in order of importance:

- Start with the user's own distinctive words. Phrase boosting is already on.
- Lucene syntax works, but `AND`, field clauses and quoted phrases are strict
  filters. Never lead with them, and never read a filtered miss as absence.
- Avoid `product_name:`; the deployed index handles it unreliably.
- Never filter by country. Imported stock and incomplete community metadata
  make geography an unsafe identity constraint. Compare returned quantity and
  metadata after searching instead of excluding candidates beforehand.
- On a miss, replace only the category term with one plausible synonym at a
  time, keeping every user-supplied brand, size, dietary, form and variant
  qualifier. Prefer separate searches to a large `OR` so a failure stays
  attributable. Do not add qualifiers the user did not give.
- Stay under Open Food Facts' limit of ten searches a minute. A successful
  search is reused for 24 hours from a disposable cache, so a repeat is free.
- Result order is not identity evidence. If more than one candidate still fits,
  show the differences and ask the user to choose before adding.

If Open Food Facts cannot identify it, use indexed web search to find an
authoritative page. Do not use a fetcher or scraper for discovery.

## Add one record

```sh
pantry add "https://www.woolworths.com.au/shop/productdetails/581176/example"
pantry add usda:2476857
pantry add off:0123456789012
pantry add --manual --id sourdough --name "Sourdough" --brand "Local Bakery" <<'PANEL'
             Per serve  Per 100g
Energy       590kJ      1000kJ
Protein      5.6g       9.5g
Fat, Total   2.0g       3.4g
Carbohydrate 23.1g      39.2g
PANEL
```

The reference decides the provider. `data` is `{"stored":bool,"reason":
"stored"|"held"|"unchanged","source","id","product":{...},"changes":[...],
"notes":[...]}`.

- The local store is checked **before** anything is spent; a held record is
  `reason:"held"` at exit 0 and no request is made.
- A record that parses is persisted immediately, before anything else in the
  run can fail.
- `usda` nutrients are read per 100 g from `foodNutrients`. The per-serving
  `labelNutrients` panel is deliberately ignored: reading it would under-report
  by the ratio of serving size to 100 g, silently.
- `off:<barcode>` is stored under source `openfoodfacts`, with the Open Food
  Facts page as its url. It keeps its own provenance rather than being filed
  as `manual`: that would claim you read it off a label, and your own entry
  for the same barcode would silently overwrite it. Treat it as
  community-maintained data, not proof of current availability.
- `--manual` reads the panel from stdin and never touches the network. It needs
  `--id` and `--name`; `--brand`, `--serving "59g"` and `--total "450g"` are
  optional. Given a retailer url it keeps that identity. Two-column labels are
  handled: the per-100 g column wins, which is the last column unless the
  header names "per 100 g" first.
- `-n NAME=VALUE`, repeatable, states a row outright instead of pasting a
  panel: `-n energy=23kJ -n sodium=1775mg`. Nothing is inferred from layout —
  no column to pick, no row to find in a line — so prefer it when the figures
  are already known. Absent rows stay absent, as always.
- A row printed in milligrams is converted to the grams a record holds, so
  `Sodium 400mg` and `Sodium 0.4g` both store `0.4`, and a trace bound stores
  the bound. Any nutrient beyond the four macros **must** state its unit: the
  macros are only ever printed in grams, but `Sodium 355` is a guess between
  two answers 1000 times apart, so it is refused rather than guessed. A `Salt` row is not read at all — salt is 2.5 times its sodium. A
  `Sodium` row must open its line and be followed by its figure, which is what
  keeps `Sodium Bicarbonate (500)` in an ingredient list from becoming a
  figure for anything. A row that does not match is absent from the record
  rather than guessed at, and nothing warns about it.
- `--basis as_prepared` with `--basis-note "per 100 mL prepared; 1 cube
  (10.5 g) makes 500 mL"` records that the panel is not on an as-sold basis.
  `--basis-note` needs `--basis`, and both need `--manual`: no retailer page or
  API response declares a basis, so reading one there would store a claim no
  source made. Use them whenever a label computes its figures on added
  water — a serving size like `300 g (100 g stick + 200 mL water)`, or a
  column headed "per 100 mL prepared".

## Adding a record that is already held

Adding an identity the store already holds keeps every field the new reading
does not state — `--manual` and `--refresh` alike. So to record the basis of a
held record, add it again with `--basis`: its pack size, url and unmentioned
rows survive the paste. For a retailer record pass its url rather than `--id`,
which is what keeps the identity. The same rule is why no provider can drop a
`basis` a human supplied.

Nothing removes a field. Correcting one means restating it, and blanking a
note means `--basis-note ""`. A record whose panel today's rules would
refuse — 141 frozen Coles rows, mostly dry goods — cannot be re-added at all
without fixing its figures first.

There is no age-based refresh. `--refresh` requires the identity to be held
already, reports `changes`, and leaves the store untouched when nothing
changed or the load failed.

## What a retailer page costs

- `--budget N` (default 4) is claimed before the request and counted even when
  the request was refused, because the site served it either way. Requests are
  paced 3000 ms apart.
- Every run says what it spent: a `used N of M page loads this run` line, or
  `notes` under `--json`, or appended to the error message on a failure.
  Preserve it when reporting.
- **A block ends the session permanently.** Never retry, change user agent,
  rotate proxies, solve a captcha, or lower pacing. Later loads in the same run
  are refused without spending anything. The answer to a block is
  `pantry add --manual`, which keeps the retailer identity.
- `--browser` is an explicit local-Chrome fallback the user asks for. It is
  never an automatic response to a block.
- Nothing walks or searches a retailer catalogue.

## Never infer zeros

A missing, malformed or unreadable nutrition value is **refused**, not coerced
to 0. An inferred zero silently under-counts every recipe downstream. Do not
work around a refusal by supplying zeros.

The one exception is `--zero-calorie`, which accepts only an absent or all-zero
panel and is refused the moment an energy-bearing value is non-zero. A
calorie-free nutrient is exempt: sodium carries no energy, so table salt is a
genuine 0 kcal record with 38.758 g of it. `sugar` is not exempt — a zero
energy printed beside a sugar figure is a half-parsed panel.

A record is also refused for: no usable energy, more energy than pure fat
(900 kcal/100 g), a negative or non-finite figure, more than 100 g of any
nutrient per 100 g, three macros totalling more than 105 g per 100 g, macros
that cannot account for the stated energy, a nutrient name outside the
vocabulary, or a `basis` that is neither `as_sold` nor `as_prepared`.

The energy check is `protein × 4 + fat × 9 + carbohydrates × 4` against the
stated calories, within 15% under or 10% over. It catches two columns read
from two different places, where every figure is plausible on its own. It also
refuses the foods Atwater under-counts by design — dried legumes, whose fibre
an AU label excludes from carbohydrate, and anything alcoholic. 635 of the
11,885 bundled rows are in that class, which is why the check runs only on the
way in and never over the frozen data. Do not work around it by editing
macros; correct the energy figure or leave the product out. The basis is the one of those also
checked when a record is **read**: an unrecognised value would read as absent,
and absent means as-sold. `basis_note` is free text and is not checked at all;
a shard is never failed over a mistake you can see in `lookup`.

## Storage

Everything added writes immediately under `$XDG_CONFIG_HOME/pantry`, or
`~/.config/pantry`. The layout is the one the bundled data ships in: one
`<source>.jsonl` shard per source, each row taking its source from the
filename rather than repeating it.

Search merges the two halves, and a stored row replaces only the base row
with the same `(source, id)` — a `coles.jsonl` in the store never stands in
for the bundled shard. **No command writes into a checkout.**

Deterministic, one shard per source, validated in full before the first write.
It refuses malformed nutrition, identity collisions, and the loss of any base
record. Only then may a human copy intentional changes into a repository.

## Freshness

A local hit is not a claim of current retailer availability. The Coles shard is
a frozen, irreplaceable 10,297-row scrape; AFCD data is Release 3; a retailer
row you hold reflects only its last successful add or explicit refresh. Say so
when freshness matters.

## Other commands

`pantry guide` prints this contract from inside the binary, with no network.
`pantry skill install|uninstall|status` manages this skill file.
