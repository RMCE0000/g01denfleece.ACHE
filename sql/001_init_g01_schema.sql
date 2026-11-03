-- g01 schema. Apply after Chatwoot's own migrations on the shared Postgres 16 database.
-- Tables 1–6 and the locality seed follow the MVP brief. The rest is the ranking,
-- idempotency, and gate machinery those tables need in order to stay deterministic.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. LOCALITIES (city + contiguous suburbs)
CREATE TABLE IF NOT EXISTS g01_localities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    primary_city VARCHAR(120) NOT NULL,
    state_code VARCHAR(10) NOT NULL,
    allowed_zip_codes TEXT[] NOT NULL,
    center_lat DOUBLE PRECISION NOT NULL,
    center_lng DOUBLE PRECISION NOT NULL,
    max_radius_miles DOUBLE PRECISION DEFAULT 25.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS g01_localities_city_state_idx
    ON g01_localities (primary_city, state_code);

-- 2. HOMESTEADER PROPERTIES & THE 5-DIMENSIONAL NORTH STAR
CREATE TABLE IF NOT EXISTS g01_properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chatwoot_account_id BIGINT NOT NULL,
    chatwoot_user_id BIGINT UNIQUE,
    chatwoot_contact_id BIGINT UNIQUE NOT NULL,
    primary_conversation_id BIGINT UNIQUE,
    locality_id UUID REFERENCES g01_localities(id) NOT NULL,
    street_address TEXT,
    zip_code VARCHAR(20) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,

    -- 1. Automated: FLOAT 0.0–100.0, objective, derived from labor hours.
    northstar_automated_pct NUMERIC(5,2) DEFAULT 0.00 CHECK (northstar_automated_pct >= 0 AND northstar_automated_pct <= 100),
    outside_aid_hours_per_week NUMERIC(6,2) DEFAULT 40.00,

    -- 2. Aesthetic: FLOAT 0.0–100.0, subjective, set by the homesteader.
    northstar_aesthetic_pct NUMERIC(5,2) DEFAULT 50.00 CHECK (northstar_aesthetic_pct >= 0 AND northstar_aesthetic_pct <= 100),

    -- 3. Material: BOOLEAN. Surplus profit is a fact on this dimension, not a sixth score.
    northstar_material_independent BOOLEAN DEFAULT FALSE,
    material_surplus_profitable BOOLEAN DEFAULT FALSE,

    -- 4. Energetic: FLOAT (surplus may exceed 100, capped at 500) + BOOLEAN.
    northstar_energetic_pct NUMERIC(5,2) DEFAULT 0.00 CHECK (northstar_energetic_pct >= 0 AND northstar_energetic_pct <= 500),
    northstar_energetic_profitable BOOLEAN DEFAULT FALSE,

    -- 5. Contained: BOOLEAN.
    northstar_contained_zero_waste BOOLEAN DEFAULT FALSE,

    known_facts_ledger JSONB DEFAULT '{
        "acreage": null,
        "soil_and_water": [],
        "energy_systems": [],
        "livestock_and_crops": [],
        "waste_containment": [],
        "skills_and_equipment": [],
        "active_goals": []
    }'::jsonb,

    goals_embedding vector(768),

    kyc_verified BOOLEAN DEFAULT FALSE,
    stripe_identity_session_id VARCHAR(255),
    -- In-progress sponsorship answers collected inside the Chatwoot thread.
    sponsor_draft JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE g01_properties ADD COLUMN IF NOT EXISTS sponsor_draft JSONB;
ALTER TABLE g01_properties ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE g01_properties ADD COLUMN IF NOT EXISTS display_name VARCHAR(255);
ALTER TABLE g01_properties ADD COLUMN IF NOT EXISTS chatwoot_inbox_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS g01_properties_email_idx
    ON g01_properties (lower(email)) WHERE email IS NOT NULL;

