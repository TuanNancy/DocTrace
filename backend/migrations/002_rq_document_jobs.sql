-- Stop the old API/worker before applying. Apply after 001; retain its tables for rollback inspection.
-- Redis/RQ owns delivery and execution. These transactions own document intent and publication.
begin;

create table public.document_operations (
    operation_id uuid primary key default gen_random_uuid(),
    doc_id uuid not null references public.documents(doc_id) on delete cascade,
    kind text not null check (kind in ('index','delete')),
    state text not null default 'pending' check (state in ('pending','done','failed','superseded')),
    delivery integer not null default 0,
    dispatched_at timestamptz,
    attempts integer not null default 0,
    attempt_id uuid,
    attempt_expires_at timestamptz,
    available_at timestamptz not null default now(),
    error text,
    created_at timestamptz not null default now()
);
create index document_operations_pending on public.document_operations(operation_id) where state = 'pending';
create index document_operations_document on public.document_operations(doc_id);
alter table public.documents add column current_operation_id uuid references public.document_operations(operation_id);

create table public.document_generations (
    generation_id uuid primary key,
    doc_id uuid not null references public.documents(doc_id) on delete cascade,
    cleanup_after timestamptz not null default now()
);
create index document_generations_document on public.document_generations(doc_id);
alter table public.document_operations enable row level security;
alter table public.document_generations enable row level security;
revoke all on public.document_operations, public.document_generations from public, anon, authenticated;
grant all on public.document_operations, public.document_generations to service_role;

-- Preserve EVERY recorded generation, including unpublished/late writes and active legacy indexes.
insert into document_generations(generation_id, doc_id)
select distinct unnest(generations), doc_id from document_jobs on conflict do nothing;
insert into document_generations(generation_id, doc_id)
select active_index_id, doc_id from documents where active_index_id is not null on conflict do nothing;
insert into document_operations(doc_id, kind)
select doc_id, case when status = 'deleting' then 'delete' else 'index' end
from documents where status in ('queued','processing','deleting');
update documents d set current_operation_id = o.operation_id,
    status = case when o.kind = 'index' then 'queued' else 'deleting' end, updated_at = now()
from document_operations o where o.doc_id = d.doc_id;
update documents set cleanup_after = now() where doc_id in (select doc_id from document_generations)
    or status = 'deleted';

-- Old binaries must fail closed: even an old worker finishing after cutover cannot publish.
drop function public.queue_document_job(uuid,uuid,text);
drop function public.claim_document_job(integer);
drop function public.heartbeat_document_job(uuid,uuid,integer);
drop function public.finish_document_job(uuid,uuid,text,integer,jsonb);
revoke all on public.document_jobs from service_role;

