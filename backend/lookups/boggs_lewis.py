"""
Boggs-Lewis Classification System Lookup Tables and Call Number Parser
Copied from reference file boggs_lewis.py
"""
import re

# ─── AREA CLASSIFICATION (Numbers) ────────────────────────────────────
AREA_CODES = {
    "000": "The Universe (astronomic charts, solar system)",
    "075": "Individual constellations",
    "080": "Moon", "081": "Mercury", "082": "Venus", "083": "Earth",
    "084": "Mars", "085": "Jupiter", "086": "Saturn", "087": "Uranus",
    "088": "Neptune", "089": "Pluto",
    "100": "World (and larger parts)",
    "101": "British Empire", "102": "Netherlands and possessions",
    "103": "France and possessions", "104": "Germany and possessions (-1919)",
    "105": "Italy and possessions", "106": "U.S.A. and possessions",
    "107": "Portugal and possessions", "108": "Japan and possessions",
    "110": "Eastern hemisphere", "112": "Eurasia",
    "115": "Europe and Africa", "116": "Asia and Africa",
    "120": "Western hemisphere",
    "122": "The Americas (North, Central, South America and Caribbean)",
    "130": "Northern hemisphere", "140": "Southern hemisphere",
    "150": "Land and water hemispheres",
    "160": "Tropical regions", "170": "Polar regions",
    "171": "North polar region; Arctic Sea",
    "172": "European polar region",
    "172.4": "Svalbard (Spitsbergen)", "177": "Greenland",
    "178": "Canadian Arctic Islands",
    "180": "South polar region; Antarctica",
    "183": "West Antarctica",
    "183.3": "Pacific quadrant (180-90W.)",
    "183.5": "American quadrant (90W.-0)",
    "183.51": "Graham Land / Palmer Land (Antarctic Peninsula)",
    "183.53": "Weddell Sea", "183.54": "South Shetland Islands",
    "183.55": "South Orkney Islands", "183.56": "South Georgia",
    "183.57": "South Sandwich Islands",
    "185": "East Antarctica",
    "185.5": "African quadrant (0-90E.)",
    "185.55": "Heard Island and McDonald Island",
    "185.57": "Kerguelen, Heard Island, McDonald Island",
    "185.7": "Australian quadrant (90E.-180)",
    "187": "Central Antarctica; South Polar plateau",
    "200": "Europe",
    "202": "Northern Europe", "203": "Western Europe",
    "204": "Central Europe", "205": "Eastern Europe",
    "206": "Southern Europe", "207": "Mediterranean Sea",
    "209": "Malta and Gozo",
    "210": "British Isles", "211": "England and Wales",
    "212": "Northern England", "213": "Western England",
    "214": "Midland counties", "215": "Eastern counties",
    "216": "Southeastern England (London, Middlesex, etc.)",
    "216.44": "London area",
    "217": "Southwestern England", "218": "Channel Islands",
    "220": "Wales", "221": "Scotland", "222": "Irish Sea and Isle of Man",
    "223": "Ireland", "224": "Northern Ireland",
    "225": "Scandinavia and Iceland",
    "226": "Norway", "227": "Sweden", "228": "Denmark", "229": "Iceland",
    "230": "Low Countries and Luxemburg",
    "232": "Netherlands", "234": "Belgium", "237": "Switzerland",
    "240": "France", "260": "Germany",
    "280": "Austria-Hungary", "282": "Austria",
    "300": "Czechoslovakia", "310": "Poland",
    "320": "U.S.S.R. / Russia / C.I.S.",
    "330": "Baltic Sea", "331": "Baltic States",
    "332": "Estonia", "333": "Latvia", "334": "Lithuania", "335": "Finland",
    "340": "Iberian Peninsula", "341": "Spain", "348": "Portugal",
    "350": "Italy", "370": "Balkan States",
    "372": "Yugoslavia", "376": "Romania", "382": "Bulgaria",
    "385": "Greece",
    "400": "Asia", "410": "Near East",
    "411": "Turkey", "412": "Cyprus",
    "413": "Syria and Lebanon", "414": "Israel", "415": "Arabia",
    "417": "Iraq", "418": "Iran", "419": "Afghanistan",
    "421": "Central Asia / Turkistan",
    "430": "Japanese Empire", "431": "Japan",
    "433": "Korea", "435": "Taiwan (Formosa)",
    "440": "China", "441": "China proper",
    "450": "India and Burma", "457": "Burma",
    "460": "Indochina and Malay Peninsula",
    "470": "Malay Archipelago; East Indies",
    "471": "Indonesia", "480": "Philippine Islands",
    "500": "Africa", "502": "Northern Africa",
    "510": "Northwestern Africa", "521": "Egypt",
    "530": "Niger-Gambia area", "550": "Cunene-Chad area",
    "560": "Somaliland-Tanganyika area",
    "570": "South Africa", "580": "Madagascar",
    "600": "North America",
    "605": "Alaska", "610": "Canada",
    "620": "Newfoundland, Labrador, Great Lakes",
    "630": "United States of America",
    "640": "New England and Middle Atlantic States",
    "660": "South Central States", "680": "Great Plains and Rockies",
    "690": "Great Basin and Pacific States",
    "700": "Latin America", "702": "Mexico",
    "710": "Central America", "720": "West Indies",
    "740": "South America", "770": "Brazil",
    "780": "Southern South America",
    "800": "Australia, New Zealand and East Indies",
    "801": "Australasia general",
    "802": "Australia and surrounding waters",
    "804": "Australia (general/whole continent)",
    "810": "Australia (political/administrative)",
    "811": "Northern Territory", "812": "Western Australia",
    "813": "Queensland", "814": "South Australia",
    "814.1": "South Australia – Adelaide and surrounds",
    "817": "New South Wales", "819": "Tasmania",
    "820": "Victoria", "821": "Victoria – Melbourne region",
    "823": "Norfolk Island", "828": "Macquarie Island",
    "830": "New Zealand",
    "831": "North Island (New Zealand)",
    "834": "South Island",
    "840": "Papua New Guinea area",
    "850": "Pacific Islands (general)",
    "910": "Pacific Ocean", "920": "Melanesia (oceanic)",
    "921": "New Guinea", "930": "Micronesia", "940": "Polynesia",
    "960": "Hawaiian Islands",
    "980": "Atlantic Ocean", "990": "Indian Ocean",
}