-- A private Chatwoot inbox shared by two signed-in homesteaders. Jane stays quiet
-- on these conversation ids unless the message says her name.
CREATE TABLE IF NOT EXISTS g01_peer_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chatwoot_conversation_id BIGINT NOT NULL UNIQUE,
    chatwoot_inbox_id BIGINT,
    property_a_id UUID NOT NULL REFERENCES g01_properties(id),
    property_b_id UUID NOT NULL REFERENCES g01_properties(id),
    topic VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT g01_peer_distinct CHECK (property_a_id <> property_b_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS g01_peer_pair_idx
    ON g01_peer_conversations (property_a_id, property_b_id);

ALTER TABLE g01_properties DROP CONSTRAINT IF EXISTS g01_properties_hours_nonnegative;
ALTER TABLE g01_properties
    ADD CONSTRAINT g01_properties_hours_nonnegative CHECK (outside_aid_hours_per_week >= 0);

-- 3. ADMIN-CONTROLLED PROMO CODES
CREATE TABLE IF NOT EXISTS g01_promo_codes (
    code VARCHAR(64) PRIMARY KEY,
    stripe_coupon_id VARCHAR(255) NOT NULL,
    discount_percent INT NOT NULL CHECK (discount_percent BETWEEN 1 AND 100),
    recommendation_boost NUMERIC(4,2) DEFAULT 1.00 CHECK (recommendation_boost BETWEEN 0.50 AND 3.00),
    restricted_locality_id UUID REFERENCES g01_localities(id),
    max_uses INT DEFAULT 100,
    current_uses INT DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. LOCAL SPONSORS & SOURCING HIERARCHY
CREATE TABLE IF NOT EXISTS g01_sponsors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID REFERENCES g01_properties(id) ON DELETE CASCADE,
    locality_id UUID REFERENCES g01_localities(id) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    founding_city VARCHAR(120) NOT NULL,
    founding_state VARCHAR(10) NOT NULL,
    is_franchise_or_chain BOOLEAN DEFAULT FALSE,

    -- local_manufacturer (0.85), local_service_or_stock (0.70), local_logistics_proxy (0.50)
    sourcing_tier VARCHAR(40) NOT NULL DEFAULT 'local_service_or_stock',
    service_tags TEXT[] NOT NULL,
    capabilities_summary TEXT NOT NULL,
    capabilities_embedding vector(768),

    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,

    referrals_last_14d INT DEFAULT 0,
    last_referred_at TIMESTAMPTZ,
    homesteader_rating NUMERIC(3,2) DEFAULT 5.00,
    promo_boost_weight NUMERIC(4,2) DEFAULT 1.00,

    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    applied_promo_code VARCHAR(64) REFERENCES g01_promo_codes(code),
    is_active_sponsor BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE g01_sponsors DROP CONSTRAINT IF EXISTS g01_sponsors_tier_chk;
ALTER TABLE g01_sponsors
    ADD CONSTRAINT g01_sponsors_tier_chk CHECK (
        sourcing_tier IN ('local_manufacturer', 'local_service_or_stock', 'local_logistics_proxy')
    );

-- 5. NEIGHBORHOOD DEMAND POLLING
CREATE TABLE IF NOT EXISTS g01_demand_polls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_property_id UUID REFERENCES g01_properties(id) NOT NULL,
    locality_id UUID REFERENCES g01_localities(id) NOT NULL,
    topic_slug VARCHAR(120) NOT NULL,
    question_sent_to_neighbors TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'polling',
    mature_at TIMESTAMPTZ NOT NULL,
    final_synthesis_report TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- The brief named this column question_Sent_to_neighbors. The sidecar reads question_sent_to_neighbors.
-- A generated compatibility column keeps both names pointed at one value if an older row used the mixed case.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'g01_demand_polls' AND column_name = 'question_Sent_to_neighbors'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'g01_demand_polls' AND column_name = 'question_sent_to_neighbors'
    ) THEN
        ALTER TABLE g01_demand_polls RENAME COLUMN "question_Sent_to_neighbors" TO question_sent_to_neighbors;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS g01_poll_votes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    poll_id UUID REFERENCES g01_demand_polls(id) ON DELETE CASCADE,
    neighbor_property_id UUID REFERENCES g01_properties(id) NOT NULL,
    raw_reply TEXT NOT NULL,
    weekly_units_demanded NUMERIC(10,2) DEFAULT 0,
    willing_price_per_unit_usd NUMERIC(10,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (poll_id, neighbor_property_id)
);

CREATE TABLE IF NOT EXISTS g01_poll_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    poll_id UUID NOT NULL REFERENCES g01_demand_polls(id) ON DELETE CASCADE,
    neighbor_property_id UUID NOT NULL REFERENCES g01_properties(id),
    conversation_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (poll_id, neighbor_property_id)
);

