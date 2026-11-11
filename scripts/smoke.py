"""Print one line per sample job from a running LinkedIn++ API.  Usage: python smoke.py [base_url]"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8787"
JOBS = [("Stripe", "Software Engineer"), ("Coinbase", "Software Engineer Intern"), ("Ramp", "Senior Backend Engineer"),
        ("Databricks", "Machine Learning Engineer"), ("Palantir", "Forward Deployed Software Engineer")]

for company, title in JOBS:
    url = f"{BASE}/api/insights?" + urllib.parse.urlencode({"company": company, "title": title})
    try:
        r = json.load(urllib.request.urlopen(url, timeout=10))
    except urllib.error.HTTPError as e:
        print(f"  {company}: {json.load(e).get('error', e.code)}")
        continue
    pay, iv, comp = r["pay"], r["interview"], r["competitiveness"]
    pay_s = f"${pay['p25'] // 1000}K-${pay['p75'] // 1000}K (n={pay['n']})" if pay else "no pay data"
    print(f"  {r['company']['name']} / {title}: {pay_s}, interview {iv['label'] if iv else '-'}, "
          f"competitiveness {comp['score'] if comp else '-'}, {r['hiring']['open_roles']} open roles")
