-- CHOQUE BGR — baseline RLS for the future single-cut PostgreSQL migration.
-- Run only after the PostgreSQL schema migration has created these tables.
-- The browser has no direct database access: anon/authenticated remain default-deny.

begin;

do $$
declare
    table_name text;
    protected_tables text[] := array[
        'recruitment_form_versions',
        'recruitment_question_groups',
        'recruitment_questions',
        'recruitment_form_version_questions',
        'recruitment_campaigns',
        'recruitment_applications',
        'recruitment_application_questions',
        'recruitment_integrity_events',
        'recruitment_reviews',
        'recruitment_interviews',
        'recruitment_evaluations',
        'recruitment_internal_notes',
        'recruitment_adaptations',
        'recruitment_cooldowns',
        'recruitment_blocks',
        'recruitment_history',
        'recruitment_notification_outbox',
        'recruit_followups'
    ];
begin
    foreach table_name in array protected_tables loop
        if to_regclass(format('public.%I', table_name)) is null then
            raise exception 'Required recruitment table public.% is missing', table_name;
        end if;
        execute format('alter table public.%I enable row level security', table_name);
        execute format('alter table public.%I force row level security', table_name);
        execute format('revoke all on table public.%I from anon, authenticated', table_name);
    end loop;
end
$$;

-- Intentionally no browser policy is created. Candidate and administrative access
-- is mediated by the authenticated Railway API, which applies ownership and RBAC.

commit;
