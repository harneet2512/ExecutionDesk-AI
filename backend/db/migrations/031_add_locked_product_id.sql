-- Migration 031: Add locked_product_id to runs table
-- This column stores the product_id that was confirmed by the user.
-- The execution node MUST use this product_id and never recompute.
-- Also adds tradability_verified flag to confirm preflight was run.

ALTER TABLE runs ADD COLUMN locked_product_id TEXT;
ALTER TABLE runs ADD COLUMN tradability_verified INTEGER DEFAULT 0;
