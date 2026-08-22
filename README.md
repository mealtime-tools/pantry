# pantry

Food product records — per 100 g, always — with local fuzzy search, Open Food
Facts discovery, and a CLI to add the products that are missing.

Three verbs over four providers: `search` fans out, `lookup` is exact and
offline, and `add` acquires from whichever provider claims the reference.

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

Nutrients are grams per 100 g — one rule, no exceptions. Consumers scale by
`grams / 100`; Pantry never stores a pre-scaled nutrient or a second unit. An
absent nutrient is unknown, never zero. Identity is
`(source, id)`, with source-native string ids normalised at ingress. Pantry
supports `coles`, `woolworths`, `afcd`, `usda`, `manual`, and
`openfoodfacts`.
Recipes deliberately accepts only its documented resolvable subset.

Nutrients are per 100 g of the product **as sold** unless the record carries
`basis`, which is `as_sold` or `as_prepared`. Absent means `as_sold`: the
frozen shards predate the key and are never rewritten to carry a default, so a
consumer that has never heard of it keeps today's behaviour. An `as_prepared`
panel was printed for the made-up food, so scaling it by a dry weight is wrong
by whatever the preparation adds — 47x for a stock cube. `basis_note` is the
free text that says how to convert instead, such as "per 100 mL prepared;
1 cube (10.5 g) makes 500 mL", and it needs a `basis` beside it: a note alone
would leave the record structurally claiming as-sold. Both keys are surfaced
by `lookup` and `search`, human output and `--json` alike.

An unrecognised `basis` is refused when a record is written and when one is
*read* — the one place this key is checked and the numbers are not, because
every other malformed figure is loud downstream while an unrecognised basis
reads as absent, and absent means as-sold. `basis_note` is free text and is
not checked: a note a reader can see in `lookup` output is not worth failing
the whole shard it sits in.

`add` keeps every field a held record carries and the new reading does not
state, so re-adding a record is how it acquires a basis, and a `--refresh`
cannot drop one no provider could put back. Nothing removes a field.

JSONL keys have this fixed order, because a one-product edit must remain a
one-line diff:

```
source id name brand url serving_size serving_unit total_size total_unit
kcal kj protein fat carbs
<vocabulary nutrients, sorted alphabetically>
basis basis_note
```

The three groups earn their treatment differently. The structural fields are
enumerated because each is validated in its own way. Energy and the four
macros are enumerated because they are cross-checked against each other and
against the 100 g the panel describes. Every other nutrient is open, governed
by a vocabulary of accepted names — today `fiber`, `sodium` and `sugar` — and
written in sorted order, so adding one is a single entry in that vocabulary
and diffs no other line.

The vocabulary is an allowlist. A name outside it is refused rather than
stored, because `sodum: 0.4` would store cleanly and then no consumer would
ever find the sodium. `salt` is deliberately not a synonym for `sodium`: salt
is 2.5 times its sodium.

Optional missing keys are omitted. Every shard omits `source` because the
filename supplies it, in the shipped data and the user's store alike. Records
sort by source order, then id.

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
`eb55fa163c815301f8673e06e282c449deea9d12bde7e0f67e2b6930d187c12d`.
`data/afcd.jsonl` has 1,588 rows and sha256
`c59184d79adcabe49762e34514144f468ba1e0cdd5770da167f584e6f63a6455`.
Tests pin the counts, checksums, and byte-for-byte re-serialization.

One Coles row contains `0.00001`: Python normally writes `1e-05`, which is why
a parse-and-dump migration would corrupt the frozen bytes while appearing
semantically equal. No command rewrites these shards; the key order above was
applied once, by hand, with every parsed value proven unchanged row by row. A fetched product already
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
