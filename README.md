# pantry

Food product records — per 100 g, always — with local fuzzy search, Open Food
Facts discovery, and a CLI to add the products that are missing.

Four verbs over four providers: `search` fans out, `lookup` is exact and
offline, `add` acquires from whichever provider claims the reference, and
`annotate` records what a held panel's figures are measured against.

Pantry owns food data and nothing else: the records, the search over them, the
sources they come from, and the commands that add new ones. Recipe arithmetic
lives elsewhere.

## Install

```sh
uv sync --project .
uv run --project . pantry --help
uv run --project . pantry skill install   # so agents can discover it
```

## Use

```sh
pantry --json search "greek yogurt" --limit 5
pantry --json search "chobani greek yogurt plain" --remote
pantry --json lookup coles 1047
pantry add "https://www.coles.com.au/product/example-1047"
pantry add usda:2476857
pantry add --manual --id sourdough --name Sourdough < panel.txt
pantry annotate coles 98548 --basis as_prepared --basis-note "per 100 mL"
pantry guide            # the full agent-facing manual, no network needed
```

`pantry guide` is the manual. `SKILL.md` is the agent-facing contract. Neither
is restated here.

## Data

The canonical per-source shards live in a directory Pantry only ever reads.
`coles.jsonl` is a frozen, irreplaceable 10,297-row scrape; nothing in this
package rewrites it. Point `PANTRY_DATA_DIR` at another copy if you keep it
somewhere else.

The user's own records go under `$XDG_CONFIG_HOME/pantry` (or
`~/.config/pantry`), in the same layout the frozen data ships in: one
`<source>.jsonl` shard per source. No command writes into a checkout;
promoting a record into one is a deliberate copy a human diffs and commits.

No credential is needed to build, test or run. A `USDA_API_KEY` in the
environment enables the USDA source; without one it is skipped silently.

### Record contract

Nutrients are per 100 g of the product **as sold**. Consumers scale by
`grams / 100`; Pantry never stores a pre-scaled nutrient. Every figure is
grams except `sodium`, which is **milligrams** per 100 g, the unit every
nutrition panel prints that row in — the one key whose unit differs from its
neighbours, so read it as mg and never as grams. Identity is `(source, id)`,
with source-native string
ids normalised at ingress. Pantry supports `coles`, `woolworths`, `afcd`,
`usda`, `manual`, and `openfoodfacts`.
Recipes deliberately accepts only its documented resolvable subset.

Two things a consumer must not guess at, then: the unit sodium is in, and what
the figures were measured against. The as-sold basis holds unless the record
carries `basis`, which is `as_sold` or `as_prepared`. Absent means `as_sold`:
the frozen shards predate the key and are never rewritten to carry a default,
so a consumer that has never heard of it keeps today's behaviour. An
`as_prepared` panel was printed for the made-up food, so scaling it by a dry
weight is wrong by whatever the preparation adds — 47x for a stock cube.
`basis_note` is the free text that says how to convert instead, such as "per
100 mL prepared; 1 cube (10.5 g) makes 500 mL", and it needs a `basis` beside
it: a note alone would leave the record structurally claiming as-sold. Both
keys are surfaced by `lookup` and `search`, human output and `--json` alike.

An unrecognised `basis`, an empty `basis_note` and a note without a basis are
all refused when a record is written. An unrecognised `basis` is refused when
one is *read*, too — the one place this key is checked and the numbers are
not, because every other malformed figure is loud downstream while an
unrecognised basis reads as absent, and absent means as-sold. The note rules
stay on the write path: an empty note, or one with no basis, is already
visible in `lookup` and `search` output, and failing a whole shard over a
mistake a reader can see would take every other row down with it.

`annotate` sets both fields on a record already held, without re-authoring its
panel, and `add --refresh` carries them across — no provider can put back a
field only a human could supply. It checks shape rather than plausibility: an
edit in place re-measures nothing, and 141 frozen rows fail today's nutrition
rules, disproportionately the dry goods whose basis most needs recording.

JSONL keys have this fixed order, because a one-product edit must remain a
one-line diff:

```
source id name brand kj fat carbs protein fiber sugar sodium kcal basis
basis_note url serving_size serving_unit total_size total_unit
```

Optional missing keys are omitted. `sodium` is optional and never inferred: the
frozen shards were written before the key existed and mostly lack it, so an
absent sodium is unknown, not zero. Unknown keys are preserved after known
ones. Every shard omits `source` because the filename supplies it, in the
shipped data and the user's store alike. Records sort by source order, then
id.

Id ordering is a key, never a comparator: digit ids use `(0, len, value)` and
other ids use `(1, 0, value)`. Digits sort first, length before codepoint, and
leading zeroes stay distinct. This avoids the non-transitive mixed-id
comparator that made output depend on input order.

Canonical JSON uses a JavaScript-compatible float formatter. ECMAScript uses
exponential notation only below decimal exponent -6 or at least 21 and renders
integral floats without `.0`; Python's defaults differ at both ends. The
formatter is part of the record format, not presentation.

### Frozen data

`data/coles.jsonl` is an irreplaceable 10,297-row scrape with sha256
`9d8eaa3b32f9775006e36710cfcf323a011c8a6b0aa48736db67d10d0bc8d7f6`.
`data/afcd.jsonl` has 1,588 rows and sha256
`53938eec2e627db56666df8abca04f6bc1dca844fb8decbfea32cfaa762d775a`. Neither
carries `sodium`; backfilling the AFCD rows is its importer's job, not a
migration.
Tests pin the counts, checksums, and byte-for-byte re-serialization.

One Coles row contains `0.00001`: Python normally writes `1e-05`, which is why
a parse-and-dump migration would corrupt the frozen bytes while appearing
semantically equal. No command rewrites these shards. A fetched product already
held is never fetched again; malformed nutrition is refused; missing values are
never inferred as zero; `--zero-calorie` conflicts with any non-zero nutrient.
Search may display a numeric convenience shape, but those values are never
accepted as stored facts without resolving the source record.

Runtime additions go only to XDG storage, never into a checkout. A stored
row shadows the base row with the same `(source, id)` and nothing more, so a
`coles.jsonl` in the store cannot stand in for the shipped shard.

Acquisition never defeats bot protection: no captcha solving, proxy rotation,
fingerprint spoofing, or retry-until-success. A block ends the session. Page
budgets are claimed before requests, refused requests still count, and the
default pace between requests is three seconds.

## Develop

```sh
uv run --project . pytest -q
uv run --project importers/afcd pytest -q importers/afcd/tests
uvx ruff check src --line-length 79
```

No test touches the network, launches a browser, or writes outside its
temporary directory. The HTTP transport, the clock and the store are all
injected for exactly that reason.