# ─── SUBJECT CLASSIFICATION (Letters) ────────────────────────────────
SUBJECT_CODES = {
    "a": "General maps",
    "aa": "General maps – atlas sheets",
    "ab": "General maps – wall maps",
    "ac": "General maps – charts / reference maps",
    "ad": "General maps – administrative/boundary",
    "ae": "General maps – pictorial/decorative",
    "af": "General maps – facsimile/reproduction",
    "an": "General maps – nautical/navigation",
    "ar": "General maps – road maps",
    "at": "General maps – topographic",
    "atc": "General maps – topographic cadastral",
    "atu": "General maps – topographic urban",
    "b": "Mathematical geography, Cartography, Surveying",
    "bj": "Cadastral surveys / Land surveys",
    "bje": "Cadastral – exploration surveys",
    "c": "Physical geography",
    "cb": "Topography/Relief",
    "cc": "Hydrography",
    "cd": "Geology",
    "ce": "Geomorphology",
    "cf": "Meteorology/Climate",
    "d": "Biogeography",
    "db": "Botany/Vegetation",
    "dc": "Zoology/Fauna",
    "dd": "Ecology",
    "e": "Human geography",
    "eb": "Population/Demographics",
    "en": "Exploration / Discovery",
    "f": "Political geography",
    "fb": "Boundaries / Administrative divisions",
    "g": "Economic geography",
    "gb": "Agriculture / Land use",
    "gbbd": "Agriculture – districts/regions",
    "gc": "Mining / Mineral resources",
    "gd": "Industry / Manufacturing",
    "gg": "Transportation",
    "gi": "Tourism / Recreation",
    "gm": "Pastoral / Grazing",
    "gmbt": "Pastoral – tenures",
    "h": "Military and naval geography",
    "hb": "Military – campaigns",
    "hc": "Naval",
    "n": "History of geography",
    "p": "Plans / Architectural drawings",
}


def parse_call_number(call_number: str) -> dict:
    cn = call_number.strip()
    parts = cn.split()
    result = {
        "raw": cn, "area_code": "", "area_description": "",
        "subject_code": "", "subject_description": "",
        "date": "", "qualifier": "", "copy_number": "",
        "is_valid": False, "validation_notes": [],
    }
    if not parts:
        return result

    result["area_code"] = parts[0]
    result["area_description"] = lookup_area(parts[0])

    if len(parts) >= 2 and parts[1][0].isalpha():
        result["subject_code"] = parts[1]
        result["subject_description"] = lookup_subject(parts[1])

    if result["area_code"] and result["subject_code"]:
        result["is_valid"] = True
    return result


def lookup_area(code: str) -> str:
    if code in AREA_CODES:
        return AREA_CODES[code]
    parts = code.split(".")
    if len(parts) == 2 and parts[0] in AREA_CODES:
        return AREA_CODES[parts[0]] + f" (sub-area .{parts[1]})"
    try:
        hundreds = str(int(float(code)) // 100 * 100)
        if hundreds in AREA_CODES:
            return AREA_CODES[hundreds] + f" (sub-area {code})"
    except ValueError:
        pass
    return ""


def lookup_subject(code: str) -> str:
    if code in SUBJECT_CODES:
        return SUBJECT_CODES[code]
    if code and code[0] in SUBJECT_CODES:
        return SUBJECT_CODES[code[0]] + f" ({code})"
    return ""
