-- LinkedIn++ schema. Plain PostgreSQL, so it runs on Supabase or any Postgres 13+.
-- Re-runnable: every statement is IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS companies (
    id                   SERIAL PRIMARY KEY,
    name                 TEXT NOT NULL,
    normalized_name      TEXT NOT NULL,
    domain               TEXT,
    cik                  INTEGER UNIQUE,          -- SEC EDGAR id (public companies)
    ticker               TEXT,
    crunchbase_permalink TEXT,
    ats_provider         TEXT CHECK (ats_provider IN ('greenhouse', 'lever', 'ashby')),
    ats_token            TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companies_normalized_name_idx ON companies (normalized_name);
CREATE UNIQUE INDEX IF NOT EXISTS companies_domain_idx ON companies (domain) WHERE domain IS NOT NULL;

-- Every name a company is known by (SEC title, LinkedIn display name, ticker...),
-- normalized, so the extension can look a company up by what LinkedIn shows.
CREATE TABLE IF NOT EXISTS company_aliases (
    alias      TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies (id) ON DELETE CASCADE
);

-- SEC EDGAR: latest annual figures from XBRL company facts.
CREATE TABLE IF NOT EXISTS sec_financials (
    company_id      INTEGER PRIMARY KEY REFERENCES companies (id) ON DELETE CASCADE,
    fiscal_year     INTEGER,
    revenue_usd     NUMERIC,
    net_income_usd  NUMERIC,
    revenue_growth  NUMERIC,      -- year over year, e.g. 0.12 = +12%
    sic_description TEXT,
    state           TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Crunchbase: funding and size.
CREATE TABLE IF NOT EXISTS funding (
    company_id      INTEGER PRIMARY KEY REFERENCES companies (id) ON DELETE CASCADE,
    total_usd       NUMERIC,
    last_round_type TEXT,
    founded_on      DATE,
    employee_min    INTEGER,
    employee_max    INTEGER,
    categories      TEXT[],
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- BuiltWith: technologies seen on the company's website.
CREATE TABLE IF NOT EXISTS tech_stack (
    company_id INTEGER NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    technology TEXT NOT NULL,
    category   TEXT,
    live       BOOLEAN NOT NULL DEFAULT true,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, technology)
);

-- Career pages (Greenhouse, Lever, Ashby public job boards).
CREATE TABLE IF NOT EXISTS job_postings (
    id           TEXT PRIMARY KEY,               -- "<source>:<external id>"
    company_id   INTEGER NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    role_family  TEXT NOT NULL,
    seniority    TEXT NOT NULL,
    location     TEXT,
    remote       BOOLEAN,
    url          TEXT,
    posted_at    TIMESTAMPTZ,
    pay_min      NUMERIC,                        -- annualized
    pay_max      NUMERIC,
    pay_currency TEXT,
    description  TEXT,
    first_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    active       BOOLEAN NOT NULL DEFAULT true   -- false once the posting disappears from the board
);
CREATE INDEX IF NOT EXISTS job_postings_company_idx ON job_postings (company_id, role_family) WHERE active;

-- Levels.fyi: self-reported compensation, imported from a file you provide.
CREATE TABLE IF NOT EXISTS levels_comp (
    id          SERIAL PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    title       TEXT,
    level       TEXT,
    role_family TEXT NOT NULL,
    seniority   TEXT NOT NULL,
    base_usd    NUMERIC,
    total_usd   NUMERIC,
    years_exp   NUMERIC,
    location    TEXT,
    reported_on DATE,
    source_file TEXT,
    row_hash    TEXT UNIQUE                      -- makes re-importing the same file a no-op
);
CREATE INDEX IF NOT EXISTS levels_comp_company_idx ON levels_comp (company_id, role_family);

-- Computed by `lpp compute`; what the API serves.
CREATE TABLE IF NOT EXISTS company_insights (
    company_id      INTEGER PRIMARY KEY REFERENCES companies (id) ON DELETE CASCADE,
    open_roles      INTEGER NOT NULL DEFAULT 0,
    new_roles_30d   INTEGER NOT NULL DEFAULT 0,
    pay             JSONB NOT NULL DEFAULT '{}',  -- {role_family: {seniority|"all": {p25, p50, p75, n, sources}}}
    competitiveness JSONB,                        -- {score, label, factors}
    interview       JSONB NOT NULL DEFAULT '{}',  -- {role_family: {score, label, rationale, method}}
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- LLM responses keyed by prompt hash, so recomputing doesn't re-bill.
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    response    JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
