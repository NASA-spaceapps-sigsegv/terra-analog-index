# Northern Ellesmere Island (Nunavut, Canada)

This 1° cell lies in the north of Ellesmere Island, in the High Arctic. With the default weights it is the best one for the lunar south pole outside Antarctica: terrain and water and ice score high, and the total is 0.67 [1].

**What is known.** Quttinirpaaq National Park, on the same island, is a polar desert with continuous permafrost [2]. We did not find this cell described as a lunar analog. The nearest declared analog is Haughton Crater (Devon Island), about 720 km away [1][3].

**What it could be used for (hypothesis).** Testing drilling and sampling in icy ground. NASA is developing a lightweight permafrost drill at Eureka, on the same island [4].

**Where the analogy breaks down.** The daily temperature range is 0.9 °C, versus 152 °C at the lunar south pole, and the minimum temperature is −37 °C, not −223 °C [1]. The 0.89 in temperature says it is among the coldest places on Earth, not that it resembles the target. The satellite's 176 mm of precipitation per year seem too high for a polar desert [1][2].

**Dust and wind.** This dimension is not scored for the Moon, which has no atmosphere. Dust optical depth is 0.009 and wind 3.8 m/s, both from a reanalysis [1]. Lunar dust is abrasive, charged regolith that no Earth cell replicates.

**What to check in the field.** Slope and roughness at rover scale, ground ice and weather-station data.

## Sources

1. Terra Analog Index, `data/processed/`: cell 61661 against `moon_south_pole`, default weights; distance to the analogs in `config/known_analogs.csv`.
2. Parks Canada, "Ecosystems and habitats", Quttinirpaaq National Park. https://parks.canada.ca/pn-np/nu/quttinirpaaq/nature/environnement-environment/habitats
3. Lee, P. et al. (2007), LPSC XXXVIII, abstract 2426 (the Haughton citation in `config/known_analogs.csv`).
4. NASA, "Haughton-Mars Project (HMP), Canadian Arctic". https://www.nasa.gov/mission/haughton-mars-project-hmp-canadian-arctic
