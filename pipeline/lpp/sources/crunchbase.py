"""Crunchbase API v4 (requires a key: set CRUNCHBASE_API_KEY).

The Basic tier covers organization lookups, which is all we use:
funding total, last round, founding date, headcount range and categories.
"""

CB_BASE = "https://api.crunchbase.com/api/v4"
FIELDS = ",".join([
    "identifier", "short_description", "website_url", "funding_total", "last_funding_type",
    "founded_on", "num_employees_enum", "categories",
])


def parse_employee_enum(value: str | None) -> tuple[int | None, int | None]:
    """'c_01001_05000' -> (1001, 5000); 'c_10001_max' -> (10001, None)."""
    if not value or not value.startswith("c_"):
        return None, None
    parts = value.split("_")[1:]
    lo = int(parts[0]) if parts and parts[0].isdigit() else None
    hi = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return lo, hi


def parse_organization(data: dict) -> dict:
    props = data.get("properties", data)
    funding = props.get("funding_total") or {}
    founded = props.get("founded_on") or {}
    lo, hi = parse_employee_enum(props.get("num_employees_enum"))
    return {
        "permalink": (props.get("identifier") or {}).get("permalink"),
        "name": (props.get("identifier") or {}).get("value"),
        "website": props.get("website_url"),
        "total_usd": funding.get("value_usd"),
        "last_round_type": props.get("last_funding_type"),
        "founded_on": founded.get("value") if isinstance(founded, dict) else founded,
        "employee_min": lo,
        "employee_max": hi,
        "categories": [c.get("value") for c in props.get("categories") or [] if c.get("value")],
    }


def parse_autocomplete(data: dict) -> str | None:
    """First organization permalink from /autocompletes."""
    for e in data.get("entities", []):
        ident = e.get("identifier") or {}
        if ident.get("entity_def_id", "organization") == "organization" and ident.get("permalink"):
            return ident["permalink"]
    return None


def fetch_organization(client, permalink: str, api_key: str) -> dict:
    data = client.get_json(f"{CB_BASE}/entities/organizations/{permalink}",
                           params={"field_ids": FIELDS}, headers={"X-cb-user-key": api_key})
    return parse_organization(data)


def find_permalink(client, name: str, api_key: str) -> str | None:
    data = client.get_json(f"{CB_BASE}/autocompletes",
                           params={"query": name, "collection_ids": "organizations", "limit": 1},
                           headers={"X-cb-user-key": api_key})
    return parse_autocomplete(data)
