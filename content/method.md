## What it does

_Terra Analog Index_ is a global search tool that compares the Earth cell by cell against lunar or Martian sites and returns a similarity profile per dimension, showing which features are well matched and where the analogy breaks down. It adds a habitability layer to prioritize regions with documented extremophiles.

## Data used

All Earth calculations are based on normalized records from calendar year 2024, covering Natural Earth geographic boundaries, ETOPO 1 km global elevation models, MERRA-2 dust and wind, MODIS monthly surface temperatures, GPM IMERG precipitation and extreme-biodiversity records extracted from NCBI BioSample. The Moon and Mars data come from official missions such as LRO (LOLA and Diviner), MOLA and MEDA, complemented where needed with values from the scientific literature, cited in place.

## How it is calculated

Each 1° cell on Earth is compared with the target site on these dimensions: terrain (slope and roughness), temperature (minimum and daily range), water and ice (precipitation and snow or ice), dust and wind (dust optical depth and surface wind) and astrobiological interest. Dust and wind only exists for Mars: the Moon has no atmosphere, so its total score does not include it.

Each physical variable gets a score from 0 to 1 with one of three rules. The rule is chosen automatically, depending on where the target's value falls relative to Earth, and it is written in `targets.json` so it can be audited: the table above shows the one used for each variable.

- **Similarity.** Earth covers the target's value, so the score drops as the cell moves away from that value.
- **Directional.** The target lies beyond what Earth reaches, like the lunar minimum temperature. Being among the most extreme places on the planet in that direction is rewarded. A 0.95 means "colder than 95% of dry land with data", not "95% equal to the Moon".
- **Presence or absence.** For snow and ice, depending on whether the target has ice or not.

Each dimension is the average of the variables that have data. **Astrobiological interest** does not measure similarity to the target: it counts the records and types of extremophiles documented in NCBI BioSample (on a log scale, so a heavily sampled cell does not dominate) and is the same for both targets.

The **total score** is the average of the dimensions with data, weighted by the weights the visitor moves, and the ranking is recomputed live. A cell enters the ranking if it has data in at least two of the three core physical dimensions (terrain, temperature, water and ice); dust and wind does not count for that.

## Validation

The most important scientific test is that the index rediscovers the analogs the community already uses. Each known analog states why it is used and whether the index's dimensions cover it: one chosen for its volcanic geology or its isolation cannot be rediscovered by an index that does not measure those things, so it is reported but does not count toward passing.

A covered analog **passes** if its best cell, with the default weights, sits at the 90th percentile or above of the eligible cells. A target passes if it has at least two covered analogs and at least two thirds of them pass. The table below comes from `validation.json` and shows each analog with its percentile and its result: `pass`, `fail` or `info`.

If a target does not pass, the data and units, the target's crop, the standard-deviation floor and the default weights are reviewed in that order, and what was done is documented. No per-cell exceptions are added and nothing is tuned until it "comes out right": a well-explained negative result is worth more than a forced one.

## Limits

These are the limits the method declares, worth keeping in mind when reading a score.

- **Conditions that cannot be replicated on Earth**: some Martian and lunar conditions, such as reduced gravity, the Martian CO2 atmosphere or perchlorate-rich soils, cannot be reproduced on Earth. No analog will be perfect.
- **Directional scores do not measure distance to the target.** A 0.95 in temperature says "among the coldest on Earth", not "95% equal to the Moon": Earth never reaches those values. Each site's card always shows the target's real value.
- **Astrobiological interest reflects where research was done.** Famous sites go up and unexplored ones stay at 0. A hypersaline lake counts as evidence of halophiles without checking what was sequenced, and if a type exceeds 5,000 records the first ones NCBI returns are taken (the manifest keeps the real total). That is why the default weight is 0.5 and every card says so.
- **"New" analogs may not be new.** A cell that is not on the team's list may be studied anyway; that is why they are presented as poorly documented candidates.
- **Cells are 1° across.** A crater, a salt flat or a cave gets diluted in the cell average.
- **Some dimensions the challenge mentions are missing:** geology and mineralogy, the subsurface and rover operations. Analogs chosen for those reasons are reported, but they do not count toward passing.
- **Dust and wind on Earth come from a reanalysis** (MERRA-2, a model), not from an observation, and Earth's wind is at about 10 m height while Perseverance measures it at 1.5 m.
- **A single year of data** (the one stated under the grid, above) may not be representative of the climate.
- **Surface temperature is used, not air temperature,** and the lunar temperature range, over a cycle of about 29.5 days, is not equivalent to Earth's daily range.
- **Snow and precipitation at the poles.** Without light there is no optical snow data during the polar night, and the precipitation product can be unreliable over Antarctica.
- **Biological data bias**: the first 5,000 records of each extremophile type are taken from BioSample, but some groups have more (salt: 11,485, cold: 12,164, acid: 8,621, heat: 25,557). It is also a less homogeneous kind of data than the rest. Some heavily studied sites abound in samples, such as parts of China, while less explored regions could host extremophile life. The logarithm helps soften the effect, but does not remove it.

## Credits

**Team sigsegv**:
- Juan Manuel Hernández: repository and grid, terrain, temperature, water and ice, known analogs, similarity, ranking, card and deployment.
- Alan Moreno: NCBI biology layer, target profiles, scoring, validation, map and this tab.
- Santino Rimondotto: scientific criteria, sources, target values, search terms, texts and pitch.
- Santiago Walter: app skeleton, control maps, README and video.

**Data.** The sources and their licenses are in the "Data used" table. The data keep their own terms; the code is licensed under the GNU GPL v3.

**Use of AI.** The team used Claude Code (Anthropic) as a programming assistant. The commits it helped with carry a `Co-Authored-By` line in the repository history. Claude and Gemini were also used for writing and for early literature screening.
