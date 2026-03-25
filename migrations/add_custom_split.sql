-- Add custom_split column to expenses table
-- This tracks whether an expense used a custom split percentage (e.g., "50 boots, 100%")

ALTER TABLE expenses ADD COLUMN custom_split BOOLEAN DEFAULT 0;
