# Australian Food Composition Database notice

The `afcd.jsonl` shard is derived from the **Australian Food Composition
Database – Release 3**, © Food Standards Australia New Zealand (FSANZ).
Source and provenance: https://www.foodstandards.gov.au/science-data/food-nutrient-databases/afcd/data-files

The AFCD-derived shard is distributed under the FSANZ Data User Licence
Agreement, based on the Creative Commons Attribution-ShareAlike 3.0 Australia
licence: https://www.foodstandards.gov.au/science-data/monitoringnutrients/afcd/datauserlicenceagreement. This share-alike notice applies to the AFCD-derived
work, not to unrelated Pantry code. No FSANZ endorsement is implied, and no
FSANZ logo is used.

Changes made: Pantry selected the Public Food Key, food name, energy with
dietary fibre, protein, total fat, available carbohydrate without sugar
alcohols, total dietary fibre, and total sugars from the per-100 g sheet;
converted kilojoules to kilocalories by dividing by 4.184 and rounding to one
decimal place; represented the selected fields as deterministically sorted
JSONL; and added an empty brand field for Pantry's common record shape.

This work is based on Australian data. Australia data may not be appropriate
for use in other countries.

There are limitations associated with food composition databases. Food
composition data used in the database or databases may represent an average of
the nutrient content of a particular sample of foods and ingredients,
determined at a particular time. The nutrient composition of foods and
ingredients can vary substantially between batches and brands because of a
number of factors, including changes in season, processing practices and
ingredient source, and methods of calculation.