create function public.request_document_operation(p_doc_id uuid, p_user_id uuid, p_kind text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare d documents; op uuid;
begin
    select * into d from documents where doc_id = p_doc_id and user_id = p_user_id for update;
    if not found then raise exception 'Document not found' using errcode = 'P0002'; end if;
    if p_kind = 'index' then
        if d.status in ('queued','processing') then return to_jsonb(d); end if;
        if d.status not in ('uploading','error') then
            raise exception 'Document cannot be indexed' using errcode = 'P0001';
        end if;
    elsif p_kind = 'delete' then
        if d.status in ('deleted','deleting') then return to_jsonb(d); end if;
        if d.status = 'uploading' then raise exception 'Upload in progress' using errcode = 'P0001'; end if;
    else raise exception 'Unknown operation'; end if;
    update document_operations set state = 'superseded' where doc_id = p_doc_id and state = 'pending';
    insert into document_operations(doc_id, kind) values(p_doc_id, p_kind) returning operation_id into op;
    update documents set current_operation_id = op, active_index_id = null, error = null,
        status = case when p_kind = 'index' then 'queued' else 'deleting' end, updated_at = now()
        where doc_id = p_doc_id returning * into d;
    return to_jsonb(d);
end $$;

create function public.begin_document_attempt(p_operation_id uuid, p_delivery integer, p_timeout integer)
returns jsonb language plpgsql security definer set search_path = public as $$
declare d documents; o document_operations; token uuid := gen_random_uuid();
begin
    -- All lifecycle RPCs lock document before operation.
    select x.* into d from documents x join document_operations j using(doc_id)
        where j.operation_id = p_operation_id for update of x;
    select * into o from document_operations where operation_id = p_operation_id for update;
    if not found or d.current_operation_id is distinct from o.operation_id or o.state <> 'pending'
        or o.delivery is distinct from p_delivery or o.available_at > now() then return null; end if;
    if o.attempt_expires_at is not null then return null; end if;
    if o.kind = 'delete' and exists(select 1 from document_operations
        where doc_id = d.doc_id and kind = 'index' and attempt_expires_at > now()) then return null; end if;
    if o.attempts >= 3 then
        update document_operations set state = 'failed', error = 'Attempt budget exhausted' where operation_id = o.operation_id;
        update documents set status = case when o.kind = 'index' then 'error' else 'delete_error' end,
            error = 'Xử lý bị gián đoạn nhiều lần. Vui lòng thử lại.', updated_at = now() where doc_id = d.doc_id;
        return null;
    end if;
    update document_operations set attempts = attempts + 1, attempt_id = token,
        attempt_expires_at = now() + make_interval(secs => greatest(1,p_timeout) + 60), error = null
        where operation_id = o.operation_id returning * into o;
    if o.kind = 'index' then
        insert into document_generations(generation_id, doc_id, cleanup_after)
            values(token, d.doc_id, o.attempt_expires_at + interval '60 seconds');
    end if;
    update documents set status = case when o.kind = 'index' then 'processing' else 'deleting' end,
        cleanup_after = coalesce(cleanup_after, now()), updated_at = now() where doc_id = d.doc_id returning * into d;
    return to_jsonb(o) || jsonb_build_object('document', to_jsonb(d));
end $$;

create function public.finish_document_attempt(p_operation_id uuid, p_attempt_id uuid,
    p_error text default null, p_retryable boolean default false,
    p_chunks_count integer default 0, p_warnings jsonb default '[]')
returns boolean language plpgsql security definer set search_path = public as $$
declare d documents; o document_operations;
begin
    select x.* into d from documents x join document_operations j using(doc_id)
        where j.operation_id = p_operation_id for update of x;
    select * into o from document_operations where operation_id = p_operation_id for update;
    if not found or o.attempt_id is distinct from p_attempt_id or o.attempt_expires_at is null then return false; end if;
    -- Even superseded writers can announce they stopped, allowing deletion to proceed sooner.
    if o.state <> 'pending' or d.current_operation_id is distinct from o.operation_id then
        update document_operations set attempt_expires_at = null where operation_id = o.operation_id;
        return false;
    end if;
    if o.attempt_expires_at <= now() then return false; end if;
    update document_operations set attempt_expires_at = null, error = p_error,
        state = case when p_error is null then 'done' when p_retryable and attempts < 3 then 'pending' else 'failed' end,
        available_at = now() + make_interval(secs => case when attempts = 1 then 10 else 30 end)
        where operation_id = o.operation_id;
    if p_error is not null then
        update documents set status = case when p_retryable and o.attempts < 3
            then case when o.kind = 'index' then 'queued' else 'deleting' end
            else case when o.kind = 'index' then 'error' else 'delete_error' end end,
            error = case when p_retryable and o.attempts < 3 then null else p_error end,
            updated_at = now() where doc_id = d.doc_id;
        return false;
    end if;
    update documents set status = case when o.kind = 'index' then 'ready' else 'deleted' end,
        active_index_id = case when o.kind = 'index' then p_attempt_id else null end,
        chunks_count = p_chunks_count, warnings = p_warnings, error = null, cleanup_after = now() + interval '1 minute',
        updated_at = now() where doc_id = d.doc_id;
    return true;
end $$;

-- Compare-and-swap protects against another dispatcher and a concurrently finishing worker.
-- A hard deadline replaces the old renewable SQL lease. RQ owns process heartbeats/timeouts.
create function public.recover_document_operation(p_operation_id uuid, p_delivery integer,
    p_attempt_id uuid, p_terminal boolean default false)
returns boolean language plpgsql security definer set search_path = public as $$
declare d documents; o document_operations;
begin
    select x.* into d from documents x join document_operations j using(doc_id)
        where j.operation_id = p_operation_id for update of x;
    select * into o from document_operations where operation_id = p_operation_id for update;
    if not found or o.state <> 'pending' or d.current_operation_id is distinct from o.operation_id
        or o.delivery <> p_delivery or o.attempt_id is distinct from p_attempt_id
        or o.available_at > now() or o.attempt_expires_at > now() then return false; end if;
    if p_terminal or o.attempts >= 3 then
        update document_operations set state = 'failed', attempt_expires_at = null where operation_id = o.operation_id;
        update documents set status = case when o.kind = 'index' then 'error' else 'delete_error' end,
            error = 'Xử lý không hoàn tất. Vui lòng thử lại.', updated_at = now() where doc_id = d.doc_id;
    else
        update document_operations set delivery = delivery + 1, attempt_id = null, attempt_expires_at = null,
            dispatched_at = null where operation_id = o.operation_id;
        update documents set status = case when o.kind = 'index' then 'queued' else 'deleting' end,
            updated_at = now() where doc_id = d.doc_id;
    end if;
    return true;
end $$;

create function public.document_cleanup_candidates(p_doc_id uuid)
returns jsonb language sql security definer set search_path = public as $$
    select coalesce(jsonb_agg(g.generation_id), '[]'::jsonb) from document_generations g
    join documents d using(doc_id) where g.doc_id = p_doc_id and g.cleanup_after <= now()
        and g.generation_id is distinct from d.active_index_id
        and not exists(select 1 from document_operations o where o.doc_id = g.doc_id
            and o.attempt_id = g.generation_id and o.attempt_expires_at > now());
$$;

-- Fix stale upload metadata even when no indexing jobs are available.
create function public.recover_stale_document_uploads()
returns void language sql security definer set search_path = public as $$
    update documents set status = 'error', error = 'Tải lên bị gián đoạn. Hãy thử lại hoặc tải lại PDF.', updated_at = now()
    where status = 'uploading' and updated_at < now() - interval '15 minutes';
$$;

revoke all on function public.request_document_operation(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.begin_document_attempt(uuid,integer,integer) from public, anon, authenticated;
revoke all on function public.finish_document_attempt(uuid,uuid,text,boolean,integer,jsonb) from public, anon, authenticated;
revoke all on function public.recover_document_operation(uuid,integer,uuid,boolean) from public, anon, authenticated;
revoke all on function public.document_cleanup_candidates(uuid) from public, anon, authenticated;
revoke all on function public.recover_stale_document_uploads() from public, anon, authenticated;
grant execute on function public.request_document_operation(uuid,uuid,text) to service_role;
grant execute on function public.begin_document_attempt(uuid,integer,integer) to service_role;
grant execute on function public.finish_document_attempt(uuid,uuid,text,boolean,integer,jsonb) to service_role;
grant execute on function public.recover_document_operation(uuid,integer,uuid,boolean) to service_role;
grant execute on function public.document_cleanup_candidates(uuid) to service_role;
grant execute on function public.recover_stale_document_uploads() to service_role;
commit;
