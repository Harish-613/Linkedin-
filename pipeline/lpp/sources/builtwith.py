"""BuiltWith (requires a key: set BUILTWITH_API_KEY).

Two response shapes are supported:
  * Domain API (paid, /v21/api.json): individual technologies
    Results[0].Result.Paths[].Technologies[] {Name, Tag, LastDetected, ...}
  * Free API (/free1/api.json): counts per technology group/category only;
    stored as "category:<name>" rows so the extension can still show them.
"""

FREE_URL = "https://api.builtwith.com/free1/api.json"
DOMAIN_URL = "https://api.builtwith.com/v21/api.json"


def parse_builtwith(data: dict) -> list[dict]:
    techs: dict[str, dict] = {}
    for result in data.get("Results") or []:
        for path in (result.get("Result") or {}).get("Paths") or []:
            for t in path.get("Technologies") or []:
                name = t.get("Name")
                if not name:
                    continue
                cats = t.get("Categories") or []
                techs[name] = {"technology": name, "category": cats[0] if cats else t.get("Tag"), "live": True}
    if techs:
        return sorted(techs.values(), key=lambda t: t["technology"])

    rows = []  # free API
    for group in data.get("groups") or []:
        for cat in group.get("categories") or []:
            if cat.get("name"):
                rows.append({"technology": f"category:{cat['name']}", "category": group.get("name"),
                             "live": (cat.get("live") or 0) > 0})
    return rows


def fetch_tech(client, domain: str, api_key: str, paid: bool = False) -> list[dict]:
    url = DOMAIN_URL if paid else FREE_URL
    return parse_builtwith(client.get_json(url, params={"KEY": api_key, "LOOKUP": domain}))
