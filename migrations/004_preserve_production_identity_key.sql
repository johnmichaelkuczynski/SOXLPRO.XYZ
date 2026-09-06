DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'user_access'
          AND column_name = 'auth_user_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'user_access'
          AND column_name = 'clerk_user_id'
    ) THEN
        ALTER TABLE public.user_access
            RENAME COLUMN auth_user_id TO clerk_user_id;
    END IF;
END
$$;