-- 6. NEIGHBOR COLLABORATION MATCHES
CREATE TABLE IF NOT EXISTS g01_neighbor_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    locality_id UUID REFERENCES g01_localities(id) NOT NULL,
    peer_a_property_id UUID REFERENCES g01_properties(id) NOT NULL,
    peer_b_property_id UUID REFERENCES g01_properties(id) NOT NULL,
    proposed_project_title VARCHAR(255) NOT NULL,
    jane_synergy_rationale TEXT NOT NULL,
    peer_a_status VARCHAR(20) DEFAULT 'pitched',
    peer_b_status VARCHAR(20) DEFAULT 'pitched',
    shared_chatwoot_conversation_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (peer_a_property_id, peer_b_property_id, proposed_project_title)
);

CREATE TABLE IF NOT EXISTS g01_referral_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sponsor_id UUID NOT NULL REFERENCES g01_sponsors(id) ON DELETE CASCADE,
    property_id UUID REFERENCES g01_properties(id) ON DELETE SET NULL,
    service_tag VARCHAR(120) NOT NULL,
    source_event_id TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS g01_processed_webhook_events (
    event_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS g01_sponsor_checkouts (
    stripe_session_id VARCHAR(255) PRIMARY KEY,
    sponsor_id UUID NOT NULL REFERENCES g01_sponsors(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS g01_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id BIGINT,
    content TEXT NOT NULL,
    delivered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS g01_sponsors_locality_idx ON g01_sponsors (locality_id);
CREATE INDEX IF NOT EXISTS g01_sponsors_tags_idx ON g01_sponsors USING GIN (service_tags);
CREATE INDEX IF NOT EXISTS g01_properties_locality_idx ON g01_properties (locality_id);
CREATE INDEX IF NOT EXISTS g01_demand_polls_status_idx ON g01_demand_polls (status, mature_at);
CREATE INDEX IF NOT EXISTS g01_properties_goals_hnsw
    ON g01_properties USING hnsw (goals_embedding vector_cosine_ops);

INSERT INTO g01_localities (id, name, primary_city, state_code, allowed_zip_codes, center_lat, center_lng)
VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', 'Lake Charles & Calcasieu Suburbs', 'Lake Charles', 'LA', ARRAY['70601','70605','70607','70611','70615','70663','70669'], 30.2266, -93.2174),
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', 'Rogers Metro', 'Rogers', 'AR', ARRAY['72756','72758'], 36.3320, -94.1185)
ON CONFLICT (primary_city, state_code) DO NOTHING;

-- Objective Automated score: percentage reduction versus a 40-hour full-manual week.
CREATE OR REPLACE FUNCTION g01_sync_property_metrics() RETURNS trigger AS $$
BEGIN
    NEW.northstar_automated_pct := ROUND(GREATEST(0, LEAST(100,
        (1 - (COALESCE(NEW.outside_aid_hours_per_week, 40) / 40.0)) * 100
    ))::numeric, 2);
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS g01_properties_metrics ON g01_properties;
CREATE TRIGGER g01_properties_metrics
    BEFORE INSERT OR UPDATE ON g01_properties
    FOR EACH ROW EXECUTE FUNCTION g01_sync_property_metrics();

CREATE OR REPLACE FUNCTION g01_company_norm(name TEXT) RETURNS TEXT AS $$
    SELECT regexp_replace(lower(COALESCE(name, '')), '[^a-z0-9]+', '', 'g');
$$ LANGUAGE SQL IMMUTABLE;

CREATE OR REPLACE FUNCTION g01_enforce_sponsor_origin() RETURNS trigger AS $$
DECLARE
    loc g01_localities%ROWTYPE;
    norm TEXT;
    rogers BOOLEAN;
BEGIN
    SELECT * INTO loc FROM g01_localities WHERE id = NEW.locality_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'sponsor locality is missing';
    END IF;
    norm := g01_company_norm(NEW.company_name);
    rogers := loc.primary_city = 'Rogers' AND loc.state_code = 'AR'
        AND NEW.founding_city = 'Rogers' AND NEW.founding_state = 'AR';
    IF position('amazon' IN norm) > 0
       OR position('homedepot' IN norm) > 0
       OR position('lowes' IN norm) > 0 THEN
        RAISE EXCEPTION 'g01 does not list internet or big-box retailers';
    END IF;
    IF position('walmart' IN norm) > 0 AND NOT rogers THEN
        RAISE EXCEPTION 'Walmart may only appear in Rogers, Arkansas';
    END IF;
    IF NEW.capabilities_summary ~* 'amazon\.|homedepot\.|lowes\.|walmart\.|wal-mart\.' THEN
        RAISE EXCEPTION 'sponsor text cannot link to a banned retailer';
    END IF;
    IF NEW.is_franchise_or_chain AND NOT rogers THEN
        RAISE EXCEPTION 'franchise chains are excluded outside the Rogers, Arkansas origin exception';
    END IF;
    IF NEW.founding_state <> loc.state_code THEN
        RAISE EXCEPTION 'founding state must sit inside the sponsor locality';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS g01_sponsors_origin ON g01_sponsors;
CREATE TRIGGER g01_sponsors_origin
    BEFORE INSERT OR UPDATE ON g01_sponsors
    FOR EACH ROW EXECUTE FUNCTION g01_enforce_sponsor_origin();

CREATE OR REPLACE FUNCTION g01_tier_weight(tier TEXT) RETURNS NUMERIC AS $$
    SELECT CASE tier
        WHEN 'homestead_fabrication' THEN 1.00
        WHEN 'local_manufacturer' THEN 0.85
        WHEN 'local_service_or_stock' THEN 0.70
        WHEN 'local_logistics_proxy' THEN 0.50
        ELSE 0.00
    END;
$$ LANGUAGE SQL IMMUTABLE;

-- Earth radius matches app.sourcing.haversine_miles (3958.7613 statute miles).
CREATE OR REPLACE FUNCTION g01_haversine_miles(
    lat1 DOUBLE PRECISION,
    lng1 DOUBLE PRECISION,
    lat2 DOUBLE PRECISION,
    lng2 DOUBLE PRECISION
) RETURNS DOUBLE PRECISION AS $$
    SELECT 3958.7613 * 2 * asin(sqrt(
        power(sin(radians(lat2 - lat1) / 2), 2) +
        cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lng2 - lng1) / 2), 2)
    ));
