create table if not exists customer_state (
    customer_id text primary key,
    stripe_customer_id text unique not null,
    plan text not null default 'starter' check (plan in ('starter','pro','enterprise')),
    status text not null default 'active' check (status in ('active','suspended','cancelled')),
    contact_email text not null,
    deployment_namespace text unique,
    company_name text,
    industry_vertical text,
    scale_classification text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function update_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end; $$;
drop trigger if exists customer_state_updated_at on customer_state;
create trigger customer_state_updated_at before update on customer_state for each row execute function update_updated_at();

create table if not exists authenticated_events (
    event_id text primary key,
    event_type text not null check (event_type in ('stripe_webhook','telemetry_batch')),
    customer_id text references customer_state(customer_id),
    session_id text not null,
    authenticated_at timestamptz not null default now(),
    expires_at timestamptz,
    metadata jsonb not null default '{}'
);
create index if not exists idx_events_customer on authenticated_events(customer_id);
create index if not exists idx_events_session on authenticated_events(session_id);
create index if not exists idx_events_expiry on authenticated_events(expires_at);

create table if not exists authority_gate_audit (
    id bigserial primary key,
    action_id text unique not null,
    verdict text not null check (verdict in ('AUTHORIZED','REJECTED')),
    verdict_code text not null,
    verdict_reason text not null,
    tpa jsonb not null,
    policy_checks jsonb not null,
    escalation jsonb,
    customer_id text,
    action_class text,
    logged_at timestamptz not null default now(),
    check ((verdict = 'AUTHORIZED' and verdict_code = 'AUTHORIZED') or (verdict = 'REJECTED' and verdict_code <> 'AUTHORIZED'))
);
create index if not exists idx_audit_customer on authority_gate_audit(customer_id);
create index if not exists idx_audit_verdict on authority_gate_audit(verdict);
create index if not exists idx_audit_code on authority_gate_audit(verdict_code);
create index if not exists idx_audit_logged_at on authority_gate_audit(logged_at);

create or replace function prevent_audit_mutation() returns trigger language plpgsql security definer as $$
begin raise exception 'authority_gate_audit is append-only'; end; $$;
drop trigger if exists authority_gate_audit_no_update on authority_gate_audit;
create trigger authority_gate_audit_no_update before update or delete on authority_gate_audit for each row execute function prevent_audit_mutation();

create table if not exists escalations (
    escalation_id text primary key,
    action_id text references authority_gate_audit(action_id),
    verdict_code text not null,
    priority int not null check (priority between 1 and 4),
    status text not null default 'open' check (status in ('open','in_review','resolved','bypassed')),
    linear_issue_id text,
    resolved_by text,
    resolved_at timestamptz,
    approval_token text,
    created_at timestamptz not null default now()
);

create table if not exists deployments (
    deployment_id text primary key,
    action_id text unique references authority_gate_audit(action_id),
    customer_id text references customer_state(customer_id),
    environment text not null,
    platform text not null check (platform in ('vercel','cloudflare_workers','railway')),
    status text not null default 'provisioning' check (status in ('provisioning','active','rolled_back','failed')),
    deployment_config jsonb,
    deployed_at timestamptz not null default now(),
    rolled_back_at timestamptz
);

create table if not exists pipeline_sessions (
    session_id text primary key,
    customer_id text references customer_state(customer_id),
    originating_event_id text not null unique,
    agent_ids text[] not null,
    status text not null default 'active' check (status in ('active','completed','expired','rejected')),
    opened_at timestamptz not null default now(),
    closed_at timestamptz,
    world_state_hash text not null
);
create index if not exists idx_session_customer on pipeline_sessions(customer_id);
create index if not exists idx_session_status on pipeline_sessions(status);

create or replace function prevent_event_mutation() returns trigger language plpgsql security definer as $$
begin raise exception 'authenticated_events is immutable'; end; $$;
drop trigger if exists authenticated_events_no_update on authenticated_events;
create trigger authenticated_events_no_update before update or delete on authenticated_events for each row execute function prevent_event_mutation();

create or replace function protect_session_identity() returns trigger language plpgsql as $$
begin
    if new.session_id <> old.session_id
       or new.customer_id is distinct from old.customer_id
       or new.originating_event_id <> old.originating_event_id
       or new.agent_ids <> old.agent_ids
       or new.world_state_hash <> old.world_state_hash then
        raise exception 'immutable pipeline session identity changed';
    end if;
    return new;
end; $$;
drop trigger if exists pipeline_session_identity_protection on pipeline_sessions;
create trigger pipeline_session_identity_protection before update on pipeline_sessions for each row execute function protect_session_identity();

create or replace function open_pipeline_session(
    p_event_id text, p_event_type text, p_customer_id text, p_session_id text,
    p_agent_ids text[], p_world_state_hash text, p_expires_at timestamptz
) returns pipeline_sessions language plpgsql security definer as $$
declare existing_session pipeline_sessions;
begin
    select * into existing_session from pipeline_sessions where originating_event_id = p_event_id for update;
    if existing_session.session_id is not null then
        if existing_session.customer_id is distinct from p_customer_id then
            raise exception 'event already bound to another customer';
        end if;
        return existing_session;
    end if;

    insert into authenticated_events(event_id,event_type,customer_id,session_id,expires_at,metadata)
    values (p_event_id,p_event_type,p_customer_id,p_session_id,p_expires_at,jsonb_build_object('source','stripe_webhook'));

    insert into pipeline_sessions(session_id,customer_id,originating_event_id,agent_ids,status,world_state_hash)
    values (p_session_id,p_customer_id,p_event_id,p_agent_ids,'active',p_world_state_hash)
    returning * into existing_session;

    return existing_session;
end; $$;

revoke all on function open_pipeline_session(text,text,text,text,text[],text,timestamptz) from public;
