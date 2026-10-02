-- Apply in the Supabase SQL editor before starting API + worker.
-- Only the backend service role can mutate documents/jobs. User reads are owner-scoped.
begin;

create table public.documents (
    doc_id uuid primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    size_bytes bigint not null check (size_bytes >= 0),
    storage_key text not null unique,
    status text not null default 'uploading' check (status in
        ('uploading','queued','processing','ready','error','deleting','delete_error','deleted')),
    active_index_id uuid,
    chunks_count integer not null default 0,
    warnings jsonb not null default '[]',
    error text,
    cleanup_after timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index documents_owner_created on public.documents(user_id, created_at desc, doc_id);

create table public.document_jobs (
    job_id uuid primary key default gen_random_uuid(),
    doc_id uuid not null references public.documents(doc_id) on delete cascade,
    kind text not null check (kind in ('index','delete')),
    state text not null default 'queued' check (state in ('queued','running','done','failed')),
    attempts integer not null default 0,
    lease_token uuid,
    lease_expires_at timestamptz,
    generations uuid[] not null default '{}',
    error text,
    created_at timestamptz not null default now()
);
create unique index document_jobs_active on public.document_jobs(doc_id, kind)
    where state in ('queued','running');
create index document_jobs_poll on public.document_jobs(state, lease_expires_at, created_at);

alter table public.documents enable row level security;
alter table public.document_jobs enable row level security;
revoke all on public.documents, public.document_jobs from anon, authenticated;
grant select on public.documents to authenticated;
grant all on public.documents, public.document_jobs to service_role;
create policy documents_owner_read on public.documents for select to authenticated
    using (user_id = (select auth.uid()) and status <> 'deleted');

create function public.queue_document_job(p_doc_id uuid, p_user_id uuid, p_kind text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare d public.documents;
begin
    select * into d from documents where doc_id = p_doc_id and user_id = p_user_id for update;
    if not found then raise exception 'Document not found' using errcode = 'P0002'; end if;
    if p_kind = 'index' then
        if d.status in ('queued','processing') then return to_jsonb(d); end if;
        if d.status not in ('uploading','error') then
            raise exception 'Document cannot be indexed in this state' using errcode = 'P0001';
        end if;
        update documents set status = 'queued', error = null, updated_at = now() where doc_id = p_doc_id;
    elsif p_kind = 'delete' then
        if d.status = 'deleted' then return to_jsonb(d); end if;
        if d.status = 'uploading' then
            raise exception 'Upload is still in progress' using errcode = 'P0001';
        end if;
        update documents set status = 'deleting', active_index_id = null, error = null,
            updated_at = now() where doc_id = p_doc_id;
        update document_jobs set state = 'failed', error = 'Document deleted'
            where doc_id = p_doc_id and kind = 'index' and state = 'queued';
    else
        raise exception 'Unknown job kind';
    end if;
    insert into document_jobs(doc_id, kind) values (p_doc_id, p_kind)
        on conflict (doc_id, kind) where state in ('queued','running') do nothing;
    select * into d from documents where doc_id = p_doc_id;
    return to_jsonb(d);
end $$;

create function public.claim_document_job(p_lease_seconds integer default 120)
returns jsonb language plpgsql security definer set search_path = public as $$
declare j public.document_jobs; d public.documents; token uuid := gen_random_uuid();
begin
    -- An API process may die between creating the row, storing bytes and enqueuing.
    update documents set status = 'error', error = 'Tải lên bị gián đoạn. Hãy thử lại hoặc tải lại PDF.',
        updated_at = now() where status = 'uploading' and updated_at < now() - interval '15 minutes';
    select q.* into j from document_jobs q join documents x using (doc_id)
        where (q.state = 'queued' or (q.state = 'running' and q.lease_expires_at < now()))
        and ((q.kind = 'index' and x.status in ('queued','processing'))
          or (q.kind = 'delete' and x.status = 'deleting' and not exists (
            select 1 from document_jobs live where live.doc_id = q.doc_id and live.kind = 'index'
            and live.state = 'running' and live.lease_expires_at >= now())))
        order by q.created_at limit 1 for update of q, x skip locked;
    if not found then return null; end if;
    if j.attempts >= 3 then
        update document_jobs set state = 'failed', error = 'Worker repeatedly interrupted' where job_id = j.job_id;
        update documents set status = case when j.kind = 'delete' then 'delete_error' else 'error' end,
            error = 'Xử lý bị gián đoạn nhiều lần. Vui lòng thử lại.', updated_at = now() where doc_id = j.doc_id;
        return null;
    end if;
    update document_jobs set state = 'running', attempts = attempts + 1, lease_token = token,
        lease_expires_at = now() + make_interval(secs => greatest(15, p_lease_seconds)),
        generations = case when kind = 'index' then array_append(generations, token) else generations end
        where job_id = j.job_id returning * into j;
    update documents set status = case when j.kind = 'index' then 'processing' else 'deleting' end,
        updated_at = now() where doc_id = j.doc_id returning * into d;
    return to_jsonb(j) || jsonb_build_object('document', to_jsonb(d));
end $$;

create function public.heartbeat_document_job(p_job_id uuid, p_token uuid, p_lease_seconds integer)
returns boolean language plpgsql security definer set search_path = public as $$
begin
    update document_jobs j set lease_expires_at = now() + make_interval(secs => greatest(15, p_lease_seconds))
        where j.job_id = p_job_id and j.lease_token = p_token and j.state = 'running'
        and j.lease_expires_at > now();
    return found;
end $$;

create function public.finish_document_job(p_job_id uuid, p_token uuid, p_error text default null,
    p_chunks_count integer default 0, p_warnings jsonb default '[]')
returns boolean language plpgsql security definer set search_path = public as $$
declare j public.document_jobs; d public.documents;
begin
    -- Lock in the same document/job order as queue_document_job.
    select x.* into d from documents x join document_jobs q using(doc_id)
        where q.job_id = p_job_id for update of x;
    select * into j from document_jobs where job_id = p_job_id for update;
    if not found or j.state <> 'running' or j.lease_token <> p_token or j.lease_expires_at <= now() then
        return false;
    end if;
    update document_jobs set state = case when p_error is null then 'done' else 'failed' end,
        error = p_error, lease_expires_at = null where job_id = p_job_id;
    if j.kind = 'index' and d.status = 'processing' then
        update documents set status = case when p_error is null then 'ready' else 'error' end,
            active_index_id = case when p_error is null then p_token else null end,
            chunks_count = p_chunks_count, warnings = p_warnings, error = p_error, updated_at = now()
            where doc_id = j.doc_id;
        return p_error is null;
    elsif j.kind = 'delete' and d.status = 'deleting' then
        update documents set status = case when p_error is null then 'deleted' else 'delete_error' end,
            active_index_id = null, chunks_count = 0, error = p_error, updated_at = now(),
            cleanup_after = case when p_error is null then now() + interval '5 minutes' else null end
            where doc_id = j.doc_id;
        return p_error is null;
    end if;
    return false;
end $$;

revoke all on function public.queue_document_job(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.claim_document_job(integer) from public, anon, authenticated;
revoke all on function public.heartbeat_document_job(uuid,uuid,integer) from public, anon, authenticated;
revoke all on function public.finish_document_job(uuid,uuid,text,integer,jsonb) from public, anon, authenticated;
grant execute on function public.queue_document_job(uuid,uuid,text) to service_role;
grant execute on function public.claim_document_job(integer) to service_role;
grant execute on function public.heartbeat_document_job(uuid,uuid,integer) to service_role;
grant execute on function public.finish_document_job(uuid,uuid,text,integer,jsonb) to service_role;
commit;