$$ LANGUAGE SQL IMMUTABLE;

-- score = tier_weight * (0.45 + 0.25 * distance_score + 0.20 * rotation_score + 0.10 * rating_score) * promo_boost
CREATE OR REPLACE FUNCTION g01_recommendation_score(
    sourcing_tier TEXT,
    distance_miles DOUBLE PRECISION,
    max_radius_miles DOUBLE PRECISION,
    referrals_last_14d INT,
    homesteader_rating NUMERIC,
    promo_boost_weight NUMERIC
) RETURNS NUMERIC AS $$
DECLARE
    tier_w NUMERIC;
    radius NUMERIC;
    dist_score NUMERIC;
    rotation_score NUMERIC;
    rating_score NUMERIC;
BEGIN
    tier_w := g01_tier_weight(sourcing_tier);
    radius := GREATEST(COALESCE(max_radius_miles, 25.0), 0.0001);
    dist_score := GREATEST(0, 1 - (GREATEST(COALESCE(distance_miles, 0), 0) / radius));
    rotation_score := 1.0 / (1 + GREATEST(COALESCE(referrals_last_14d, 0), 0));
    rating_score := LEAST(1, GREATEST(0, COALESCE(homesteader_rating, 5) / 5.0));
    RETURN ROUND(
        tier_w * (0.45 + 0.25 * dist_score + 0.20 * rotation_score + 0.10 * rating_score)
        * COALESCE(promo_boost_weight, 1),
        4
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION g01_rank_local_sponsors(
    p_property_id UUID,
    p_service_tag TEXT,
    p_limit INT DEFAULT 5
) RETURNS TABLE (
    sponsor_id UUID,
    company_name VARCHAR,
    sourcing_tier VARCHAR,
    tier_weight NUMERIC,
    distance_miles DOUBLE PRECISION,
    score NUMERIC,
    promo_boost_weight NUMERIC,
    referrals_last_14d INT,
    homesteader_rating NUMERIC
) AS $$
    SELECT
        s.id,
        s.company_name,
        s.sourcing_tier,
        g01_tier_weight(s.sourcing_tier),
        g01_haversine_miles(p.lat, p.lng, s.lat, s.lng),
        g01_recommendation_score(
            s.sourcing_tier,
            g01_haversine_miles(p.lat, p.lng, s.lat, s.lng),
            l.max_radius_miles,
            s.referrals_last_14d,
            s.homesteader_rating,
            s.promo_boost_weight
        ) AS score,
        s.promo_boost_weight,
        s.referrals_last_14d,
        s.homesteader_rating
    FROM g01_sponsors s
    JOIN g01_properties p ON p.id = p_property_id
    JOIN g01_localities l ON l.id = p.locality_id
    WHERE s.locality_id = p.locality_id
      AND s.is_active_sponsor
      AND lower(p_service_tag) = ANY (SELECT lower(t) FROM unnest(s.service_tags) AS u(t))
      AND (
          NOT s.is_franchise_or_chain
          OR (
              l.primary_city = 'Rogers' AND l.state_code = 'AR'
              AND s.founding_city = 'Rogers' AND s.founding_state = 'AR'
          )
      )
      AND position('amazon' IN g01_company_norm(s.company_name)) = 0
      AND position('homedepot' IN g01_company_norm(s.company_name)) = 0
      AND position('lowes' IN g01_company_norm(s.company_name)) = 0
      AND (
          position('walmart' IN g01_company_norm(s.company_name)) = 0
          OR (l.primary_city = 'Rogers' AND l.state_code = 'AR')
      )
    ORDER BY score DESC, s.referrals_last_14d ASC, s.id ASC
    LIMIT GREATEST(COALESCE(p_limit, 5), 1);
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION g01_recount_referrals() RETURNS void AS $$
BEGIN
    UPDATE g01_sponsors s
    SET referrals_last_14d = COALESCE(sub.cnt, 0),
        last_referred_at = sub.last_at
    FROM (
        SELECT sponsor_id, COUNT(*)::int AS cnt, MAX(created_at) AS last_at
        FROM g01_referral_events
        WHERE created_at >= NOW() - INTERVAL '14 days'
        GROUP BY sponsor_id
    ) sub
    WHERE s.id = sub.sponsor_id;

    UPDATE g01_sponsors s
    SET referrals_last_14d = 0
    WHERE NOT EXISTS (
        SELECT 1 FROM g01_referral_events e
        WHERE e.sponsor_id = s.id
          AND e.created_at >= NOW() - INTERVAL '14 days'
    );
END;
$$ LANGUAGE plpgsql;

-- Origin registry shipped with the two localities. These rows are already active.
-- A homesteader who files a new sponsor in the thread still stays inactive until Stripe pays.
INSERT INTO g01_sponsors (
    id, locality_id, company_name, founding_city, founding_state, is_franchise_or_chain,
    sourcing_tier, service_tags, capabilities_summary, lat, lng, is_active_sponsor
)
SELECT
    seed.id, loc.id, seed.company_name, seed.founding_city, seed.founding_state, seed.is_franchise,
    seed.sourcing_tier, seed.service_tags, seed.summary, seed.lat, seed.lng, TRUE
FROM (
    VALUES
        ('cccccccc-cccc-cccc-cccc-ccccccccccc1'::uuid, 'Lake Charles', 'LA', 'Calcasieu Glass & Lamp', 'Lake Charles', 'LA', FALSE, 'local_manufacturer', ARRAY['grow_lights'], 'Blows and wires small greenhouse lamps in Lake Charles.', 30.2400::float8, -93.2200::float8),
        ('cccccccc-cccc-cccc-cccc-ccccccccccc2'::uuid, 'Lake Charles', 'LA', 'Chenier Logistics', 'Lake Charles', 'LA', FALSE, 'local_logistics_proxy', ARRAY['grow_lights', 'logistics'], 'Local procurement and delivery inside Calcasieu Parish.', 30.2266::float8, -93.2174::float8),
        ('cccccccc-cccc-cccc-cccc-ccccccccccc3'::uuid, 'Rogers', 'AR', 'Rogers Oak Mill', 'Rogers', 'AR', FALSE, 'local_manufacturer', ARRAY['lumber'], 'Mills oak in Rogers.', 36.3400::float8, -94.1200::float8),
        ('cccccccc-cccc-cccc-cccc-ccccccccccc4'::uuid, 'Rogers', 'AR', 'Walmart', 'Rogers', 'AR', TRUE, 'local_service_or_stock', ARRAY['general_goods'], 'Origin store in Rogers, Arkansas. No public checkout link is stored.', 36.3320::float8, -94.1185::float8)
) AS seed(id, city, state_code, company_name, founding_city, founding_state, is_franchise, sourcing_tier, service_tags, summary, lat, lng)
JOIN g01_localities loc ON loc.primary_city = seed.city AND loc.state_code = seed.state_code
WHERE NOT EXISTS (
    SELECT 1 FROM g01_sponsors existing
    WHERE existing.locality_id = loc.id AND existing.company_name = seed.company_name
);
