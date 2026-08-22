"""The text behind `pantry guide`: the manual, shipped in the binary."""

GUIDE = """
pantry — food product records, per 100 g, always.

THREE VERBS
  search <query>          every enabled provider; local unless --remote
  lookup <src> <id>       exact identity, local only, never a request
  add <ref>               acquire one record and store it

IDENTITY
  A product is the pair (source, id). Sources are coles, woolworths, afcd,
  usda, openfoodfacts, manual. Ids are source-native
  strings compared with `==`; leading zeros are significant, and no id carries
  a source prefix. Keep both halves of a search result.

NUTRIENTS
  Every figure in every record is grams per 100 g. One rule, no exceptions.
  Scale by grams / 100 at the point of display. Never store a pre-scaled
  value. An absent nutrient is unknown, never zero.

  Energy and the four macros are on every record. Every other nutrient comes
  from a vocabulary of accepted names -- fiber, sodium, sugar -- and a name
  outside it is refused rather than stored: a misspelling stores cleanly and
  then nothing ever finds the nutrient again.

  Per 100 g as sold, unless the record carries `basis`: as_sold or
  as_prepared, absent meaning as_sold. An as_prepared panel was printed for
  the made-up food, so scaling it by a dry weight is wrong by whatever the
  preparation adds -- 47x for a stock cube. Read `basis_note` for the
  conversion instead ("per 100 mL prepared; 1 cube (10.5 g) makes 500 mL").
  Both are shown by search and lookup when present. A basis that is neither
  value is refused, on the way out and on the way in alike: an unrecognised
  one reads as absent and absent means as-sold, which is the silent error the
  key exists to prevent. The note is free text and nothing else about the pair
  is checked, because one bad row must never cost the shard it sits in.

PROVIDERS
  local          the frozen shards plus your own. Search. No network.
  openfoodfacts  the public Search-a-licious index. Search and acquire by
                 barcode. No key. Successful searches are reused for 24 h.
  usda           FoodData Central. Acquire by fdcId. Needs $USDA_API_KEY (or
                 .env, or --api-key); without one it is simply skipped.
  retailer       Coles and Woolworths product pages. Acquire by url.

  A provider with no credential is skipped silently — unconfigured is not a
  failure. Keys are read from the environment and never printed.

SEARCH LOCALLY FIRST
  pantry --json search "greek yogurt" --limit 10
  Emits {"query":...,"sources":[...],"results":[...]} and exits 0 even when
  results is empty. Local only by default: no request, no cost, no rate limit.
  Do this before anything remote, every time. --remote adds the providers that
  cost a request, --source NAME restricts to one (repeatable), --limit applies
  per provider, and every result carries the source it came from.

  pantry --json lookup coles 1047
  Found exits 0 with {"found":true,...,"product":{...}}; a miss exits 1 with
  {"found":false,...,"product":null}. Both are answers, not errors. This
  command never touches the network.

DISCOVER A PRODUCT THAT IS NOT HELD
  pantry --json search "brand cultured soy block" --remote --source
    openfoodfacts --limit 10
  Community data: candidates, not proof of current retailer availability.
  Start with the user's own distinctive words; phrase boosting is already on.
  Lucene syntax works, but `AND`, field clauses and quoted phrases are strict
  filters — never lead with them, and never read a filtered miss as absence.
  Avoid `product_name:`, which the deployed index handles unreliably. Never
  filter by country: imported stock and incomplete metadata make geography an
  unsafe identity constraint. If a query misses, swap one category synonym at
  a time and keep every user-supplied brand, size, form and variant. Stay
  under ten searches a minute. If more than one candidate still fits, show the
  differences and ask which one before adding anything.

ADD ONE RECORD
  pantry add "https://www.woolworths.com.au/shop/productdetails/581176/x"
  pantry add usda:2476857
  pantry add off:0123456789012
  pantry add --manual --id sourdough --name Sourdough <<'EOF'
               Per serve  Per 100g
  Energy       590kJ      1000kJ
  Protein      5.6g       9.5g
  Fat, Total   2.0g       3.4g
  Carbohydrate 23.1g      39.2g
  EOF

  The reference decides the provider. The local store is checked before
  anything is spent, and a record that parses is persisted immediately.
  Emits {"stored":...,"reason":"stored|held|unchanged","source":...,"id":...,
  "product":{...},"changes":[...],"notes":[...]}.

  There is no age-based refresh. Re-read a held record only with --refresh,
  which requires the identity to be held already, reports the changed fields,
  and leaves the store untouched if nothing changed or the load failed.

  An Open Food Facts row is stored under source `openfoodfacts` with its OFF
  page as the url. Filing it as `manual` would claim you read it off a label
  and would let your own entry for the same barcode overwrite it. It is
  community data, not proof of current availability.

  A row printed in milligrams is converted to the grams a record holds, so
  "Sodium 400mg" and "Sodium 0.4g" both store 0.4, and a trace bound such as
  "LESS THAN 5mg" stores the bound. A Salt row is not read at all: salt is 2.5
  times its sodium, and reading one as the other would overstate it by 150
  percent.

  To be read, a Sodium row must open its line and be followed by its figure.
  That rules out an additive -- "Sodium Bicarbonate (500)", which also matches
  the carbs row on "bicarbonate" -- and with it "Sodium (as salt)", "Sodium
  (g) 0.4" (only a unit on the figure is converted) and a row wrapped in
  markup. A declined row is absent from the record rather than guessed at, and
  nothing warns about it.

  --manual reads the panel from stdin and never touches the network; with a
  retailer url it keeps that identity, so a blocked page is a redirection and
  not a dead end. Two-column labels are handled: the per-100 g column wins,
  which is the last column unless the header names "per 100 g" first. When
  that column is computed on added water, say so with --basis as_prepared and
  --basis-note; --basis-note needs --basis, and both need --manual, because no
  page or API declares a basis.

  Adding a record that is already held keeps every field the new reading does
  not state, --manual and --refresh alike. That is how a held record gets a
  basis: re-add it with --basis, and its pack size, url and unmentioned rows
  survive. It is also why no provider can drop a basis a human supplied. The
  cost is that nothing removes a field -- correcting one means restating it,
  and an empty --basis-note is the only blanking there is.

WHAT A RETAILER PAGE COSTS
  The page budget defaults to 4 (--budget N). It is claimed before the request
  and counted even when the request was refused, because the site served it
  either way. Requests are paced 3000 ms apart. Every run says what it spent,
  successful or not — under --json it is in `notes`, or appended to the error
  message. Preserve it when reporting a failure.

  A block ends the session permanently: no retry, no second user agent, no
  proxy, no captcha solving, no lowered pacing. Later loads in the same run
  are refused without spending anything. The answer to a block is
  `pantry add --manual`. --browser is an explicit local-Chrome fallback the
  user asks for; it is never an automatic response to a block.

NEVER INFER ZEROS
  A missing, malformed or unreadable nutrition value is refused, not coerced.
  An inferred zero silently under-counts every recipe downstream. The one
  exception is --zero-calorie, which accepts only an absent or all-zero panel
  and is refused the moment an energy-bearing value is non-zero. A
  calorie-free nutrient is exempt: sodium carries no energy, so table salt is
  a genuine 0 kcal record with 38.758 g of it. Sugar is not exempt, and the
  100 g per 100 g ceiling still applies to every nutrient alike.

STORAGE
  Everything added writes immediately under $XDG_CONFIG_HOME/pantry, or
  ~/.config/pantry. No command writes into a checkout.

  The layout is the one the frozen data ships in: one <source>.jsonl shard
  per source, each row taking its source from the filename rather than
  repeating it. Search merges the two, and a stored row replaces only the
  base row with the same (source, id) -- never a whole shard. Promoting a
  record into a checkout is a deliberate copy; the Coles shard is a frozen,
  irreplaceable 10,297-row scrape that nothing here rebuilds.

EXIT CODES
  0 success (including a search that found nothing)
  1 usage error: bad flags, unparseable input, a refused declaration, a
    missing credential, or a spent page budget
  2 remote error: network failure, API failure, or a site refusal
  3 assertion failure
  4 data-quality warning escalated by --strict

  Pantry returns 0, 1 and 2; 3 and 4 are reserved by the shared convention.

  With --json, stdout is exactly one JSON object, failures included:
  {"ok":false,"error":{"message":"..."}}. The flag works before or after the
  subcommand and applies to search, lookup and add. Treat stdout as JSON only
  after asking for it.

FRESHNESS
  A local hit is not a claim of current retailer availability. The Coles shard
  is a frozen scrape, AFCD data is Release 3, and a retailer row you hold
  reflects only its last successful add or explicit refresh.
"""
